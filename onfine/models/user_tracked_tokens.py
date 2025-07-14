from datetime import datetime
from ..extensions import db


class UserTrackedTokens(db.Model):
    """Для хранения отслеживаемых токенов пользователем"""

    __tablename__ = "user_tracked_tokens"
    __table_args__ = (
        db.UniqueConstraint("user_id", "token_id", name="uq_user_token"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.BigInteger, db.ForeignKey("users.id"), nullable=False
    )
    token_id = db.Column(
        db.Integer, db.ForeignKey("blockchain_tokens.id"), nullable=False
    )
    added_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship(
        "User", backref=db.backref("tracked_tokens", lazy="dynamic")
    )
    token = db.relationship("BlockchainTokens")

    def __repr__(self):
        return (
            f"<UserTrackedToken user={self.user_id} token={self.token.symbol}>"
        )
