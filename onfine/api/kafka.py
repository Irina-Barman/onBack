import os
from typing import Any, Dict

from flask import jsonify
from flask_restx import Namespace, Resource
from kafka import KafkaAdminClient
from kafka.errors import KafkaError

kafka_ns = Namespace("kafka", description="Работоспособность кафки")
# err(kafka_ns)


@kafka_ns.route("/info")
class KafkaHealth(Resource):
    def get(self) -> Dict[str, Any]:
        """Test"""
        try:
            admin = KafkaAdminClient(
                bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP", "kafka:9092"),
                request_timeout_ms=5000,
            )
            admin.list_topics()
            return jsonify({"status": "healthy"}), 200
        except KafkaError as e:
            return jsonify({"status": "unhealthy", "error": str(e)}), 500
