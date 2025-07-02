from datetime import datetime

from ..extensions import db


class PackageProperty(db.Model):
    """Дополнительные свойства пакетов"""

    __tablename__ = "package_properties"

    id = db.Column(db.Integer, primary_key=True)
    package_id = db.Column(
        db.Integer,
        db.ForeignKey("packages.id", ondelete="CASCADE"),
        nullable=False,
    )
    key = db.Column(db.String(100), nullable=False)
    value = db.Column(db.Text, nullable=False)

    package = db.relationship("Package", back_populates="properties")
