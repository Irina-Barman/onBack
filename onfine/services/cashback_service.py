from __future__ import annotations

import logging
from decimal import Decimal

from onfine.extensions import db
from onfine.models.referral_balance import ReferralBalance
from onfine.models.transactions import Transaction, TxStatus, TxType
from onfine.models.user import User
from onfine.utils.ledger_decorator import LedgerType, ledger

logger = logging.getLogger(__name__)


def ref_balance(user: User) -> Decimal:
    """
    Возвращает текущий баланс реферальных средств пользователя.

    Args:
        user (User): Экземпляр пользователя.

    Returns:
        Decimal: Баланс реферальных средств, 0 если записи нет.
    """
    rb = ReferralBalance.query.get(user.id)
    return Decimal(rb.balance) if rb else Decimal(0)


def ref_credit(user_id: int, amount: Decimal) -> None:
    """
    Начисляет реферальные средства пользователю.

    Args:
        user_id (int): ID пользователя.
        amount (Decimal): Сумма для начисления.
    """
    rb = ReferralBalance.query.get(user_id)
    if not rb:
        rb = ReferralBalance(user_id=user_id, balance=amount)
        db.session.add(rb)
    else:
        rb.balance += amount
    db.session.flush()


@ledger(LedgerType.referral, direction="out")
def ref_debit(user: User, amount: Decimal) -> Transaction:
    """
    Списывает реферальные средства пользователя.

    Args:
        user (User): Экземпляр пользователя.
        amount (Decimal): Сумма списания.

    Raises:
        ValueError: Если недостаточно средств на реферальном балансе.

    Returns:
        Transaction: Созданная транзакция списания.
    """
    rb = ReferralBalance.query.get(user.id)
    if not rb or rb.balance < amount:
        raise ValueError("Not enough referral balance")

    rb.balance -= amount
    tx = Transaction(
        user_id=user.id,
        type=TxType.referral,
        status=TxStatus.confirmed,
        network="ref",
        amount=-amount,
    )
    db.session.add(tx)
    db.session.flush()
    return tx
