"""
Модуль распределения доходов пула и раундов финансирования.

Основные функции:
- fetch_pool_income(): Получает доход пула за текущий день, вычисляет операционные расходы
  и распределяет оставшуюся сумму пропорционально по активным раундам финансирования.
- distribute_round(round_id): Распределяет доходы среди инвесторов указанного раунда,
  создаёт транзакции и записи в бухгалтерском журнале, а также зачисляет средства на баланс.

Константы:
- OPEX_PCT (Decimal): Доля операционных расходов (7%).

Зависимости:
- datetime.date: Для получения текущей даты.
- decimal.Decimal, decimal.ROUND_DOWN: Для точных денежных вычислений.
- SQLAlchemy (db): Для работы с базой данных.
- get_today_income_usdt: Внешний клиент для получения дохода пула за сегодня.
- Модели: FundingRound, RoundIncome, RoundInvestment, Transaction, LedgerEntry, LedgerType, TxStatus, TxType.
- credit_to_balance: Сервис для зачисления средств на баланс пользователя.

Функции:

fetch_pool_income() -> None
    Получает доход пула за текущий день, вычисляет операционные расходы (7%)
    и распределяет оставшуюся сумму между активными раундами финансирования
    пропорционально их капиталу.

    Если суммарный капитал равен нулю, функция завершает работу без действий.

distribute_round(round_id: int) -> None
    Распределяет накопленные доходы указанного раунда среди инвесторов
    пропорционально их инвестициям.

    Для каждого инвестора создаёт транзакцию типа "прибыль", запись в бухгалтерском журнале
    и зачисляет сумму на баланс.
    После распределения удаляет записи о доходах раунда.
"""

from datetime import date
from decimal import ROUND_DOWN, Decimal

from ..extensions import db
from ..external.emcd_client import get_today_income_usdt  # реализуем ниже
from ..models import (
    FundingRound,
    LedgerEntry,
    LedgerType,
    RoundIncome,
    RoundInvestment,
    RoundState,
    Transaction,
    TxStatus,
    TxType,
)
from ..services.wallet_service import credit_to_balance

OPEX_PCT = Decimal("0.07")


def fetch_pool_income() -> None:
    """
    Получает доход от пула за сегодняшний день и распределяет его.

    Вычисляет долю операционных расходов и распределяет доход между
    текущими раундами финансирования.
    """
    mined = get_today_income_usdt()  # Decimal
    opex = (mined * OPEX_PCT).quantize(Decimal("0.01"))
    dist = mined - opex
    day = date.today()  # noqa: DTZ011
    mining = FundingRound.query.filter_by(state=RoundState.MINING).all()
    tot_cap = sum(r.cap_usdt for r in mining)
    if tot_cap == 0:
        return
    for r in mining:
        share = r.cap_usdt / tot_cap
        row = RoundIncome(
            round_id=r.id,
            period_day=day,
            mined_usdt=mined * share,
            opex_usdt=opex * share,
            distributable=dist * share,
        )
        db.session.add(row)
    db.session.commit()


def distribute_round(round_id: int) -> None:
    """
    Распределяет доходы среди инвесторов в указанном раунде.

    :param round_id: Идентификатор раунда финансирования.
    :raises ValueError: Если не удается найти раунд по указанному
        идентификатору.
    """
    r = FundingRound.query.get(round_id)
    if r is None:
        raise ValueError(f"Funding round with ID {round_id} not found.")

    income: Decimal = (
        db.session.query(
            db.func.coalesce(db.func.sum(RoundIncome.distributable), 0),
        )
        .filter_by(round_id=round_id)
        .scalar()
    )

    if income == 0:
        return

    tot_inv: Decimal = db.session.query(db.func.sum(RoundInvestment.amount)).filter_by(round_id=round_id).scalar()

    for inv in RoundInvestment.query.filter_by(round_id=round_id):
        payout: Decimal = (income * (inv.amount / tot_inv)).quantize(
            Decimal("0.01"),
            ROUND_DOWN,
        )
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
        credit_to_balance(inv.user_id, "erc", payout)

    db.session.query(RoundIncome).filter_by(round_id=round_id).delete()
    db.session.commit()
