from datetime import datetime

from ..extensions import db


class PackageProperty(db.Model):
    __tablename__ = "package_properties"

    id = db.Column(db.Integer, primary_key=True)
    package_id = db.Column(
        db.Integer, db.ForeignKey("packages.id"), nullable=False, unique=True
    )

    term_months = db.Column(db.Integer, nullable=False)  # срок в месяцах
    interest_rate_from = db.Column(
        db.Numeric(5, 2), nullable=False
    )  # минимальная доходность, например 18.00
    interest_rate_to = db.Column(
        db.Numeric(5, 2), nullable=True
    )  # максимальная доходность, например 45.00
    bonuses = db.Column(
        db.Text, nullable=True
    )  # многострочное описание бонусов
    target_audience = db.Column(
        db.Text, nullable=True
    )  # для кого предназначен пакет

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    package = db.relationship(
        "Package", back_populates="package_property", uselist=False
    )
