from datetime import datetime

from ..extensions import db


class Package(db.Model):
    __tablename__ = "packages"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    type = db.Column(db.String(32), nullable=False)
    price_usdt = db.Column(db.Numeric(18, 2), nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    purchases = db.relationship("Purchase", back_populates="package")

    package_info = db.relationship(
        "PackageInfo",
        back_populates="package",
        cascade="all, delete-orphan",
        lazy="joined",
    )

    @property
    def properties_description(self) -> str | None:
        if not self.package_info:
            return None
        return ", ".join(
            f"{prop.key}: {prop.value}" for prop in self.package_info
        )
