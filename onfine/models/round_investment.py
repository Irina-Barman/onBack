from datetime import datetime
from ..extensions import db

class RoundInvestment(db.Model):
    __tablename__ = "round_investments"
    __table_args__ = (db.UniqueConstraint("round_id", "user_id"),)

    id          = db.Column(db.Integer, primary_key=True)
    round_id    = db.Column(db.Integer, db.ForeignKey("funding_rounds.id"))
    user_id     = db.Column(db.BigInteger, db.ForeignKey("users.id"))
    amount      = db.Column(db.Numeric(18, 2), nullable=False)
    invested_at = db.Column(db.DateTime, default=datetime.utcnow)
