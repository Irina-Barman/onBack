from datetime import datetime
from enum import Enum
from ..extensions import db


class LedgerType(str, Enum):
    deposit = "deposit"
    withdraw = "withdraw"
    purchase = "purchase"
    referral = "referral"
    profit = "profit"
    reversal = "reversal"


class LedgerEntry(db.Model):
    __tablename__ = "ledger_entries"

    id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(
        db.BigInteger, db.ForeignKey("users.id"), nullable=True
    )

    origin_table = db.Column(db.String(32), nullable=False)
    origin_id = db.Column(db.BigInteger, nullable=False)

    type = db.Column(db.Enum(LedgerType), nullable=False)
    direction = db.Column(db.String(3), nullable=False)  # in / out
    network = db.Column(db.String(8))
    amount = db.Column(db.Numeric(18, 2), nullable=False)

    meta = db.Column(db.JSON, default=dict)
    created_at = db.Column(
        db.DateTime, default=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        db.Index("ix_ledger_origin", "origin_table", "origin_id"),
    )
