from datetime import timedelta
from typing import Optional

from flask_jwt_extended import create_access_token
from sqlalchemy.exc import IntegrityError
from ..extensions import db
from ..models.user import User
from ..models.token_store import Token
from ..utils.mailer import send_email


class AuthService:
    # ----------------- REGISTRATION -----------------
    @staticmethod
    def register_user(email: str, password: str, nickname: str,
                      partner_uid: Optional[str] = None) -> User:
        if User.query.filter_by(email=email).first():
            raise ValueError("Email is already registered.")

        user = User(email=email, nickname=nickname, partner_uid=partner_uid)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()           # получаем user.id до коммита

        # e-mail confirmation token (24 h)
        token = Token.create(user.id, purpose="confirm_email", ttl_minutes=60 * 24)
        db.session.commit()

        confirm_link = f"https://example.com/confirm-email?token={token.token}"
        send_email(email, "Confirm your email", f"Click: {confirm_link}")

        return user

    # ----------------- CONFIRM EMAIL -----------------
    @staticmethod
    def confirm_email(token_str: str):
        token = Token.query.filter_by(token=token_str, purpose="confirm_email", used=False).first()
        if not token or token.expires_at < db.func.now():
            raise ValueError("Invalid or expired token.")

        user = User.query.get(token.user_id)
        user.email_confirmed = True
        token.used = True
        db.session.commit()

    # ----------------- LOGIN -----------------
    @staticmethod
    def login_user(email: str, password: str) -> dict:
        user: User = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            raise ValueError("Invalid credentials.")
        if not user.email_confirmed:
            raise ValueError("Email not confirmed.")

        access_token = create_access_token(
            identity=user.id,
            expires_delta=timedelta(days=7)   # «длинный» токен на неделю
        )
        return {
            "accessToken": access_token,
            "tokenType": "Bearer",
            "expireTimestamp": (db.func.extract("epoch", db.func.now()) + 60 * 60 * 24 * 7)
        }

    # ----------------- FORGOT PASSWORD -----------------
    @staticmethod
    def forgot_password(email: str):
        user: User = User.query.filter_by(email=email).first()
        if not user:
            raise ValueError("Email not found.")

        token = Token.create(user.id, purpose="reset_pwd", ttl_minutes=30)  # 30 мин
        db.session.commit()

        reset_link = f"https://example.com/reset?token={token.token}"
        send_email(email, "Password reset", f"Click: {reset_link}")

    # ----------------- RESET PASSWORD -----------------
    @staticmethod
    def reset_password(token: str, new_password: str) -> dict:
        t = Token.query.filter_by(token=token, purpose="reset_pwd", used=False).first()
        if not t or t.expires_at < db.func.now():
            raise ValueError("Invalid or expired token.")

        user = User.query.get(t.user_id)
        user.set_password(new_password)
        t.used = True
        db.session.commit()
        return {"message": "Password changed successfully."}

