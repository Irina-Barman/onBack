from ..extensions import db
from datetime import datetime


class ReferralBalance(db.Model):
    __tablename__ = "referral_balances"

    user_id = db.Column(db.BigInteger, db.ForeignKey("users.id"), primary_key=True)
    balance = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
