from datetime import datetime
from ..extensions import db

class RoundState(db.Enum):  # SQLAlchemy Enum helper
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    MINING = "MINING"
    DONE = "DONE"

class FundingRound(db.Model):
    __tablename__ = "funding_rounds"

    id              = db.Column(db.Integer, primary_key=True)
    cap_usdt        = db.Column(db.Numeric(18, 2), nullable=False)
    collected_usdt  = db.Column(db.Numeric(18, 2), default=0)
    state           = db.Column(RoundState, default=RoundState.OPEN)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    closed_at       = db.Column(db.DateTime)
