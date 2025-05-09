import uuid
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from ..extensions import db


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.BigInteger, primary_key=True)
    uid = db.Column(db.String(36), unique=True, nullable=False,
                    default=lambda: str(uuid.uuid4()))
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    email_confirmed = db.Column(db.Boolean, default=False)

    password_hash = db.Column(db.String(255), nullable=False)
    nickname = db.Column(db.String(80), nullable=False)

    partner_uid = db.Column(
        db.String(36), db.ForeignKey("users.uid"), index=True)
    children = db.relationship("User",
                               backref=db.backref("partner", remote_side=[uid]))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Обратная связь
    purchases = db.relationship("Purchase", back_populates="user")

    # helpers -------------------------------------------------
    def set_password(
        self, raw: str):   self.password_hash = generate_password_hash(raw)

    def check_password(self, raw: str): return check_password_hash(
        self.password_hash, raw)
