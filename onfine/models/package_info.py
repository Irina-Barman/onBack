from ..extensions import db


class PackageInfo(db.Model):
    """
    Модель дополнительных свойств пакетов.

    Атрибуты:
        id (int): Уникальный идентификатор записи.
        package_id (int): Внешний ключ на пакет.
        key (str): Ключ свойства.
        value (str): Значение свойства.
        package (Optional[Package]): Связанный объект пакета.
    """

    __tablename__ = "package_info"

    id = db.Column(db.Integer, primary_key=True)
    package_id = db.Column(
        db.Integer,
        db.ForeignKey("packages.id", ondelete="CASCADE"),
        nullable=False,
    )
    key = db.Column(db.String(100), nullable=False)
    value = db.Column(db.Text, nullable=False)

    package = db.relationship("Package", back_populates="package_info")
