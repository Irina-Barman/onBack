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
