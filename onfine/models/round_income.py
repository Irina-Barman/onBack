from datetime import datetime

from ..extensions import db


class RoundIncome(db.Model):
    __tablename__ = "round_income"

    id = db.Column(db.Integer, primary_key=True)
    round_id = db.Column(db.Integer, db.ForeignKey("funding_rounds.id"))
    period_day = db.Column(db.Date, nullable=False)
    mined_usdt = db.Column(db.Numeric(18, 2), nullable=False)
    opex_usdt = db.Column(db.Numeric(18, 2), nullable=False)
    distributable = db.Column(db.Numeric(18, 2), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
