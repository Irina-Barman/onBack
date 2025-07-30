"""
Email Consumer Service

Этот модуль реализует Kafka-консьюмера, который слушает входящий топик с email-сообщениями,
валидация и обработка которых ведется с записью результатов в базу данных и публикацией статуса отправки
в другой Kafka-топик.

Основные компоненты:
- Валидация входящих сообщений
- Обработка сообщений с сохранением логов в БД (PostgreSQL)
- Публикация результатов обработки в Kafka с указанием статуса (успешно/ошибка)
- Управление offset-ами вручную для обеспечения at-least-once обработки

Переменные окружения, используемые в конфигурации:
- KAFKA_BOOTSTRAP: адрес Kafka bootstrap сервера (по умолчанию "kafka:9092")
- EMAIL_TOPIC: входящий Kafka топик для email сообщений (по умолчанию "email_topic")
- ERROR_TOPIC: исходящий Kafka топик для статусов email (по умолчанию "error_emails")
- KAFKA_GROUP_ID: группа консьюмера Kafka (по умолчанию "email_consumer_group")
- DATABASE_URL: строка подключения к базе данных PostgreSQL

Зависимости:
- kafka-python
- SQLAlchemy
- onfine.models.email_log.EmailLog (ORM модель для таблицы логов email)
- onfine.utils.kafka_producer (функции send и flush для взаимодействия с Kafka)

Логирование:
- Используется логгер с именем "email_consumer" для вывода информации и ошибок.

"""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from kafka import KafkaConsumer, OffsetAndMetadata, TopicPartition
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from onfine.models.email_log import EmailLog
from onfine.utils.kafka_producer import flush, send

logger = logging.getLogger("email_consumer")

KAFKA_BOOTSTRAP: str = os.getenv("KAFKA_BOOTSTRAP", "kafka:9092")
KAFKA_TOPIC_IN: str = os.getenv("EMAIL_TOPIC", "email_topic")
KAFKA_TOPIC_OUT: str = os.getenv("ERROR_TOPIC", "error_emails")
KAFKA_GROUP_ID: str = os.getenv("KAFKA_GROUP_ID", "email_consumer_group")
DATABASE_URL: str = os.getenv(
    "DATABASE_URL", "postgresql://user:password@db/dbname"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)


def validate_message(data: Any) -> bool:
    """
    Валидирует структуру входящего сообщения.

    Проверяет, что:
    - data является словарём
    - содержит обязательные поля "to" (str) и "template_type" (str)
    - если присутствует поле "context", то оно должно быть словарём

    Args:
        data (Any): Десериализованное JSON-сообщение из Kafka.

    Returns:
        bool: True, если сообщение валидно, иначе False.
    """
    if not isinstance(data, dict):
        return False
    if "to" not in data or not isinstance(data["to"], str):
        return False
    if "template_type" not in data or not isinstance(
        data["template_type"], str
    ):
        return False
    if "context" in data and not isinstance(data["context"], dict):
        return False
    return True


