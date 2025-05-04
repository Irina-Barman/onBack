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
#Не работает жесткая инциализация

import os
import json
import logging
from kafka import KafkaProducer
from kafka.errors import KafkaError


logger = logging.getLogger(__name__)
_producer: KafkaProducer | None = None


def _get_producer() -> KafkaProducer | None:
    global _producer
    if _producer is not None:
        return _producer

    bootstrap = os.getenv("KAFKA_BOOTSTRAP", "kafka:9092")
    try:
        p = KafkaProducer(
            bootstrap_servers=bootstrap,
            value_serializer=lambda d: json.dumps(d).encode(),
        )
        # проверим сразу, что подключились
        p.bootstrap_connected()
        _producer = p
        logger.info(f"KafkaProducer initialized, bootstrap={bootstrap}")
    except KafkaError as e:
        logger.error(f"Cannot connect to Kafka broker at {bootstrap}: {e}")
        _producer = None
    return _producer


def send(topic: str, data: dict) -> bool:
    """
    Отправить сообщение в Kafka.
    Возвращает True, если удалось запланировать отправку, False иначе.
    """
    p = _get_producer()
    if not p:
        logger.warning(f"KafkaProducer unavailable, dropping message to '{topic}': {data}")
        return False

    try:
        p.send(topic, data)
        p.flush()
        return True
    except KafkaError as e:
        logger.error(f"Failed to send to Kafka topic '{topic}': {e}")
        return False
