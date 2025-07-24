"""
Сервис аутентификации и управления пользователями.

Основные функции:
- Регистрация пользователя с отправкой email-подтверждения.
- Подтверждение email по токену.
- Вход пользователя с выдачей JWT токена.
- Запрос на сброс пароля с отправкой ссылки на email.
- Сброс пароля по токену.

Используемые переменные окружения:
- BASE_URL (str): базовый URL для формирования ссылок подтверждения и сброса пароля.
  По умолчанию "https://example.com".
- JWT_ACCESS_TOKEN_EXPIRES (int): время жизни JWT токена в секундах.

Методы:
- register_user(email: str, password: str, partner_uid: Optional[str]) -> User
- confirm_email(token_str: str) -> None
- login_user(email: str, password: str) -> Dict[str, Any]
- forgot_password(email: str) -> None
- reset_password(token: str, new_password: str) -> Dict[str, str]

Исключения:
- ValueError при ошибках валидации, отсутствии пользователя или недействительных токенах.
"""

import os
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from flask_jwt_extended import create_access_token

from ..extensions import db
from ..models.email_confirmation_token import EmailConfirmationToken
from ..models.user import User
from ..utils.mailer import send_email

load_dotenv()


class AuthService:
    BASE_URL = os.getenv("BASE_URL", "https://example.com")

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
        if not email or not password:
            raise ValueError("Email and password are required.")

        if User.query.filter_by(email=email).first():
            raise ValueError("Email is already registered.")

        user = User(email=email, partner_uid=partner_uid)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()  # получаем user.id до коммита

        # e-mail confirmation token (24 h)
        token = EmailConfirmationToken.create(
            user.id,
            purpose="confirm_email",
            ttl_minutes=60 * 24,
        )
        db.session.commit()

        confirm_link = (
            f"{AuthService.BASE_URL}/confirm-email?token={token.token}"
        )
        send_email(
            email,
            "Confirm your email",
            f"Click the link to confirm your email: {confirm_link}",
        )

        return user

    # ----------- /resend-confirmation ----------
    @staticmethod
    def resend_confirmation_email(email: str) -> None:
        """
        Повторная отправка письма с подтверждением email.

        :param email: Email пользователя.
        :raises ValueError: Если email не найден или уже подтверждён.
        """
        user = User.query.filter_by(email=email).first()
        if not user:
            raise ValueError("Email not found.")
        if user.email_confirmed:
            raise ValueError("Email already confirmed.")

        # Ищем активный токен подтверждения
        now = datetime.utcnow()
        token = (
            EmailConfirmationToken.query.filter_by(
                user_id=user.id,
                purpose="confirm_email",
                used=False,
            )
            .filter(EmailConfirmationToken.expires_at > now)
            .first()
        )

        if not token:
            token = EmailConfirmationToken.create(
                user.id,
                purpose="confirm_email",
                ttl_minutes=60 * 24,  # сутки
            )
            db.session.commit()

        confirm_link = (
            f"{AuthService.BASE_URL}/confirm-email?token={token.token}"
        )
        send_email(
            email,
            "Confirm your email",
            f"Click the link to confirm your email: {confirm_link}",
        )

    # ----------------- CONFIRM EMAIL -----------------
    @staticmethod
    def confirm_email(token_str: str) -> None:
        """
        Подтверждение адреса электронной почты пользователя.

        :param token_str: Токен подтверждения.
        :raises ValueError: Если токен недействителен или истек.
        """
        token = EmailConfirmationToken.query.filter_by(
            token=token_str,
            purpose="confirm_email",
            used=False,
        ).first()

        if token is None or token.expires_at < datetime.utcnow():
            raise ValueError("Invalid or expired token.")

        user = User.query.get(token.user_id)
        if not user:
            raise ValueError("User not found.")

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
        if not email or not password:
            raise ValueError("Email and password are required.")

        user: User = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            raise ValueError("Invalid credentials.")

        if not user.email_confirmed:
            raise ValueError("Email not confirmed.")

        expires_in_seconds = os.getenv("JWT_ACCESS_TOKEN_EXPIRES")
        if expires_in_seconds is None:
            raise ValueError(
                "JWT_ACCESS_TOKEN_EXPIRES is not set in environment variables."
            )
        expires_in_seconds = int(expires_in_seconds)

        access_token = create_access_token(
            identity=str(user.id),
            expires_delta=timedelta(seconds=expires_in_seconds),
        )

        expire_timestamp = int(
            (
                datetime.utcnow() + timedelta(seconds=expires_in_seconds)
            ).timestamp()
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
        if not email:
            raise ValueError("Email is required.")

        user: User = User.query.filter_by(email=email).first()
        if not user:
            raise ValueError("Email not found.")

        token = EmailConfirmationToken.create(
            user.id,
            purpose="reset_pwd",
            ttl_minutes=60 * 24,  # сутки
        )
        db.session.commit()

        reset_link = f"{AuthService.BASE_URL}/reset?token={token.token}"
        send_email(
            email,
            "Password reset",
            f"Click the link to reset your password: {reset_link}",
        )

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
        if not token or not new_password:
            raise ValueError("Token and new password are required.")

        t = EmailConfirmationToken.query.filter_by(
            token=token,
            purpose="reset_pwd",
            used=False,
        ).first()

        if t is None or t.expires_at < datetime.utcnow():
            raise ValueError("Invalid or expired token.")

        user = User.query.get(t.user_id)
        if not user:
            raise ValueError("User not found.")

        user.set_password(new_password)
        t.used = True
        db.session.commit()
        return {"message": "Password changed successfully."}