def process_message(
    data: Dict[str, Any],
    status: str = "sent",
    error_message: Optional[str] = None,
) -> None:
    """
    Обрабатывает сообщение: сохраняет лог в базе и публикует статус в Kafka.

    Если message_id отсутствует, генерируется SHA256-хеш по ключевым полям.
    Проверяется наличие записи с таким message_id в базе, чтобы избежать дубликатов.
    В случае конфликтов уникальности — ошибка логируется и обработка продолжается.

    Параметры:
        data (Dict[str, Any]): Валидированное сообщение с данными email.
        status (str): Статус обработки сообщения.
            Возможные значения: "sent" (успешно), "error" (ошибка).
            По умолчанию "sent".
        error_message (Optional[str]): Текст ошибки при статусе "error".
            По умолчанию None.

    При публикации в Kafka отправляется сообщение с полями:
        - status: статус обработки ("error" — только при ошибках)
        - to: адрес получателя
        - template_type: тип шаблона письма
        - при необходимости, можно добавить context (контекст письма) в result_message
        - sent_at: время публикации статуса в ISO формате
        - error: текст ошибки (если есть)
    """
    session: Session = SessionLocal()
    try:
        message_id: Optional[str] = data.get("message_id")
        if not message_id:
            unique_str = f"{data['to']}|{data['template_type']}|{data.get('sent_at', '')}"
            message_id = hashlib.sha256(unique_str.encode("utf-8")).hexdigest()

        session.expire_all()

        existing: Optional[EmailLog] = (
            session.query(EmailLog).filter_by(message_id=message_id).first()
        )
        if existing:
            logger.info(
                f"Сообщение с message_id={message_id} уже обработано, пропускаем"
            )
            return

        email_log = EmailLog(
            message_id=message_id,
            user_uid=data.get("context", {}).get("user_uid"),
            email_to=data["to"],
            subject=data.get("context", {}).get("subject", ""),
            body=None,
            sent_at=datetime.now(timezone.utc),
            success=(status == "sent"),
            error_message=error_message,
        )
        session.add(email_log)
        try:
            session.commit()
        except Exception as e:
            session.rollback()
            if "duplicate key value" in str(e):
                logger.warning(
                    f"Дубликат message_id={message_id} при вставке — пропускаем"
                )
                return
            else:
                raise

        # Отправляем в Kafka только если статус "error"
        if status == "error":
            result_message: Dict[str, Any] = {
                "status": status,
                "to": data["to"],
                "template_type": data["template_type"],
                "sent_at": datetime.now(timezone.utc).isoformat(),
            }
            if error_message:
                result_message["error"] = error_message

            sent_message_id: Optional[str] = send(
                KAFKA_TOPIC_OUT, result_message, message_id=message_id
            )
            if sent_message_id is None:
                logger.error(
                    f"Failed to send message_id={message_id} to Kafka topic {KAFKA_TOPIC_OUT}"
                )
            else:
                logger.info(
                    f"Опубликовано в {KAFKA_TOPIC_OUT}: message_id={sent_message_id}"
                )
    except Exception:
        session.rollback()
        logger.error("Ошибка обработки сообщения", exc_info=True)
        raise
    finally:
        session.close()


def main() -> None:
    """
    Основная функция запуска Kafka-консьюмера.

    Логика обработки сообщений:
    - Подключается к Kafka и слушает входящий топик.
    - Для каждого полученного сообщения сразу коммитит offset (message.offset + 1),
      чтобы избежать повторного чтения этого сообщения.
    - Валидирует сообщение.
      - Если сообщение невалидно, логирует ошибку и пропускает.
    - Если валидно, пытается обработать:
      - При успешной обработке сохраняет лог и публикует статус "sent".
      - При ошибке обработки публикует статус "error" с текстом ошибки.
    - Ошибки при публикации статуса "error" логируются, но не вызывают повторной обработки.
    - Цикл обработки не прерывается при ошибках отдельных сообщений.
    - Обработка offset-ов вручную обеспечивает at-least-once семантику с минимальной задержкой.
    - При завершении работы корректно закрывает консьюмер и сбрасывает буферы.

    Returns:
        None
    """
    consumer = KafkaConsumer(
        KAFKA_TOPIC_IN,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id=KAFKA_GROUP_ID,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        consumer_timeout_ms=10000,
    )

    logger.info(
        f"Консьюмер писем запущен, слушает топик '{KAFKA_TOPIC_IN}' на {KAFKA_BOOTSTRAP}"
    )

    try:
        while True:
            try:
                for message in consumer:
                    data = message.value
                    logger.info(f"Получено сообщение: {data}")

                    # Немедленно коммитим offset, чтобы не читать сообщение повторно
                    consumer.commit(
                        offsets={
                            TopicPartition(
                                message.topic, message.partition
                            ): OffsetAndMetadata(
                                message.offset + 1, leader_epoch=-1
                            )
                        }
                    )

                    if not validate_message(data):
                        logger.error(f"Невалидное сообщение: {data}")
                        # Пропускаем сообщение, offset уже сдвинут
                        continue

                    try:
                        process_message(data)
                    except Exception as e:
                        logger.error(
                            f"Ошибка при обработке сообщения: {e}",
                            exc_info=True,
                        )
                        try:
                            # Публикуем статус "error" с описанием проблемы
                            process_message(
                                data, status="error", error_message=str(e)
                            )
                        except Exception as inner_e:
                            logger.error(
                                f"Ошибка при публикации ошибки: {inner_e}",
                                exc_info=True,
                            )
                        # Продолжаем обработку следующих сообщений без повторного чтения
                        continue

                logger.debug(
                    "Таймаут ожидания сообщений, продолжаю слушать..."
                )
            except StopIteration:
                # Исключение StopIteration может возникать при consumer_timeout_ms
                continue

    except KeyboardInterrupt:
        logger.info("Получен сигнал завершения, выхожу...")
    except Exception as e:
        logger.error(f"Неожиданная ошибка в консьюмере: {e}", exc_info=True)
    finally:
        consumer.close()
        flush()


if __name__ == "__main__":
    main()
