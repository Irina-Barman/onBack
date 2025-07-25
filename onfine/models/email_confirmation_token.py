import uuid
from datetime import datetime, timedelta

from sqlalchemy import and_, or_

from ..extensions import db


# Переименовано с Token
class EmailConfirmationToken(db.Model):
    """
    Модель токена подтверждения email или сброса пароля.

    Атрибуты:
        id (int): Уникальный идентификатор токена.
        user_id (int): Идентификатор пользователя, которому принадлежит токен.
        token (str): Уникальная строка токена (UUID4 hex).
        purpose (str): Назначение токена, например 'confirm_email' или 'reset_pwd'.
        expires_at (datetime): Время истечения срока действия токена.
        used (bool): Флаг, указывающий, был ли токен использован.
        created_at (datetime): Время создания токена.

    Методы:
        deactivate_expired_and_used_tokens(user_id, purpose):
            Помечает все токены пользователя, которые использованы или просрочены, как использованные.

        get_active_token(user_id, purpose):
            Возвращает первый найденный активный (неиспользованный и не просроченный) токен
            для пользователя и указанной цели или None, если такого нет.

        is_active(self):
            Проверяет, что токен не использован и не просрочен, возвращает булевое значение.
            (метод для сервиса, чтобы разделять исключения)


        create(user_id, purpose, ttl_minutes):
            Создает новый токен с заданным временем жизни (в минутах) или возвращает
            существующий активный токен. Перед созданием нового токена помечает старые как использованные.

    Особенности:
        - Токены уникальны и генерируются с помощью UUID4.
        - Используется явное управление сессией базы данных (flush, commit).
    """

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
    purpose = db.Column(
        db.String(32), nullable=False
    )  # Возможные значения: 'confirm_email', 'reset_pwd'
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def is_active(self) -> bool:
        """
        Проверяет, что токен не использован и не просрочен.

        :return: True, если токен активен, иначе False.
        """
        return (not self.used) and (self.expires_at > datetime.utcnow())

    @staticmethod
    def deactivate_expired_and_used_tokens(user_id: int, purpose: str) -> None:
        """
        Помечает все токены пользователя, которые использованы или просрочены, как использованные.

        :param user_id: Идентификатор пользователя.
        :param purpose: Назначение токена.
        """
        now = datetime.utcnow()
        (
            EmailConfirmationToken.query.filter(
                EmailConfirmationToken.user_id == user_id,
                EmailConfirmationToken.purpose == purpose,
                or_(
                    EmailConfirmationToken.used.is_(True),
                    and_(
                        EmailConfirmationToken.used.is_(False),
                        EmailConfirmationToken.expires_at < now,
                    ),
                ),
            )
            .filter(
                EmailConfirmationToken.used.is_(False)
            )  # Обновляем только неиспользованные
            .update({"used": True}, synchronize_session="fetch")
        )
        db.session.flush()

    @staticmethod
    def get_active_token(
        user_id: int, purpose: str
    ) -> "EmailConfirmationToken":
        """
        Получает первый доступный активный токен для пользователя и цели.

        Активный токен — это токен, который:
        - Не был использован (used == False).
        - Истекшее время (expires_at) еще не наступило.

        :param user_id: Идентификатор пользователя.
        :param purpose: Назначение токена.
        :return: Объект EmailConfirmationToken или None, если активных токенов нет.
        """
        now = datetime.utcnow()
        return (
            EmailConfirmationToken.query.filter_by(
                user_id=user_id,
                purpose=purpose,
                used=False,
            )
            .filter(EmailConfirmationToken.expires_at > now)
            .first()
        )

    @staticmethod
    def create(
        user_id: int, purpose: str, ttl_minutes: int
    ) -> "EmailConfirmationToken":
        """
        Создает новый токен с указанным временем жизни или возвращает существующий активный.

        Логика:
        - Сначала помечает все устаревшие и использованные токены как использованные.
        - Проверяет наличие активного токена для данного пользователя и цели.
        - Если активный токен найден, возвращает его.
        - Иначе создает новый токен с уникальным UUID и временем истечения.

        :param user_id: Идентификатор пользователя.
        :param purpose: Назначение токена ('confirm_email' или 'reset_pwd').
        :param ttl_minutes: Время жизни токена в минутах.
        :return: Объект EmailConfirmationToken.
        """
        # Помечаем устаревшие и использованные токены
        EmailConfirmationToken.deactivate_expired_and_used_tokens(
            user_id, purpose
        )

        # Проверяем наличие активного токена
        existing_token = EmailConfirmationToken.get_active_token(
            user_id, purpose
        )
        if existing_token:
            return existing_token

        # Создаем новый токен с уникальным UUID и временем истечения
        new_token = EmailConfirmationToken(
            user_id=user_id,
            purpose=purpose,
            expires_at=datetime.utcnow() + timedelta(minutes=ttl_minutes),
        )
        db.session.add(new_token)
        db.session.flush()  # Получаем id и token до коммита
        return new_token
