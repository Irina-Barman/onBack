# import os, json
# from kafka import KafkaProducer
#
# _producer = KafkaProducer(
#         bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP", "kafka:9092"),
#         value_serializer=lambda d: json.dumps(d).encode())
#
# def send(topic: str, data: dict):
#     _producer.send(topic, data)
#     _producer.flush()
# Не работает жесткая инциализация

import json
import logging
import os
import time
from typing import Any, Dict, Optional

from kafka import KafkaProducer
from kafka.errors import KafkaError, KafkaTimeoutError

logger = logging.getLogger(__name__)
_producer: Optional[KafkaProducer] = None


def _get_producer(retries: int = 3) -> Optional[KafkaProducer]:
    """Инициализация продюсера с ретраями."""
    global _producer
    if _producer is not None:
        return _producer

    bootstrap = os.getenv("KAFKA_BOOTSTRAP", "kafka:9092")
    for attempt in range(retries):
        try:
            producer = KafkaProducer(
                bootstrap_servers=bootstrap,
                value_serializer=lambda d: json.dumps(d).encode("utf-8"),
                acks="all",  # Ждём подтверждения от всех реплик
                retries=3,  # Ретраи на уровне клиента
            )
            if producer.bootstrap_connected():
                _producer = producer
                logger.info(f"Connected to Kafka at {bootstrap}")
                return _producer
        except KafkaError as e:
            logger.error(f"Attempt {attempt + 1}: Kafka connection failed: {e}")
            if attempt < retries - 1:
                time.sleep(2)

    logger.critical("All Kafka connection attempts failed!")
    return None


def send(
    topic: str,
    data: Dict[str, Any],
    retries: int = 3,
    backoff: float = 1.0,
) -> bool:
    """
    Отправляет сообщение в Kafka топик.

    Args:
        topic: Название топика.
        data: Данные для отправки (словарь).
        retries: Количество попыток при ошибке.
        backoff: Задержка между попытками (сек).

    Returns:
        bool: Успешно ли отправлено.
    """
    producer = _get_producer()
    if not producer:
        logger.error(f"Producer unavailable. Dropping message to {topic}: {data}")
        return False

    for attempt in range(retries):
        try:
            future = producer.send(topic, data)
            future.get(timeout=10.0)  # Блокируемся до подтверждения
            logger.debug(f"Message sent to {topic}: {data}")
            return True
        except KafkaTimeoutError as e:
            logger.warning(f"Timeout sending to {topic} (attempt {attempt + 1}): {e}")
        except KafkaError as e:
            logger.error(f"Failed to send to {topic} (attempt {attempt + 1}): {e}")

        if attempt < retries - 1:
            time.sleep(backoff)

    logger.error(f"Message dropped after {retries} retries: {data}")
    return False


def flush() -> None:
    """Принудительно отправить все буферизованные сообщения."""
    if _producer:
        _producer.flush()
