from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from flask_jwt_extended import create_access_token

from ..extensions import db
from ..models.token_store import Token
from ..models.user import User
from ..utils.mailer import send_email


class AuthService:
    # ----------------- REGISTRATION -----------------
    @staticmethod
    def register_user(
        email: str,
        password: str,
        partner_uid: Optional[str] = None,
    ) -> User:
        """Регистрация нового пользователя.

        :param email: Адрес электронной почты пользователя.
        :param password: Пароль пользователя.
        :param partner_uid: Идентификатор партнера (необязательно).
        :raises ValueError: Если адрес электронной почты уже зарегистрирован.
        :return: Зарегистрированный пользователь.
        """
        if User.query.filter_by(email=email).first():
            raise ValueError("Email is already registered.")

        user = User(email=email, partner_uid=partner_uid)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()  # получаем user.id до коммита

        # e-mail confirmation token (24 h)
        token = Token.create(
            user.id,
            purpose="confirm_email",
            ttl_minutes=60 * 24,
        )
        db.session.commit()

        confirm_link = f"https://example.com/confirm-email?token={token.token}"
        send_email(email, "Confirm your email", f"Click: {confirm_link}")

        return user

    # ----------------- CONFIRM EMAIL -----------------
    @staticmethod
    @staticmethod
    def confirm_email(token_str: str) -> None:
        """
        Подтверждение адреса электронной почты пользователя.

        :param token_str: Токен подтверждения.
        :raises ValueError: Если токен недействителен или истек.
        """
        token = Token.query.filter_by(
            token=token_str,
            purpose="confirm_email",
            used=False,
        ).first()

        # Проверяем, существует ли токен и не истек ли он
        if token is None or token.expires_at < datetime.utcnow():  # noqa: DTZ003
            raise ValueError("Invalid or expired token.")

        user = User.query.get(token.user_id)
        user.email_confirmed = True
        token.used = True
        db.session.commit()

    # ----------------- LOGIN -----------------
    @staticmethod
    def login_user(email: str, password: str) -> Dict[str, Any]:
        """
        Вход пользователя в систему.

        :param email: Адрес электронной почты пользователя.
        :param password: Пароль пользователя.
        :raises ValueError: Если учетные данные недействительны или
        адрес электронной почты не подтвержден.
        :return: Словарь с токеном доступа и информацией о его сроке действия.
        """
        user: User = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            raise ValueError("Invalid credentials.")
        if not user.email_confirmed:
            raise ValueError("Email not confirmed.")

        access_token = create_access_token(
            identity=str(user.id),
            expires_delta=timedelta(days=7),  # «длинный» токен на неделю
        )
        # Вычисляем срок действия токена

        expire_timestamp = int(
            (datetime.utcnow() + timedelta(days=7)).timestamp(),  # noqa: DTZ003
        )

        return {
            "accessToken": access_token,
            "tokenType": "Bearer",
            "expireTimestamp": expire_timestamp,
        }

    # ----------------- FORGOT PASSWORD -----------------
    @staticmethod
    def forgot_password(email: str) -> None:
        """
        Запрос на сброс пароля.

        :param email: Адрес электронной почты пользователя.
        :raises ValueError: Если адрес электронной почты не найден.
        """
        user: User = User.query.filter_by(email=email).first()
        if not user:
            raise ValueError("Email not found.")

        token = Token.create(
            user.id,
            purpose="reset_pwd",
            ttl_minutes=30,
        )  # 30 мин
        db.session.commit()

        reset_link = f"https://example.com/reset?token={token.token}"
        send_email(email, "Password reset", f"Click: {reset_link}")

    # ----------------- RESET PASSWORD -----------------
    @staticmethod
    def reset_password(token: str, new_password: str) -> Dict[str, str]:
        """
        Сброс пароля пользователя.

        :param token: Токен сброса пароля.
        :param new_password: Новый пароль пользователя.
        :raises ValueError: Если токен недействителен или истек.
        :return: Словарь с сообщением об успешном изменении пароля.
        """
        t = Token.query.filter_by(
            token=token, purpose="reset_pwd", used=False
        ).first()
        if not t or t.expires_at < db.func.now():
            raise ValueError("Invalid or expired token.")

        user = User.query.get(t.user_id)
        user.set_password(new_password)
        t.used = True
        db.session.commit()
        return {"message": "Password changed successfully."}
