# onfine/models/emcd_account.py
from datetime import datetime

from sqlalchemy import Index

from ..extensions import db


class EMCDAccountInfo(db.Model):
    """
    Модель для хранения общей информации о аккаунте EMCD (без привязки к пользователям, для общего пула).
    """

    __tablename__ = 'emcd_account_info'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    # Фиксированный для общего пула
    pool_id = db.Column(db.Integer, nullable=False, default=0)
    username = db.Column(db.String(50), nullable=False)
    date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    env_var_name = db.Column(
        db.String(255), nullable=False, default='EMCD_API_KEY')

    coins = db.relationship(
        'EMCDCoinInfo', backref='account_info', cascade='all, delete-orphan')

    __table_args__ = (
        db.UniqueConstraint('pool_id', 'date',
                            name='uq_emcd_account_pool_date'),
        Index('idx_account_pool_date', 'pool_id', 'date'),
    )

    def __repr__(self):
        return f"<EMCDAccountInfo pool_id={self.pool_id} username={self.username} date={self.date}>"


class EMCDCoinInfo(db.Model):
    """
    Модель для хранения детальной информации о криптовалюте в аккаунте EMCD.

    """

    __tablename__ = 'emcd_coin_info'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    account_info_id = db.Column(db.Integer, db.ForeignKey(
        'emcd_account_info.id'), nullable=False)
    coin_id = db.Column(db.String(10), nullable=False)
    token_id = db.Column(db.Integer, db.ForeignKey(
        'blockchain_tokens.id'), nullable=True)
    # Добавлено для уникальности по дате
    date = db.Column(db.Date, nullable=False)
    address = db.Column(db.String(100), nullable=False)
    balance = db.Column(db.Float, nullable=False)
    total_paid = db.Column(db.Float, nullable=False)
    total_reward = db.Column(db.Float, nullable=False)
    min_payout = db.Column(db.Float, nullable=False)
    env_var_name = db.Column(
        db.String(255), nullable=False, default='EMCD_API_KEY')

    token = db.relationship('BlockchainTokens', backref='coin_infos')

    __table_args__ = (
        db.UniqueConstraint('account_info_id', 'coin_id', 'date',
                            name='uq_emcd_coin_account_coin_date'),
        Index('idx_coin_account_coin_date',
              'account_info_id', 'coin_id', 'date'),
        Index('idx_coin_token_id', 'token_id'),
    )

    def __repr__(self):
        return f"<EMCDCoinInfo coin_id={self.coin_id} balance={self.balance} date={self.date}>"
