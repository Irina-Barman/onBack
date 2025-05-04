from datetime import datetime
from ..extensions import db


class EquipmentInvestment(db.Model):
    __tablename__ = "equipment_investments"
    __table_args__ = (
        db.UniqueConstraint("user_id", "equipment_id"),
    )

    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.BigInteger, db.ForeignKey("users.id"))
    equipment_id = db.Column(db.Integer, db.ForeignKey("mining_equipment.id"))
    net_amount   = db.Column(db.Numeric(18, 2), nullable=False)   # после реф-части
    invested_at  = db.Column(db.DateTime, default=datetime.utcnow)
