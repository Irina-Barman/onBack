from datetime import datetime

from sqlalchemy import Index

from ..extensions import db


class EMCDPayout(db.Model):
    """
    Модель для хранения информации о выплатах EMCD.
    """

    __tablename__ = "emcd_payout"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=False)
    coin = db.Column(db.String(10), nullable=False)
    token_id = db.Column(db.Integer, db.ForeignKey("blockchain_tokens.id"), nullable=True)
    code = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.Integer, nullable=False)
    gmt_time = db.Column(db.String(20), nullable=False)
    payout = db.Column(db.Float, nullable=False)
    type_ = db.Column(db.String(20), nullable=False)
    tx_id = db.Column(db.String(100), nullable=True)
    date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    env_var_name = db.Column(db.String(255), nullable=False, default="EMCD_API_KEY")

    token = db.relationship("BlockchainTokens", backref="payouts")

    __table_args__ = (
        db.UniqueConstraint("user_id", "date", "coin", name="uq_emcd_payout_user_date_coin"),
        Index("idx_payout_user_date_coin", "user_id", "date", "coin"),
        Index("idx_payout_token_id", "token_id"),
    )

    def __repr__(self) -> str:
        return f"<EMCDPayout user_id={self.user_id} coin={self.coin} payout={self.payout}>"
