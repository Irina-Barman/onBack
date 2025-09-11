from datetime import datetime

from sqlalchemy import Index

from ..extensions import db


class EMCDIncome(db.Model):
    """
    Модель для хранения информации о доходах EMCD.

    """

    __tablename__ = 'emcd_income'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey(
        'users.id'), nullable=False)
    coin = db.Column(db.String(10), nullable=False)
    token_id = db.Column(db.Integer, db.ForeignKey(
        'blockchain_tokens.id'), nullable=True)
    code = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.Integer, nullable=False)
    gmt_time = db.Column(db.String(20), nullable=False)
    income = db.Column(db.Float, nullable=False)
    type_ = db.Column(db.String(20), nullable=False)
    total_hashrate = db.Column(db.Integer, nullable=False)
    date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    env_var_name = db.Column(
        db.String(255), nullable=False, default='EMCD_API_KEY')

    token = db.relationship('BlockchainTokens', backref='incomes')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'date', 'coin',
                            name='uq_emcd_income_user_date_coin'),
        Index('idx_income_user_date_coin', 'user_id', 'date', 'coin'),
        Index('idx_income_token_id', 'token_id'),
    )

    def __repr__(self):
        return f"<EMCDIncome user_id={self.user_id} coin={self.coin} income={self.income}>"
