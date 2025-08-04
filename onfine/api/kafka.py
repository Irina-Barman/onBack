import os

from flask_restx import Namespace, Resource
from kafka import KafkaAdminClient
from kafka.errors import KafkaError

kafka_ns = Namespace("kafka", description="Работоспособность кафки")


@kafka_ns.route("/info")
class KafkaHealth(Resource):
    def get(self) -> dict:
        """
        Проверка работоспособности Kafka.
        GET-запрос без тела.
        Возвращает JSON-объект со статусом.
        """
        try:
            admin = KafkaAdminClient(
                bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP", "kafka:9092"),
                request_timeout_ms=5000,
            )
            admin.list_topics()
            return {"status": "healthy"}, 200
        except KafkaError as e:
            return {"status": "unhealthy", "error": str(e)}, 500
