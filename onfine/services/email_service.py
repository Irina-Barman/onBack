"""
Модуль email_service — сервис для отправки email-сообщений с повторными попытками и логированием в БД.
Общая логика работы:
        1. Формируется сообщение с адресатом, типом шаблона и контекстом.
        2. Сообщение отправляется в Kafka-топик с заданным числом повторных попыток.
        3. По результату отправки формируется статус и уникальный идентификатор сообщения.
        4. Результат отправки сохраняется в таблицу email_logs с привязкой к пользователю.
        5. Все ошибки отправки и логирования фиксируются в логах.

    Переменные окружения и конфигурация (не входят в этот класс, но важны для работы):
        - Kafka bootstrap servers и параметры подключения (используются в onfine.utils.kafka_producer.send)
        - Настройки базы данных PostgreSQL (конфиг для SQLAlchemy Session)
        - Константы MAX_RETRIES, backoff — задают поведение повторных попыток отправки

    Зависимости:
        - SQLAlchemy для работы с базой данных (Session, модели)
        - Модель EmailLog: ORM-модель таблицы email_logs, содержащей поля:
            user_uid, email_to, subject, body, sent_at, success, error_message, message_id
        - Kafka producer: функция send(topic, message, retries, backoff) из onfine.utils.kafka_producer,
          которая реализует отправку сообщений с retry и возвращает уникальный message_id
        - Стандартный модуль logging для логирования ошибок и информации

    Атрибуты:
        db_session (Session): сессия SQLAlchemy для работы с базой данных.

    Методы:
        send_email_with_retry(to, template_type, context) -> Dict[str, Optional[str]]:
            Отправляет email-сообщение в Kafka с повторными попытками.
        log_email(to, context, success, error_message=None, message_id=None) -> None:
            Логирует результат отправки письма в таблицу email_logs.
        send_and_log(to, template_type, context) -> None:
            Комбинирует отправку письма и логирование результата с обработкой ошибок.

    Примечание:
        Контекст (context) должен содержать ключи 'user_uid' и 'subject' для корректного логирования.
        message_id связывает запись в базе с конкретным сообщением Kafka, что позволяет отслеживать
        статус доставки и отладку.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional

from sqlalchemy.orm import Session

from onfine.models.email_log import EmailLog
from onfine.utils.kafka_producer import send

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


class EmailService:
    """
    Сервис для отправки email-сообщений через Kafka с повторными попытками
    и логированием результатов отправки в базу данных PostgreSQL.

    """

    def __init__(self, db_session: Session) -> None:
        """
        Инициализация сервиса сессией базы данных.

        Args:
            db_session (Session): активная сессия SQLAlchemy для работы с БД.
        """
        self.db_session = db_session

    def send_email_with_retry(
        self, to: str, template_type: str, context: dict
    ) -> Dict[str, Optional[str]]:
        """
        Отправляет email-сообщение в Kafka с повторными попытками.

        Формирует сообщение с адресатом, типом шаблона и контекстом,
        отправляет в Kafka-топик 'email_topic' с максимальным числом повторов.

        Args:
            to (str): адрес электронной почты получателя.
            template_type (str): идентификатор шаблона письма.
            context (dict): словарь с дополнительными данными для шаблона,
                должен содержать хотя бы 'user_uid' и 'subject' для логирования.

        Returns:
            dict: словарь с ключами:
                - 'status': 'success' или 'error'
                - 'error_message': строка с описанием ошибки или None
                - 'message_id': уникальный идентификатор сообщения в Kafka или None
        """
        topic = "email_topic"
        message_id = str(
            uuid.uuid4()
        )  # Генерируем уникальный id для сообщения

        message = {
            "to": to,
            "template_type": template_type,
            "context": context,
            "message_id": message_id,
            "sent_at": datetime.now(timezone.utc).isoformat(),
        }

        sent_message_id = send(
            topic, message, retries=MAX_RETRIES, backoff=2.0
        )
        if sent_message_id:
            return {
                "status": "success",
                "error_message": None,
                "message_id": message_id,
            }
        else:
            error_msg = f"Failed to send message to Kafka topic '{topic}' after {MAX_RETRIES} retries"
            logger.error(error_msg)
            return {
                "status": "error",
                "error_message": error_msg,
                "message_id": None,
            }

    def log_email(
        self,
        to: str,
        context: dict,
        success: bool,
        error_message: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> None:
        """
        Сохраняет информацию о попытке отправки email в базу данных.

        Если message_id не передан, генерируется новый UUID.
        Записывает данные в таблицу email_logs с полями:
        user_uid, email_to, subject, body (пустое), sent_at (текущее время UTC),
        success, error_message, message_id.

        Args:
            to (str): адрес электронной почты получателя.
            context (dict): контекст с данными письма, ожидается наличие ключей:
                'user_uid' (str) - уникальный идентификатор пользователя,
                'subject' (str) - тема письма.
            success (bool): статус успешности отправки.
            error_message (Optional[str]): текст ошибки, если отправка не удалась.
            message_id (Optional[str]): уникальный идентификатор сообщения,
                связывает запись в БД и сообщение Kafka.
        """
        if not message_id:
            message_id = str(uuid.uuid4())

        email_log = EmailLog(
            user_uid=context.get("user_uid"),
            email_to=to,
            subject=context.get("subject", ""),
            body="",
            sent_at=datetime.now(timezone.utc),
            success=success,
            error_message=error_message,
            message_id=message_id,
        )
        self.db_session.add(email_log)
        self.db_session.commit()

    def send_and_log(self, to: str, template_type: str, context: dict) -> None:
        """
        Выполняет отправку email с повторными попытками и логирование результата.

        Отправляет сообщение методом send_email_with_retry, затем сохраняет результат
        в базу через log_email. Логирует успешную отправку или ошибки отправки и логирования.

        Args:
            to (str): адрес электронной почты получателя.
            template_type (str): тип шаблона письма.
            context (dict): контекст с данными письма.

        Возвращаемое значение:
            None
        """
        result = self.send_email_with_retry(to, template_type, context)
        success = result.get("status") == "success"
        error_message = result.get("error_message") if not success else None
        message_id = result.get("message_id")

        try:
            self.log_email(to, context, success, error_message, message_id)
            if success:
                logger.info(
                    f"Письмо успешно отправлено и сохранено в лог для {to}"
                )
            else:
                logger.error(f"Письмо не отправлено для {to}: {error_message}")
        except Exception as e:
            logger.error(f"Ошибка логирования письма для {to}: {e}", exc_info=True)
