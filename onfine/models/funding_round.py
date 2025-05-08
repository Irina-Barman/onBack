from datetime import datetime
from ..extensions import db


# Определяем ENUM с именем
RoundState = db.Enum(
    "OPEN", "CLOSED", "MINING", "DONE", name="roundstate_enum"
)


class FundingRound(db.Model):
    __tablename__ = "funding_rounds"

    id = db.Column(db.Integer, primary_key=True)
    cap_usdt = db.Column(db.Numeric(18, 2), nullable=False)
    collected_usdt = db.Column(db.Numeric(18, 2), default=0)
    state = db.Column(RoundState, default="OPEN")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    closed_at = db.Column(db.DateTime)
