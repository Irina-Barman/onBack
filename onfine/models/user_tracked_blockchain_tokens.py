from datetime import datetime

from ..extensions import db


class UserTrackedBlockchainToken(db.Model):
    """Для хранения отслеживаемых токенов блокчейна пользователем"""

    __tablename__ = "user_tracked_blockchain_tokens"
    __table_args__ = (db.UniqueConstraint("user_id", "blockchain_token_id", name="uq_user_blockchain_token"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=False)
    blockchain_token_id = db.Column(db.Integer, db.ForeignKey("blockchain_tokens.id"), nullable=False)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref=db.backref("tracked_blockchain_tokens", lazy="dynamic"))
    blockchain_token = db.relationship("BlockchainTokens")

    def __repr__(self):  # noqa ANN204
        return (
            f"<UserTrackedBlockchainToken user_id={self.user_id} "
            f"blockchain_token_symbol={self.blockchain_token.symbol}>"
        )
