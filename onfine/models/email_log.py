import uuid
from datetime import datetime

from onfine.extensions import db


class EmailLog(db.Model):
    """
    Модель для хранения логов отправленных email-сообщений.

    Каждая запись отражает попытку отправки письма, включая
    информацию о получателе, теме, теле письма, времени отправки,
    а также статус отправки (успех/ошибка).

    Поля:
        id (BigInteger): Автоинкрементный первичный ключ записи.
        uid (String(36)): Уникальный UUID записи в строковом формате.
        user_uid (String(36)): UUID пользователя, которому отправлено письмо (внешний ключ на users.uid).
        email_to (String): Email адрес получателя письма.
        subject (String): Тема письма.
        body (Text): Текст письма (может быть пустым).
        sent_at (DateTime): Время отправки письма (UTC).
        success (Boolean): Флаг успешной отправки (True — успешно).
        error_message (Text): Сообщение об ошибке, если отправка не удалась.
        message_id (str): Уникальный идентификатор сообщения из Kafka.
    """

    __tablename__ = "email_logs"

    id = db.Column(
        db.BigInteger,
        primary_key=True,  # Автоинкрементный первичный ключ записи
    )

    uid = db.Column(
        db.String(36),
        unique=True,
        nullable=False,
        default=lambda: str(uuid.uuid4()),
        index=True,  # Уникальный UUID записи (строка формата UUID)
    )
    message_id = db.Column(
        db.String(100),
        unique=True,
        nullable=False,
        index=True,
        comment="Уникальный идентификатор сообщения из Kafka",
    )

    user_uid = db.Column(
        db.String(36),
        db.ForeignKey("users.uid"),
        nullable=True,
        index=True,  # UUID пользователя, которому отправлено письмо (может быть NULL)
    )

    email_to = db.Column(
        db.String(255),
        nullable=False,
        index=True,  # Email адрес получателя письма
    )

    subject = db.Column(db.String(255), nullable=False, comment="Тема письма")

    body = db.Column(
        db.Text,
        nullable=True,  # Текст письма (может отсутствовать)
    )

    sent_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False,  # Дата и время отправки письма в UTC",
    )

    success = db.Column(
        db.Boolean,
        default=True,
        nullable=False,  # Флаг успешной отправки (True — письмо отправлено успешно
    )

    error_message = db.Column(
        db.Text,
        nullable=True,  # Текст ошибки, если отправка письма не удалась
    )

    # Связь с моделью User по полю user_uid
    user = db.relationship(
        "User",
        backref=db.backref("email_logs", lazy=True),  #  Связь с пользователем, которому отправлено письмо
    )

    def __repr__(self):  # noqa ANN204
        """
        Возвращает строковое представление объекта EmailLog,
        удобное для отладки и логирования.
        """
        return (
            f"<EmailLog uid={self.uid} to={self.email_to} "
            f"subject={self.subject} sent_at={self.sent_at} success={self.success}>"
        )
