from datetime import datetime
from enum import Enum

from ..extensions import db


class PurchaseStatus(str, Enum):
    pending = "pending"
    completed = "completed"
    canceled = "canceled"


class Purchase(db.Model):
    """
    Покупка пакета пользователем.
    """

    __tablename__ = "purchases"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.BigInteger, db.ForeignKey("users.id"), nullable=False
    )
    package_id = db.Column(
        db.Integer, db.ForeignKey("packages.id"), nullable=False
    )

    amount_usdt = db.Column(
        db.Numeric(18, 2), nullable=False
    )  # цена пакета (фиксируется)
    gas_usdt = db.Column(db.Numeric(18, 2), nullable=False)  # комиссия сети
    network = db.Column(db.String(8), nullable=False)  # 'bep' | 'erc' | 'trc'

    status = db.Column(db.Enum(PurchaseStatus), default=PurchaseStatus.pending)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    confirmed_at = db.Column(db.DateTime)

    is_from_database = db.Column(db.Boolean, default=False)

    # связи
    package = db.relationship("Package", back_populates="purchases")
    user = db.relationship("User", back_populates="purchases")

    # Связь с Transaction
    transaction = db.relationship(
        "Transaction", back_populates="purchase", uselist=False
    )
