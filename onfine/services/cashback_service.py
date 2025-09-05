"""
Модуль сервиса кэшбэка.

Основные функции:
- Получение текущего реферального баланса пользователя.
- Начисление средств на реферальный баланс.
- Списание средств с реферального баланса с проверкой достаточности и созданием транзакции.

Используемые константы:
- TxType.referral (str): Тип транзакции для реферальных операций.
- TxStatus.confirmed (str): Статус подтверждённой транзакции.

Зависимости:
- onfine.extensions.db: SQLAlchemy сессия для работы с базой данных.
- onfine.models.referral_balance.ReferralBalance: Модель для хранения реферальных балансов.
- onfine.models.transactions.Transaction, TxStatus, TxType: Модель транзакций и константы статусов и типов.
- onfine.models.user.User: Модель пользователя.
- onfine.utils.ledger_decorator.ledger, LedgerType: Декоратор для логирования операций в системе учёта.

Функции:
- ref_balance(user: User) -> Decimal
    Возвращает текущий реферальный баланс пользователя. Если баланс отсутствует, возвращает Decimal(0).

- ref_credit(user_id: int, amount: Decimal) -> None
    Начисляет указанную сумму на реферальный баланс пользователя. Создаёт запись баланса, если её нет.

- ref_debit(user: User, amount: Decimal) -> Transaction
    Списывает указанную сумму с реферального баланса пользователя после проверки достаточности средств.
    Создаёт и возвращает запись транзакции. Применяет декоратор @ledger для логирования в системе учёта.

Исключения:
- ValueError при недостатке средств на балансе или отсутствии записи.
"""


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
