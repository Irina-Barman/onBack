"""
Модуль управления инвестициями в раунды финансирования.

Основные функции:
- invest(): Инвестирует указанную сумму для пользователя в открытый раунд финансирования.
  Если открытого раунда нет, создаёт новый с дефолтным лимитом. Проверяет переполнение лимита,
  списывает средства с баланса, создаёт запись об инвестиции и обновляет статус раунда.

Константы:
- CAP_DEFAULT (Decimal): Дефолтный лимит капитала для нового раунда (80000 USDT).

Зависимости:
- datetime.datetime: Для установки времени закрытия раунда.
- decimal.Decimal: Для точных денежных расчётов.
- typing.Any: Для аннотаций типов (например, для объекта user).
- SQLAlchemy (db): Для работы с базой данных.
- Модели: FundingRound, RoundState, RoundInvestment.
- wallet_service.debit: Сервис для списания средств с баланса пользователя.
- ledger_decorator.ledger: Декоратор для автоматического создания записей в бухгалтерском журнале (тип 'purchase', направление 'out').

Функции:
- invest(user: Any, amount: Decimal) -> RoundInvestment
    Инвестирует указанную сумму для пользователя в открытый раунд финансирования.
    Если открытого раунда нет, создаёт новый раунд с дефолтным лимитом (CAP_DEFAULT).
    Проверяет, что сумма инвестиций не превышает лимит раунда; если превышает, выбрасывает ValueError.
    Списывает сумму с баланса пользователя (ERC), создаёт объект RoundInvestment,
    обновляет накопленную сумму раунда и, если достигнут лимит, закрывает раунд.
    Функция декорирована @ledger для автоматического создания записи в бухгалтерском журнале.

Исключения:
- ValueError при попытке инвестировать сумму, превышающую лимит раунда (Round overflow).
- Возможны исключения, связанные с ошибками базы данных или списания средств с баланса пользователя.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from ..extensions import db
from ..models.funding_round import FundingRound, RoundState
from ..models.round_investment import RoundInvestment
from ..services.wallet_service import debit
from ..utils.ledger_decorator import LedgerType, ledger

CAP_DEFAULT = Decimal("80000")


@ledger(LedgerType.purchase, direction="out")
def invest(user: Any, amount: Decimal) -> RoundInvestment:
    """
    Инвестирует указанную сумму для пользователя в открытый раунд
        финансирования.

    Если открытый раунд не найден, создается новый раунд с заданным лимитом.
    Если сумма инвестиций превышает лимит раунда, выбрасывается ошибка.

    :param user: Пользователь, который делает инвестицию.
    :param amount: Сумма инвестиции.
    :raises ValueError: Если сумма превышает лимит раунда.
    :return: Объект RoundInvestment, представляющий инвестицию.
    """
    # ищем открытый раунд
    r = FundingRound.query.filter_by(state=RoundState.OPEN).order_by(FundingRound.id).first()
    if not r:
        r = FundingRound(cap_usdt=CAP_DEFAULT)
        db.session.add(r)
        db.session.flush()

    if r.collected_usdt + amount > r.cap_usdt:
        raise ValueError("Round overflow")

    debit(user, "erc", amount)  # списываем gross
    inv = RoundInvestment(round_id=r.id, user_id=user.id, amount=amount)
    db.session.add(inv)

    r.collected_usdt += amount
    if r.collected_usdt == r.cap_usdt:
        r.state = RoundState.CLOSED
        r.closed_at = datetime.utcnow()  # noqa: DTZ003

    db.session.commit()
    return inv
