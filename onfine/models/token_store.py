import uuid
from datetime import datetime, timedelta
from typing import Type

from ..extensions import db


class Token(db.Model):
    __tablename__ = "tokens"

    id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("users.id"),
        nullable=False,
    )

    token = db.Column(
        db.String(64),
        unique=True,
        nullable=False,
        default=lambda: uuid.uuid4().hex,
    )
    purpose = db.Column(db.String(32), nullable=False)  # 'confirm_email' | 'reset_pwd'
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # фабрика токенов
    @staticmethod
    def create(user_id: int, purpose: str, ttl_minutes: int) -> Type["Token"]:
        """
        Создает новый токен для указанного пользователя с заданной целью
        и временем жизни.

        :param user_id: ID пользователя, которому принадлежит токен.
        :param purpose: Цель токена ('confirm_email' или 'reset_pwd').
        :param ttl_minutes: Время жизни токена в минутах.
        :return: Созданный объект Token.
        """
        t = Token(
            user_id=user_id,
            purpose=purpose,
            expires_at=datetime.utcnow() + timedelta(minutes=ttl_minutes),  # noqa: DTZ003
        )
        db.session.add(t)
        return t
