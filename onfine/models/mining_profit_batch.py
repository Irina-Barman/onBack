from datetime import datetime
from ..extensions import db


class MiningProfitBatch(db.Model):
    __tablename__ = "mining_profit_batches"

    id            = db.Column(db.Integer, primary_key=True)
    equipment_id  = db.Column(db.Integer, db.ForeignKey("mining_equipment.id"))
    mined_usdt    = db.Column(db.Numeric(18, 2), nullable=False)
    opex_usdt     = db.Column(db.Numeric(18, 2), nullable=False)
    distributable = db.Column(db.Numeric(18, 2), nullable=False)
    period_start  = db.Column(db.DateTime)
    period_end    = db.Column(db.DateTime)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
