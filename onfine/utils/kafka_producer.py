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
import uuid
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
    message_id: Optional[str] = None,
) -> Optional[str]:
    """
    Отправляет сообщение в Kafka топик.

    Возвращает message_id если успешно, иначе None.
    """

    producer = _get_producer()
    if not producer:
        logger.error(f"Producer unavailable. Dropping message to {topic}: {data}")
        return None

    if not message_id:
        message_id = str(uuid.uuid4())
    data_with_id = data.copy()
    data_with_id["message_id"] = message_id

    for attempt in range(retries):
        try:
            future = producer.send(topic, data_with_id)
            future.get(timeout=10.0)
            logger.debug(f"Message sent to {topic}: {data_with_id}")
            return message_id
        except KafkaTimeoutError as e:
            logger.warning(f"Timeout sending to {topic} (attempt {attempt + 1}): {e}")
        except KafkaError as e:
            logger.error(f"Failed to send to {topic} (attempt {attempt + 1}): {e}")

        if attempt < retries - 1:
            time.sleep(backoff)

    logger.error(f"Message dropped after {retries} retries: {data_with_id}")
    return None


def flush() -> None:
    """Принудительно отправить все буферизованные сообщения."""
    if _producer:
        _producer.flush()
