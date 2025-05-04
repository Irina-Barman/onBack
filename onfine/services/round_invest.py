from decimal import Decimal
from datetime import datetime
from ..extensions import db
from ..models.funding_round import FundingRound, RoundState
from ..models.round_investment import RoundInvestment
from ..services.wallet_service import debit
from ..utils.ledger_decorator import ledger, LedgerType

CAP_DEFAULT = Decimal("80000")

@ledger(LedgerType.purchase, direction="out")
def invest(user, amount: Decimal):
    # ищем открытый раунд
    r = (FundingRound.query
         .filter_by(state=RoundState.OPEN)
         .order_by(FundingRound.id).first())
    if not r:
        r = FundingRound(cap_usdt=CAP_DEFAULT)
        db.session.add(r); db.session.flush()

    if r.collected_usdt + amount > r.cap_usdt:
        raise ValueError("Round overflow")

    debit(user, "erc", amount)               # списываем gross
    inv = RoundInvestment(round_id=r.id, user_id=user.id, amount=amount)
    db.session.add(inv)

    r.collected_usdt += amount
    if r.collected_usdt == r.cap_usdt:
        r.state = RoundState.CLOSED
        r.closed_at = datetime.utcnow()

    db.session.commit()
    return inv
