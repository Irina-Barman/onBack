from datetime import datetime

from ..extensions import db


class Package(db.Model):
    """Модель инвестиционного пакета"""

    __tablename__ = "packages"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    type = db.Column(db.String(32), nullable=False)
    price_usdt = db.Column(db.Numeric(18, 2), nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    purchases = db.relationship("Purchase", back_populates="package")
    # description тут удалён, в сваг модели это поле наполняется из package_info

    package_info = db.relationship(
        "PackageInfo",
        back_populates="package",
        cascade="all, delete-orphan",
        lazy="joined",
    )
    package_property = db.relationship(
        "PackageProperty",
        back_populates="package",
        cascade="all, delete-orphan",
        uselist=False,  # один к одному
        lazy="joined",
    )

    @property
    def package_description(self) -> str | None:
        """
        Формирует строковое описание пакета на основе связанных ключ-значений из package_info.

        Возвращает:
            str | None: Конкатенированное описание в формате "ключ: значение", разделённое запятыми,
                        либо None, если информация отсутствует.
        """
        if not self.package_info:
            return None
        return ", ".join(f"{prop.key}: {prop.value}" for prop in self.package_info)
