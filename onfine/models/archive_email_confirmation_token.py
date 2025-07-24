from datetime import datetime

from ..extensions import db


class ArchiveEmailConfirmationToken(db.Model):
    """
    Модель для архивации токенов подтверждения электронной почты.

    Атрибуты:
        id (int): Уникальный идентификатор записи.
        user_id (int): Идентификатор пользователя, которому принадлежит токен.
        token (str): Строковое значение токена подтверждения.
        purpose (str): Назначение токена (например, "confirm_email", "reset_pwd").
        expires_at (datetime): Время истечения срока действия токена.
        used (bool): Флаг, указывающий, был ли токен использован.
        created_at (datetime): Время создания токена.
        archived_at (datetime): Время архивации токена.
    """
    __tablename__ = "archive_email_confirmation_token"

    id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(db.BigInteger, nullable=False)
    token = db.Column(db.String(64), nullable=False)
    purpose = db.Column(db.String(32), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    archived_at = db.Column(db.DateTime, default=datetime.utcnow)
