# onfine/models/purchase.py
from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy.dialects.postgresql import BYTEA

from onfine.extensions import db


class PurchaseStatus(str, Enum):
    pending = "pending"
    completed = "completed"
    canceled = "canceled"
    failed = "failed"


class PurchaseStep(str, Enum):
    pending = "pending"
    gas_enqueued = "gas_enqueued"
    gas_sent = "gas_sent"
    gas_ready = "gas_ready"
    usdt_sent = "usdt_sent"
    completed = "completed"
    failed = "failed"


class Purchase(db.Model):
    __tablename__ = "purchases"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=False)
    package_id = db.Column(db.Integer, db.ForeignKey("packages.id"), nullable=False)
    wallet_id = db.Column(db.Integer, db.ForeignKey("wallets.id"), nullable=True, index=True)

    # бизнес-статус
    status = db.Column(db.Enum(PurchaseStatus), default=PurchaseStatus.pending, nullable=False, index=True)
    # тех. шаг пайплайна
    step = db.Column(db.Enum(PurchaseStep), default=PurchaseStep.pending, nullable=False, index=True)

    # суммы
    amount_usdt = db.Column(db.Numeric(18, 2), nullable=False)
    gas_usdt = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    network = db.Column(db.String(8), nullable=False)  # 'ERC20'|'BEP20'|'TRC20'

    # EVM nonce (для TRON None)
    reserved_nonce = db.Column(db.Integer, nullable=True)

    # предподписанные/отправленные транзакции
    user_raw_tx = db.Column(BYTEA, nullable=True)  # EVM RLP bytes / TRON raw
    user_tx_hash = db.Column(db.String(128), nullable=True)  # итоговый хэш перевода USDT

    # антифрод
    fraud_suspected = db.Column(db.Boolean, default=False)

    # данные по газу
    gas_topup_amount_native = db.Column(db.Numeric(38, 18), nullable=True)  # оценка/факт
    gas_topup_expense_id = db.Column(db.Integer, db.ForeignKey("platform_gas_expenses.id"))
    gas_topup_tx = db.Column(db.String(128), nullable=True)

    # фиксация реквизитов
    platform_address = db.Column(db.String(128), nullable=True)
    usdt_token_contract = db.Column(db.String(128), nullable=True)

    # опционально: поля лока кошелька (если хочешь «долгий» лок)
    wallet_lock_id = db.Column(db.Integer, nullable=True)
    wallet_lock_token = db.Column(db.String(64), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    confirmed_at = db.Column(db.DateTime, nullable=True)

    # связи
    package = db.relationship("Package", back_populates="purchases")
    user = db.relationship("User", back_populates="purchases")
    transaction = db.relationship("Transaction", back_populates="purchase", uselist=False)
    wallet = db.relationship("Wallet")

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
