"""
Модуль email_consumer — Kafka-консьюмер для обработки сообщений с данными для отправки email.

Функционал:
- Подключается к Kafka-топику, указанному в переменной окружения KAFKA_TOPIC.
- Получает сообщения в формате JSON с полями:
    - "to": адрес получателя письма (str)
    - "template_type": тип шаблона письма (str)
    - "context": словарь с параметрами шаблона (dict, опционально)
- Для каждого сообщения вызывает функцию process_message, которая:
    - Создает сессию базы данных.
    - Использует сервис EmailService для отправки письма с retry.
    - Логирует результаты отправки в таблицу EmailLog.
    - При ошибках отправки или записи логов сохраняет информацию об ошибке.
- Логирует ключевые события и ошибки.
- Обрабатывает корректное завершение работы по таймауту ожидания сообщений или сигналам прерывания.

Переменные окружения (с значениями по умолчанию):
- KAFKA_BOOTSTRAP: адрес Kafka bootstrap-сервера (default: "localhost:9092")
- KAFKA_TOPIC: имя Kafka-топика для чтения сообщений (default: "email_topic")
- KAFKA_GROUP_ID: ID группы консьюмера Kafka (default: "email_consumer_group")
- DATABASE_URL: строка подключения к базе данных PostgreSQL (default: "postgresql://user:password@db/dbname")

Зависимости:
- kafka-python для работы с Kafka
- SQLAlchemy для работы с базой данных
- onfine.services.email_service.EmailService — сервис отправки email с retry и логированием
- models.EmailLog — ORM-модель для хранения логов отправки писем
"""

import json
import logging
import os
from datetime import datetime

from kafka import KafkaConsumer
from models import EmailLog
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from onfine.services.email_service import EmailService

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
logger = logging.getLogger("email_consumer")

# Конфигурация подключения к Kafka и базе данных через переменные окружения
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "email_topic")
KAFKA_GROUP_ID = os.getenv("KAFKA_GROUP_ID", "email_consumer_group")
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://user:password@db/dbname"
)

# Создаем движок SQLAlchemy и фабрику сессий для работы с базой данных
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)


def process_message(data: dict):
    """
    Обрабатывает одно сообщение из Kafka.

    Создает сессию БД и экземпляр EmailService.
    Извлекает необходимые поля из сообщения:
        - to: email получателя (str)
        - template_type: тип шаблона письма (str)
        - context: словарь с данными для шаблона (dict, опционально)

    Вызывает метод send_and_log сервиса для отправки письма с retry и логированием.
    В случае исключений откатывает транзакцию и пытается записать ошибку в EmailLog.

    Args:
        data (dict): Декодированное JSON-сообщение из Kafka с ключами:
            - "to": адрес получателя (str)
            - "template_type": тип шаблона (str)
            - "context": контекст шаблона (dict, опционально)

    Логирует ключевые события и ошибки.
    """
    session = SessionLocal()
    email_service = EmailService(session)
    to = None
    context = {}
    try:
        to = data["to"]
        template_type = data["template_type"]
        context = data.get("context", {})

        logger.info(
            f"Отправка письма на адрес {to} с шаблоном {template_type}"
        )

        # Отправка письма с retry и сохранение результата в базу
        email_service.send_and_log(to, template_type, context)

    except Exception as e:
        session.rollback()
        logger.error(f"Error processing message: {e}")

        # Пытаемся сохранить информацию об ошибке в EmailLog
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

    Подключается к Kafka-топику с настройками из переменных окружения.
    Слушает сообщения в бесконечном цикле (с таймаутом ожидания).
    Для каждого сообщения вызывает process_message.

    Обрабатывает сигналы завершения и исключения, корректно закрывая консьюмер.

    Логирует ключевые события работы консьюмера.
    """
    consumer = KafkaConsumer(
        KAFKA_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id=KAFKA_GROUP_ID,
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        consumer_timeout_ms=10000,  # Таймаут ожидания сообщений (10 секунд)
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
