from datetime import datetime

from ..extensions import db


class Package(db.Model):
    """
    Каталог инвестиционных пакетов.
    """

    __tablename__ = "packages"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    type = db.Column(db.String(32), nullable=False)  # e.g. 'futures'
    price_usdt = db.Column(db.Numeric(18, 2), nullable=False)
    description = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    purchases = db.relationship("Purchase", back_populates="package")
    properties = db.relationship(
        "PackageProperty",
        back_populates="package",
        cascade="all, delete-orphan",
        lazy="joined",
    )
