"""
Модуль Kafka-консьюмера для отправки email по шаблонам.

Описание:
    Этот модуль реализует консьюмера Kafka, который принимает сообщения с данными
    для отправки email, обрабатывает их, вызывает функцию отправки писем с retry,
    и записывает результат в базу данных.

Функциональность:
    - Подключение к Kafka-топику и чтение сообщений в формате JSON.
    - Обработка сообщений: извлечение email, шаблона и контекста.
    - Отправка email с использованием функции send_email_by_template из onfine.utils.mailer,
      с повторными попытками при ошибках (экспоненциальный backoff).
    - Логирование результатов отправки писем в таблицу EmailLog в PostgreSQL.
    - Обработка и логирование ошибок в процессе отправки и записи в базу.
    - Конфигурация параметров Kafka и базы данных через переменные окружения.

Используемые переменные окружения:
    - KAFKA_BOOTSTRAP: адрес Kafka bootstrap сервера (по умолчанию "localhost:9092").
    - KAFKA_TOPIC: название Kafka-топика для чтения сообщений (по умолчанию "email_topic").
    - KAFKA_GROUP_ID: ID группы консьюмера Kafka (по умолчанию "email_consumer_group").
    - DATABASE_URL: URL подключения к PostgreSQL в формате SQLAlchemy.
"""

import json
import logging
import os
import time
from datetime import datetime

from kafka import KafkaConsumer
from models import EmailLog
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from onfine.utils.mailer import send_email_by_template

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
logger = logging.getLogger("email_consumer")

# Конфигурация из переменных окружения с дефолтными значениями
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "email_topic")
KAFKA_GROUP_ID = os.getenv("KAFKA_GROUP_ID", "email_consumer_group")
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://user:password@db/dbname"
)

# Создаем движок и сессию SQLAlchemy для работы с базой данных
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)

MAX_RETRIES = 3  # Максимальное число попыток повторной отправки письма


def send_email_with_retry(
    email: str, template_type: str, context: dict
) -> dict:
    """
    Отправляет email с использованием шаблона с повторными попытками при ошибках.

    Пытается вызвать функцию send_email_by_template, которая выбрасывает исключение при ошибке.
    Если отправка успешна (исключений не возникло), возвращает {"status": "success"}.
    При возникновении ошибки повторяет попытку с экспоненциальной задержкой (1, 2, 4 секунды).
    После MAX_RETRIES неудачных попыток возвращает статус ошибки и сообщение.

    Args:
        email (str): Email получателя.
        template_type (str): Тип шаблона письма.
        context (dict): Контекст для шаблона (данные для подстановки).

    Returns:
        dict: Результат с ключом "status" и, при ошибке, "error_message".
    """
    attempt = 0
    while attempt < MAX_RETRIES:
        try:
            # send_email_by_template выбрасывает исключение при ошибке,
            # если вызов прошёл без исключений — считаем успехом
            send_email_by_template(email, template_type, context)
            return {"status": "success"}
        except Exception as e:
            wait_time = 2**attempt  # Задержка: 1, 2, 4 секунды
            logger.error(
                f"Ошибка отправки письма: {e}. Ретрай через {wait_time} сек."
            )
            time.sleep(wait_time)
            attempt += 1
    return {
        "status": "error",
        "error_message": f"Failed to send email after {MAX_RETRIES} retries",
    }


def process_message(data: dict):
    """
    Обрабатывает одно сообщение из Kafka.

    Извлекает адрес получателя, тип шаблона и контекст из сообщения,
    пытается отправить письмо с retry, логирует результат в базу.

    При возникновении ошибок при обработке сообщения или записи в БД
    логирует ошибку и пытается записать неудачную попытку отправки.

    Args:
        data (dict): Декодированное JSON-сообщение из Kafka с ключами:
            - "to": email получателя (str)
            - "template_type": тип шаблона письма (str)
            - "context": словарь с данными для шаблона (dict, опционально)
    """
    session = SessionLocal()
    to = None
    context = {}
    try:
        to = data["to"]
        template_type = data["template_type"]
        context = data.get("context", {})

        logger.info(
            f"Отправка письма на адрес {to} с шаблоном {template_type}"
        )

        result = send_email_with_retry(to, template_type, context)

        success = result.get("status") == "success"
        error_message = result.get("error_message") if not success else None

        email_log = EmailLog(
            user_uid=context.get("user_uid"),
            email_to=to,
            subject=context.get("subject", ""),
            body="",  # Можно добавить тело письма, если нужно
            sent_at=datetime.utcnow(),
            success=success,
            error_message=error_message,
        )
        session.add(email_log)
        session.commit()

        if success:
            logger.info(
                f"Письмо успешно отправлено и сохранено в лог для {to}"
            )
        else:
            logger.error(f"Письмо не отправлено для {to}: {error_message}")

    except Exception as e:
        session.rollback()
        logger.error(f"Error processing message: {e}")

        # Пытаемся сохранить ошибку в лог отправки
        try:
            email_log = EmailLog(
                user_uid=context.get("user_uid"),
                email_to=to,
                subject=context.get("subject", ""),
                body=None,
                sent_at=datetime.utcnow(),
                success=False,
                error_message=str(e),
            )
            session.add(email_log)
            session.commit()
        except Exception as log_exc:
            logger.error(f"Failed to log email error: {log_exc}")

    finally:
        session.close()


def main():
    """
    Основная функция запуска Kafka-консьюмера.

    Подписывается на топик, принимает сообщения, вызывает обработку каждого.
    Обрабатывает сигналы завершения и ошибки, корректно закрывает консьюмер.
    """
    consumer = KafkaConsumer(
        KAFKA_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id=KAFKA_GROUP_ID,
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        consumer_timeout_ms=10000,  # Таймаут ожидания сообщений (10 сек)
    )

    logger.info(
        f"Консьюмер писем запущен, слушает топик '{KAFKA_TOPIC}' на {KAFKA_BOOTSTRAP}"
    )

    try:
        for message in consumer:
            data = message.value
            logger.info(f"Получено сообщение: {data}")
            process_message(data)

    except StopIteration:
        logger.info(
            "Таймаут ожидания сообщений истёк, завершаю работу консьюмера"
        )
    except KeyboardInterrupt:
        logger.info("Получен сигнал завершения, выхожу...")
    except Exception as e:
        logger.error(f"Unexpected error in consumer: {e}")
    finally:
        consumer.close()


if __name__ == "__main__":
    main()
