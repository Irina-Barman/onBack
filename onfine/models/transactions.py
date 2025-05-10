from datetime import datetime
from enum import Enum

from ..extensions import db


class TxType(str, Enum):
    deposit = "deposit"
    deposit = "deposit"
    withdraw = "withdraw"
    purchase = "purchase"
    profit = "profit"
    profit = "profit"
    referral = "referral"


class TxStatus(str, Enum):
    pending = "pending"
    confirmed = "confirmed"
    canceled = "canceled"
    pending = "pending"
    confirmed = "confirmed"
    canceled = "canceled"


class Transaction(db.Model):
    __tablename__ = "transactions"

    id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey(
        "users.id"), nullable=False)

    type = db.Column(db.Enum(TxType),   nullable=False)
    status = db.Column(db.Enum(TxStatus), nullable=False,
                       default=TxStatus.pending)
    network = db.Column(db.String(8))
    amount = db.Column(db.Numeric(18, 2), nullable=False)   # чистая сумма
    # комиссия сети (withdraw)
    fee = db.Column(db.Numeric(18, 2))
    address = db.Column(db.String(128))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    confirmed_at = db.Column(db.DateTime)
