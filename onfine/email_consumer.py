import json
import logging
import os
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

# Адрес сервера Kafka, можно задать через переменную окружения KAFKA_BOOTSTRAP,
# по умолчанию localhost:9092
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
# Топик Kafka для чтения сообщений. Можно задать через KAFKA_TOPIC,
# по умолчанию "email_topic"
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "email_topic")
# Идентификатор группы консьюмеров Kafka, для координации оффсетов.
# Можно задать через KAFKA_GROUP_ID, по умолчанию "email_consumer_group"
KAFKA_GROUP_ID = os.getenv("KAFKA_GROUP_ID", "email_consumer_group")

# URL подключения к базе данных, например PostgreSQL.
# Задаётся через переменную окружения DATABASE_URL
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://user:password@db/dbname"
)

# Создаём движок SQLAlchemy и фабрику сессий для работы с базой
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)


def process_message(data: dict):
    """
    Обрабатывает одно сообщение из Kafka.

    Параметры:
        data (dict): Распарсенный JSON с данными письма.
            Ожидается, что содержит ключи:
            - "to": адрес получателя письма (str)
            - "template_type": тип шаблона письма (str)
            - "context": словарь с контекстом для шаблона (dict, опционально)

    Логика:
        - Отправляет письмо через send_email_by_template
        - Создаёт запись в таблице EmailLog с результатом отправки
        - В случае ошибки логирует ошибку и создаёт запись с ошибкой
    """
    session = SessionLocal()
    try:
        to = data["to"]
        template_type = data["template_type"]
        context = data.get("context", {})

        logger.info(
            f"Отправка письма на адрес {to} с шаблоном {template_type}"
        )
        send_email_by_template(to, template_type, context)

        email_log = EmailLog(
            user_uid=context.get("user_uid"),
            email_to=to,
            subject=context.get("subject", ""),
            body="",
            sent_at=datetime.utcnow(),
            success=True,
            error_message=None,
        )
        session.add(email_log)
        session.flush()  # Чтобы получить id, если нужно
        session.commit()

        logger.info(f"Письмо успешно отправлено и сохранено в лог для {to}")

    except Exception as e:
        # Откатываем транзакцию при ошибке
        session.rollback()
        logger.error(f"Error processing message: {e}")

        # Пытаемся сохранить ошибку в лог отправки
        try:
            email_log = EmailLog(
                user_uid=context.get("user_uid")
                if "context" in locals()
                else None,
                email_to=to if "to" in locals() else None,
                subject=context.get("subject")
                if "context" in locals()
                else None,
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

    Настраивает консьюмера с параметрами из переменных окружения,
    слушает указанный топик, обрабатывает каждое сообщение вызовом process_message.

    Обрабатывает сигналы прерывания и ошибки, корректно закрывая консьюмера.
    """
    consumer = KafkaConsumer(
        KAFKA_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id=KAFKA_GROUP_ID,
        auto_offset_reset="earliest",  # читать с начала, если оффсетов нет
        enable_auto_commit=True,  # автоматический коммит оффсетов
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),  # десериализация JSON
    )

    logger.info(
        f"Консьюмер писем запущен, слушает топик '{KAFKA_TOPIC}' на {KAFKA_BOOTSTRAP}"
    )

    try:
        for message in consumer:
            data = message.value
            logger.info(f"Получено сообщение: {data}")
            process_message(data)

    except KeyboardInterrupt:
        logger.info("Получен сигнал завершения, выхожу...")
    except Exception as e:
        logger.error(f"Unexpected error in consumer: {e}")
    finally:
        consumer.close()


if __name__ == "__main__":
    main()
