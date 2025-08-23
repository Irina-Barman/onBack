from datetime import datetime
from decimal import Decimal
from enum import Enum

from onfine.extensions import db


class GasExpenseStatus(str, Enum):
    enqueued = "enqueued"
    sent = "sent"
    confirmed = "confirmed"
    failed = "failed"


class PlatformGasExpense(db.Model):
    __tablename__ = "platform_gas_expenses"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=False, index=True)
    wallet_id = db.Column(db.Integer, db.ForeignKey("wallets.id"), nullable=False, index=True)
    network = db.Column(db.String(8), nullable=False, index=True)  # 'erc20' | 'bep20' | 'trc20'

    amount_native = db.Column(db.Numeric(38, 18), nullable=False)  # сколько отправили нативки
    amount_usdt_est = db.Column(db.Numeric(38, 18), nullable=False, default=Decimal("0"))  # справочно

    status = db.Column(db.Enum(GasExpenseStatus), nullable=False, default=GasExpenseStatus.enqueued)
    platform_tx_hash = db.Column(db.String(128))
    error = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    confirmed_at = db.Column(db.DateTime)

    wallet = db.relationship("Wallet")
