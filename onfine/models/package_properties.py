from datetime import datetime
from enum import Enum

from ..extensions import db


class PackageCategory(Enum):
    BEGINNERS = "beginners"
    STABLE_INCOME = "stable_income"
    MAXIMUM_EARNING = "maximum_earning"
    EXPERIENCED_INVESTORS = "experienced_investors"


class PackageProperty(db.Model):
    """
    Модель свойств пакета с дополнительной информацией.

    Атрибуты:
        id (int): Уникальный идентификатор записи.
        package_id (int): Внешний ключ на пакет (уникальный).
        term_months (int): Срок действия пакета в месяцах.
        interest_rate_from (Decimal): Минимальная доходность (например, 18.00).
        interest_rate_to (Optional[Decimal]): Максимальная доходность (например, 45.00).
        bonuses (Optional[str]): Описание бонусов (многострочное).
        target_audience (Optional[PackageCategory]): Категория/целевая аудитория пакета (ограничено Enum).
        created_at (datetime): Дата и время создания записи.
        package (Optional[Package]): Связанный объект пакета.
    """

    __tablename__ = "package_properties"

    id = db.Column(db.Integer, primary_key=True)
    package_id = db.Column(db.Integer, db.ForeignKey("packages.id"), nullable=False, unique=True)

    term_months = db.Column(db.Integer, nullable=False)
    interest_rate_from = db.Column(db.Numeric(5, 2), nullable=False)
    interest_rate_to = db.Column(db.Numeric(5, 2), nullable=True)
    bonuses = db.Column(db.Text, nullable=True)
    target_audience = db.Column(db.Enum(PackageCategory), nullable=True)  # Изменено на Enum

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    package = db.relationship("Package", back_populates="package_property", uselist=False)
