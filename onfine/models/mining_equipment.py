from datetime import datetime
from ..extensions import db


class MiningEquipment(db.Model):
    __tablename__ = "mining_equipment"

    id        = db.Column(db.Integer, primary_key=True)
    name      = db.Column(db.String(64), nullable=False)
    cost_usdt = db.Column(db.Numeric(18, 2), nullable=False)
    opex_pct  = db.Column(db.Numeric(5, 2), nullable=False, default=5)  # 5 %
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
