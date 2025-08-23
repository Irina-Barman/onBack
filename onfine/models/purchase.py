# onfine/models/purchase.py
from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy.dialects.postgresql import BYTEA
from sqlalchemy.sql import func

from onfine.extensions import db


class PurchaseStatus(str, Enum):
    """
    Высокоуровневый финальный статус покупки.
    Используется для бизнес‑логики и отчетности.
    """

    pending = "pending"  # создана и находится в процессе
    completed = "completed"  # успешно завершена
    canceled = "canceled"  # отменена (по таймауту/ошибке/пользователем)
    failed = "failed"  # ошибка (не удалось провести)


class PurchaseStep(str, Enum):
    """
    Пошаговый тех. статус (жизненный цикл gasless‑покупки).
    Используется воркерами/оркестраторами.
    """

    pending = "pending"  # создано
    gas_enqueued = "gas_enqueued"  # событие на топап газа отправлено в очередь
    gas_sent = "gas_sent"  # нативка отправлена (tx платформы опубликован)
    gas_ready = "gas_ready"  # подтверждено поступление нативки/баланс покрывает fee
    usdt_sent = "usdt_sent"  # опубликована/подтверждается USDT‑транзакция пользователя
    completed = "completed"  # завершено успешно
    failed = "failed"  # завершено с ошибкой


class Purchase(db.Model):
    """
    Покупка пакета пользователем (gasless‑flow совместима).
    - Финальный статус: PurchaseStatus
    - Промежуточные шаги: PurchaseStep
    - Поля для EVM/TRON: reserved_nonce, user_raw_tx, user_tx_hash
    - Учёт расходов платформы на газ: gas_topup_* и связь на PlatformGasExpense
    """

    __tablename__ = "purchases"

    id = db.Column(db.Integer, primary_key=True)

    # Кто и что покупает
    user_id = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=False, index=True)
    package_id = db.Column(db.Integer, db.ForeignKey("packages.id"), nullable=False, index=True)

    # Какой кошелёк в сети задействован (наш пользовательский адрес в соответствующей сети)
    wallet_id = db.Column(db.Integer, db.ForeignKey("wallets.id"), nullable=True, index=True)

    # Денежные параметры (фиксируются на момент создания)
    amount_usdt = db.Column(db.Numeric(18, 2), nullable=False)  # цена пакета (строго 50/100/…)
    gas_usdt = db.Column(db.Numeric(18, 2), nullable=False)  # эквивалент комиссии сети в USDT (для аналитики)
    network = db.Column(
        db.String(8),
        nullable=False,
        index=True,
    )  # 'erc20' | 'bep20' | 'trc20' (или 'ERC20'/'BEP20'/'TRC20' — держи консистентно в сервисах)

    # Статусы
    status = db.Column(db.Enum(PurchaseStatus), default=PurchaseStatus.pending, nullable=False, index=True)
    step = db.Column(db.Enum(PurchaseStep), default=PurchaseStep.pending, nullable=False, index=True)

    # Временные метки
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now())
    confirmed_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    # Отладочная/служебная метка (если создано бэчем/миграцией и т.п.)
    is_from_database = db.Column(db.Boolean, default=False)

    # ======== Технические поля под gasless (EVM/TRON) ========

    # Nonce, занятый под этот перевод (для EVM); для TRON может быть неиспользуемым.
    reserved_nonce = db.Column(db.Integer, nullable=True)

    # Предподписанная транзакция пользователя:
    # - EVM: RLP raw bytes user transfer(USDT -> platform)
    # - TRON: signed bytes (или можно оставлять пустым и подписывать в confirm worker)
    user_raw_tx = db.Column(BYTEA, nullable=True)

    # Хэш опубликованной user‑транзакции (EVM tx hash / TRON txid)
    user_tx_hash = db.Column(db.String(128), nullable=True, index=True)

    # Флаг: подозрение на попытку замены транзакции (replacement/fraud)
    fraud_suspected = db.Column(db.Boolean, default=False, nullable=False)

    # Фактические данные по газу (нативная монета, в единицах сети; precision 18 хватает для ETH/BNB/TRX)
    gas_topup_amount_native = db.Column(db.Numeric(38, 18), nullable=True)
    gas_topup_tx = db.Column(db.String(128), nullable=True, index=True)

    # Ссылка на запись расходов платформы (если ведёшь отдельную таблицу расходов)
    gas_topup_expense_id = db.Column(db.Integer, db.ForeignKey("platform_gas_expenses.id"), nullable=True, index=True)

    # Адрес платформы (куда идут USDT) и адрес контракта USDT на момент создания
    platform_address = db.Column(db.String(128), nullable=True)
    usdt_token_contract = db.Column(db.String(128), nullable=True)

    # ======== Связи ========
    user = db.relationship("User", back_populates="purchases")
    package = db.relationship("Package", back_populates="purchases")
    wallet = db.relationship("Wallet")  # однонаправленной достаточно; можно back_populates добавить в Wallet
    transaction = db.relationship("Transaction", back_populates="purchase", uselist=False)

    # Если есть модель PlatformGasExpense — удобно завести связь (не обязательно bidirectional)
    gas_expense = db.relationship(
        "PlatformGasExpense",
        primaryjoin="Purchase.gas_topup_expense_id==PlatformGasExpense.id",
        foreign_keys="[Purchase.gas_topup_expense_id]",
        uselist=False,
    )

    # ======== Утилиты ========

    def mark_failed(self, reason: str | None = None) -> None:  # noqa: ARG002
        """
        Переводит покупку в финальный failed‑статус.
        Полезно вызывать из воркеров при необрабатываемых ошибках/таймаутах.
        """
        self.step = PurchaseStep.failed
        self.status = PurchaseStatus.failed
        # здесь при желании можно логировать reason в отдельную таблицу событий/аудита

    def mark_completed(self) -> None:
        """
        Переводит покупку в финальный completed‑статус.
        """
        self.step = PurchaseStep.completed
        self.status = PurchaseStatus.completed
        self.confirmed_at = datetime.utcnow()  # noqa: DTZ003
