"""
Модуль email_service — сервис для отправки email-сообщений с повторными попытками и логированием в БД.

Функционал:
- Отправка email-сообщений с использованием KafkaProducer (публикация в Kafka-топик).
- Повторные попытки отправки с экспоненциальной задержкой при ошибках (максимум 3 попытки).
- Логирование попыток отправки (успех/ошибка) в базу данных через SQLAlchemy-модель EmailLog.
- Логирование действий и ошибок через стандартный модуль logging.

Переменные окружения (с значениями по умолчанию):
- KAFKA_BOOTSTRAP: адрес Kafka bootstrap-сервера (default: "localhost:9092")
- KAFKA_TOPIC: имя Kafka-топика для публикации сообщений (default: "mailer_emails")

Зависимости:
- kafka-python — KafkaProducer для публикации сообщений
- sqlalchemy.orm.Session — сессия для работы с базой данных
- models.EmailLog — ORM-модель для записи логов email
- logging, time, datetime — для логирования, таймаутов и временных меток
"""

import json
import logging
import os
import time
from datetime import datetime
from typing import Dict, Optional

from kafka import KafkaProducer

from sqlalchemy.orm import Session

from onfine.models.email_log import EmailLog

# from onfine.utils.mailer import send_email_by_template

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


class EmailService:
    """
    Сервис для отправки email через Kafka с повторными попытками и логированием в БД.

    Атрибуты:
        db_session (Session): сессия SQLAlchemy для работы с БД.
        producer (KafkaProducer | None): KafkaProducer для публикации сообщений.
        kafka_topic (str): имя Kafka-топика для отправки сообщений.

    Методы:
        send_email_with_retry(to, template_type, context) -> Dict:
            Пытается отправить email с повторными попытками при ошибках.
        log_email(to, context, success, error_message=None) -> None:
            Сохраняет запись о попытке отправки письма в базу.
        send_and_log(to, template_type, context) -> None:
            Отправляет письмо с ретраями и логирует результат.
    """

    def __init__(self, db_session: Session):
        """
        Инициализирует сервис, настраивает KafkaProducer и сохраняет сессию БД.

        Args:
            db_session (Session): активная сессия SQLAlchemy для работы с базой.
        """
        self.db_session = db_session

        kafka_servers = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
        self.kafka_topic = os.getenv("KAFKA_TOPIC", "mailer_emails")
        try:
            self.producer = KafkaProducer(
                bootstrap_servers=kafka_servers,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            )
        except Exception as e:
            logger.error(f"Ошибка инициализации Kafka Producer: {e}")
            self.producer = None

    def send_email_with_retry(
        self, to: str, template_type: str, context: dict
    ) -> Dict[str, Optional[str]]:
        """
        Пытается отправить email с повторными попытками при ошибках.

        Args:
            to (str): Email получателя.
            template_type (str): Имя шаблона письма.
            context (dict): Контекст для шаблона, может содержать 'subject'.

        Returns:
            dict: Результат отправки с ключами:
                - "status": "success" или "error"
                - "error_message": текст ошибки или None при успехе

        Логика:
        - Выполняет до MAX_RETRIES попыток отправки.
        - При неудаче ждет экспоненциально растущий таймаут (2^attempt сек).
        - Публикует сообщение в Kafka, логирует попытки и ошибки.
        """
        attempt = 0
        while attempt < MAX_RETRIES:
            try:
                subject = context.get("subject", "<no subject>")

                logger.info(
                    f"[MOCK SEND EMAIL] To: {to}\n"
                    f"Template: {template_type}\n"
                    f"Subject: {subject}\n"
                    f"Context: {context}"
                )

                if self.producer:
                    try:
                        msg = {
                            "to": to,
                            "subject": subject,
                            "template": template_type,
                            "context": context,
                        }
                        self.producer.send(self.kafka_topic, msg)
                        self.producer.flush()
                        logger.info(
                            f"Email message published to Kafka topic '{self.kafka_topic}'"
                        )
                    except Exception as e:
                        logger.error(f"Ошибка публикации в Kafka: {e}")
                        raise

                return {"status": "success", "error_message": None}

            except Exception as e:
                wait_time = 2**attempt
                logger.error(
                    f"Ошибка при mock отправке письма (attempt {attempt + 1}/{MAX_RETRIES}) "
                    f"для {to}: {e}. Ретрай через {wait_time} сек."
                )
                time.sleep(wait_time)
                attempt += 1

        return {
            "status": "error",
            "error_message": f"Failed to mock send email after {MAX_RETRIES} retries",
        }

    def log_email(
        self,
        to: str,
        context: dict,
        success: bool,
        error_message: Optional[str] = None,
    ) -> None:
        """
        Сохраняет запись о попытке отправки email в базу данных.

        Args:
            to (str): Email получателя.
            context (dict): Контекст письма, используется для subject и user_uid.
            success (bool): Флаг успеха отправки.
            error_message (Optional[str]): Текст ошибки, если отправка неуспешна.

        Использует ORM-модель EmailLog и коммитит изменения в сессии.
        """
        email_log = EmailLog(
            user_uid=context.get("user_uid"),
            email_to=to,
            subject=context.get("subject", ""),
            body="",
            sent_at=datetime.utcnow(),
            success=success,
            error_message=error_message,
        )
        self.db_session.add(email_log)
        self.db_session.commit()

    def send_and_log(self, to: str, template_type: str, context: dict) -> None:
        """
        Отправляет email с повторными попытками и логирует результат в базу.

        Args:
            to (str): Email получателя.
            template_type (str): Имя шаблона письма.
            context (dict): Контекст для шаблона.

        Логика:
        - Вызывает send_email_with_retry для отправки.
        - Логирует результат вызовом log_email.
        - Логирует в журнал успех или ошибку.
        - Ловит и логирует ошибки при сохранении в БД.
        """
        result = self.send_email_with_retry(to, template_type, context)
        success = result.get("status") == "success"
        error_message = result.get("error_message") if not success else None

        try:
            self.log_email(to, context, success, error_message)
            if success:
                logger.info(
                    f"Письмо успешно отправлено и сохранено в лог для {to}"
                )
            else:
                logger.error(
                    f"Письмо не отправлено для {to}: {error_message}"
                )
        except Exception as e:
            logger.error(f"Ошибка логирования письма для {to}: {e}")
