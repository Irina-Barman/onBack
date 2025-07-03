from datetime import datetime

from ..extensions import db


class PackageInfo(db.Model):
    """Дополнительные свойства пакетов"""

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
