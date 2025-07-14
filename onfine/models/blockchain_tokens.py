from datetime import datetime

from ..extensions import db


class BlockchainTokens(db.Model):
    __tablename__ = "blockchain_tokens"
    __table_args__ = (db.UniqueConstraint("network", "symbol"),)

    id = db.Column(db.Integer, primary_key=True)
    network = db.Column(db.String(16), nullable=False)  # ERC20, BEP20, TRC20
    symbol = db.Column(db.String(16), nullable=False)
    contract_address = db.Column(db.String(100), nullable=False)
    decimals = db.Column(db.Integer, nullable=False, default=18)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):  # noqa ANN204
        return f"<Token {self.network}:{self.symbol}>"
