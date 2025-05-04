from ..extensions import db


class TransferFee(db.Model):
    """
    Текущая комиссия на вывод (USDT) в сети.
    """
    __tablename__ = "transfer_fee"

    network = db.Column(db.String(8), primary_key=True)
    fee_usdt = db.Column(db.Numeric(18, 2), nullable=False)
