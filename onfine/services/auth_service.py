"""
Сервис аутентификации и управления пользователями.

Основные функции:
- Регистрация пользователя с отправкой email-подтверждения.
- Повторная отправка письма с подтверждением email.
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
    Регистрирует нового пользователя, создаёт токен подтверждения email и отправляет письмо.

- resend_confirmation_email(email: str) -> None
    Повторно отправляет письмо с подтверждением email, если пользователь существует и email не подтверждён.

- confirm_email(token_str: str) -> None
    Подтверждает email пользователя по токену, помечая токен как использованный.

- login_user(email: str, password: str) -> Dict[str, Any]
    Аутентифицирует пользователя и возвращает JWT access token с временем жизни.

- forgot_password(email: str) -> None
    Инициирует процесс сброса пароля, создаёт токен сброса и отправляет письмо.

- reset_password(token_str: str, new_password: str) -> Dict[str, str]
    Сбрасывает пароль пользователя по валидному токену и помечает токен как использованный.

Исключения:
- ValueError при ошибках валидации, отсутствии пользователя или недействительных токенах.
"""

import os
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from flask_jwt_extended import create_access_token

from onfine.services.email_service import EmailService

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
        """
        Регистрация нового пользователя с отправкой email-подтверждения.

        :param email: Адрес электронной почты пользователя.
        :param password: Пароль пользователя.
        :param partner_uid: Идентификатор партнера (опционально).
        :raises ValueError: Если email или пароль не указаны, либо email уже зарегистрирован.
        :return: Объект созданного пользователя.
        """
        if not email or not password:
            raise ValueError("Email and password are required.")

        # Проверяем, что email ещё не зарегистрирован
        if User.query.filter_by(email=email).first():
            raise ValueError("Email is already registered.")

        # Создаём пользователя и задаём пароль
        user = User(email=email, partner_uid=partner_uid)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()  # Получаем user.id до коммита

        # Создаём токен для подтверждения email (срок 24 часа)
        token = EmailConfirmationToken.create(
            user.id,
            purpose="confirm_email",
            ttl_minutes=60*24,
        )
        db.session.commit()


        confirm_link = f"https://example.com/confirm-email?token={token.token}"

        email_service = EmailService(db.session)

        context = {
            "user_uid": user.uid,
            "subject": "Подтверждение регистрации",
            "confirm_link": confirm_link,
            "user_email": user.email,
        }

        email_service.send_and_log(
            to=user.email,
            template_type="registration_confirmation.html",
            context=context,
        )

        return user

    # ----------- /resend-confirmation ----------
    @staticmethod
    def resend_confirmation_email(email: str) -> None:
        """
        Повторная отправка письма с подтверждением email.

        :param email: Email пользователя.
        :raises ValueError: Если пользователь не найден или email уже подтверждён.
        """
        user = User.query.filter_by(email=email).first()
        if not user:
            raise ValueError("Email not found.")
        if user.email_confirmed:
            raise ValueError("Email already confirmed.")

        token = EmailConfirmationToken.get_active_token(
            user.id, "confirm_email"
        )

        if not token:
            token = EmailConfirmationToken.create(
                user.id,
                purpose="confirm_email",
                ttl_minutes=60 * 24,
            )
            db.session.commit()

        # Отправляем письмо с подтверждением
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
        Подтверждение email пользователя по токену.

        :param token_str: Токен подтверждения email.
        :raises ValueError: Если токен недействителен, просрочен или пользователь не найден.
        """
        # Ищем токен по строке, назначению
        token = EmailConfirmationToken.query.filter_by(
            token=token_str,
            purpose="confirm_email",
        ).first()

        if token is None:
            raise ValueError("Invalid token.")

        # Проверяем, что токен активен (не использован и не просрочен)
        if not token.is_active():
            raise ValueError(
                "Token expired or already used, request a new one"
            )

        user = User.query.get(token.user_id)
        if not user:
            raise ValueError("User not found.")

        # Подтверждаем email пользователя и помечаем токен как использованный
        user.email_confirmed = True
        token.used = True
        db.session.flush()  # Фиксируем изменения в сессии перед массовым обновлением

        # Массово деактивируем все просроченные и использованные токены для данного пользователя
        EmailConfirmationToken.deactivate_expired_and_used_tokens(
            token.user_id, token.purpose
        )
        db.session.commit()

        email_service = EmailService(db.session)

        context = {
            "user_uid": user.uid,
            "subject": "Добро пожаловать!",
            "user_email": user.email,
            # можно добавить user_name и другие данные
        }
        email_service.send_and_log(
            to=user.email,
            template_type="welcome_after_confirmation.html",
            context=context,
        )

    # ----------------- LOGIN -----------------
    @staticmethod
    def login_user(email: str, password: str) -> Dict[str, Any]:
        """
        Аутентификация пользователя и выдача JWT токена.

        :param email: Email пользователя.
        :param password: Пароль пользователя.
        :raises ValueError: Если данные некорректны или email не подтверждён.
        :return: Словарь с accessToken, типом токена и временем истечения.
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
        )  # noqa: DTZ003

        if not email or not password:
            raise ValueError("Email and password are required.")

        return {
            "accessToken": access_token,
            "tokenType": "Bearer",
            "expireTimestamp": expire_timestamp,
        }

    # ----------------- FORGOT PASSWORD -----------------
    @staticmethod
    def forgot_password(email: str) -> None:
        """
        Инициирует процесс сброса пароля — создаёт токен и отправляет ссылку по email.

        :param email: Email пользователя.
        :raises ValueError: Если email не указан или не найден.
        """
        if not email:
            raise ValueError("Email is required.")

        user: User = User.query.filter_by(email=email).first()
        if not user:
            raise ValueError("Email not found.")

        # Создаём токен для сброса пароля (24 часа)
        token = EmailConfirmationToken.create(
            user.id,
            purpose="reset_pwd",
            ttl_minutes=60 * 24,
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
    def reset_password(token_str: str, new_password: str) -> Dict[str, str]:
        """
        Сброс пароля пользователя по токену.

        :param token_str: Токен сброса пароля.
        :param new_password: Новый пароль пользователя.
        :raises ValueError: Если токен недействителен, просрочен или пользователь не найден.
        :return: Сообщение об успешном изменении пароля.
        """
        # Ищем валидный токен сброса пароля
        token = EmailConfirmationToken.query.filter_by(
            token=token_str,
            purpose="reset_pwd",
        ).first()

        if token is None:
            raise ValueError("Invalid token.")

        # Проверяем, что токен активен (не использован и не просрочен)
        if not token.is_active():
            raise ValueError(
                "Token expired or already used, request a new one"
            )

        user = User.query.get(token.user_id)
        if not user:
            raise ValueError("User not found.")

        # Обновляем пароль пользователя и помечаем токен как использованный
        user.set_password(new_password)
        token.used = True
        db.session.flush()  # Фиксируем изменения перед массовым обновлением

        # Массово деактивируем все просроченные и использованные токены для данного пользователя
        EmailConfirmationToken.deactivate_expired_and_used_tokens(
            token.user_id, token.purpose
        )
        db.session.commit()

        email_service = EmailService(db.session)

        context = {
            "user_uid": user.uid,
            "subject": "Пароль успешно сброшен",
            "user_email": user.email,
            # при необходимости можно добавить дату и время сброса
        }

        email_service.send_and_log(
            to=user.email,
            template_type="password_reset.html",
            context=context,
        )

        return {"message": "Password changed successfully."}
