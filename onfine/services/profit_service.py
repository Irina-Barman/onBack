"""
Модуль управления прибылью от майнинга оборудования.

Основные функции:
- record_mined(): Фиксирует добычу USDT за определённый период для заданного оборудования,
  вычисляет операционные расходы и создаёт новый батч прибыли с распределительной суммой.
- distribute_batch(): Распределяет прибыль из батча среди инвесторов оборудования пропорционально
  их чистым инвестициям, создаёт транзакции, записи в бухгалтерском журнале и зачисляет средства на баланс.

Зависимости:
- decimal.Decimal, decimal.ROUND_DOWN: Для точных денежных расчётов с округлением вниз.
- typing.Any: Для аннотаций типов (например, для периодов).
- SQLAlchemy (db): Для работы с базой данных.
- Модели: EquipmentInvestment, MiningEquipment, MiningProfitBatch, Transaction, TxStatus, TxType, LedgerEntry, LedgerType.
- wallet_service (wsvc): Сервис для зачисления средств на баланс пользователя (credit_to_balance).

Функции:

record_mined(equipment_id: int, mined_usdt: Decimal, period_start: Any, period_end: Any) -> MiningProfitBatch
    Фиксирует добычу USDT за период для заданного оборудования.
    Вычисляет операционные расходы на основе процента OPEX оборудования и создаёт новый батч прибыли.

distribute_batch(batch_id: int) -> None
    Распределяет распределительную сумму из батча среди инвесторов оборудования.
    Пропорционально чистым инвестициям каждого инвестора вычисляет выплату, создаёт транзакцию типа 'profit',
    запись в бухгалтерском журнале и зачисляет сумму на основной баланс (ERC) как депозит.
    Если суммарная чистая инвестиция равна нулю, функция завершается без действий.
"""

from decimal import ROUND_DOWN, Decimal
from typing import Any

from ..extensions import db
from ..models import (
    EquipmentInvestment,
    MiningEquipment,
    MiningProfitBatch,
    Transaction,
    TxStatus,
    TxType,
)
from ..models.ledger_entry import LedgerEntry, LedgerType
from ..services import wallet_service as wsvc


def record_mined(
    equipment_id: int,
    mined_usdt: Decimal,
    period_start: Any,
    period_end: Any,
) -> MiningProfitBatch:
    """
    Фиксирует добычу за период, создавая новый Batch.

    Параметры:
        equipment_id (int): Идентификатор оборудования.
        mined_usdt (Decimal): Сумма добытого в USDT.
        period_start (Any): Начало периода.
        period_end (Any): Конец периода.

    Return:
        MiningProfitBatch: Созданный объект Batch.
    """
    eq = MiningEquipment.query.get(equipment_id)
    opex = (mined_usdt * (eq.opex_pct / 100)).quantize(Decimal("0.01"))
    dist = mined_usdt - opex

    batch = MiningProfitBatch(
        equipment_id=equipment_id,
        mined_usdt=mined_usdt,
        opex_usdt=opex,
        distributable=dist,
        period_start=period_start,
        period_end=period_end,
    )
    db.session.add(batch)
    db.session.commit()
    return batch


def distribute_batch(batch_id: int) -> None:
    """
    Распределяет добычу среди инвесторов на основе их доли в общей чистой
    инвестиции.

    Параметры:
        batch_id (int): Идентификатор батча для распределения.

    Return:
        None: Функция не Return значения. Все изменения сохраняются в базе
        данных.
    """
    batch = MiningProfitBatch.query.get(batch_id)
    eq_id = batch.equipment_id
    dist = batch.distributable

    # Суммарная net-инвестиция
    total_net = (
        db.session.query(
            db.func.coalesce(db.func.sum(EquipmentInvestment.net_amount), 0),
        )
        .filter_by(equipment_id=eq_id)
        .scalar()
    )

    if total_net == 0:
        return

    investments = EquipmentInvestment.query.filter_by(equipment_id=eq_id).all()
    for inv in investments:
        share = inv.net_amount / total_net
        payout = (dist * share).quantize(Decimal("0.01"), ROUND_DOWN)
        if payout == 0:
            continue

        tx = Transaction(
            user_id=inv.user_id,
            type=TxType.profit,
            status=TxStatus.confirmed,
            network="profit",
            amount=payout,
        )
        db.session.add(tx)
        db.session.flush()

        db.session.add(
            LedgerEntry(
                user_id=inv.user_id,
                origin_table="transactions",
                origin_id=tx.id,
                type=LedgerType.profit,
                direction="in",
                network="profit",
                amount=payout,
            ),
        )

        # Кладём на основной баланс (ERC) как депозит
        wsvc.credit_to_balance(inv.user_id, "erc", payout)

    db.session.commit()
