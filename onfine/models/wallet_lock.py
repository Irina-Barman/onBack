import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.schema import Index

from onfine.extensions import db


class WalletLockStatus(str, Enum):
    active = "active"
    released = "released"
    expired = "expired"


class WalletLockPurpose(str, Enum):
    purchase = "purchase"
    withdrawal = "withdrawal"
    other = "other"


class WalletLock(db.Model):
    __tablename__ = "wallet_locks"

    id = db.Column(db.Integer, primary_key=True)
    wallet_id = db.Column(db.Integer, db.ForeignKey("wallets.id"), nullable=False, index=True)
    purpose = db.Column(db.Enum(WalletLockPurpose), nullable=False)
    holder_token = db.Column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid.uuid4)

    status = db.Column(db.Enum(WalletLockStatus), nullable=False, default=WalletLockStatus.active)
    comment = db.Column(db.String(255))

    ttl_until = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    released_at = db.Column(db.DateTime, nullable=True)

    wallet = db.relationship("Wallet", backref="locks")


# Partial unique index: один активный лок на кошелёк
# (PostgreSQL)
Index(
    "ux_wallet_locks_wallet_active",
    WalletLock.wallet_id,
    unique=True,
    postgresql_where=(WalletLock.status == WalletLockStatus.active),
)
