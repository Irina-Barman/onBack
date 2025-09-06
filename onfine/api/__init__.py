import logging

from flask import Blueprint, Flask
from flask_restx import Api

from .auth import auth_ns
from .cashback import ns as cashback_ns
from .emcd import ns as emcd_ns
from .equipment import ns as equipment_ns
from .kafka import kafka_ns
from .package import ns as package_ns
from .token import ns as token_ns
from .twofa import ns as twofa_ns
from .user import user_ns
from .wallet import ns as wallet_ns

logging.getLogger("pkg_resources").setLevel(logging.WARNING)

# 🔐 Swagger поддержка JWT токена
authorizations = {
    "Bearer": {
        "type": "apiKey",
        "in": "header",
        "name": "Authorization",
        "description": 'JWT Authorization header using the Bearer scheme. Example: "Bearer <token>"',
    },
}


def register_namespaces(app: Flask) -> None:  # noqa D103
    bp = Blueprint("api", __name__, url_prefix="/api")

    api = Api(
        bp,
        title="Onfine API",
        version="1.0",
        doc="/docs",
        authorizations=authorizations,
        security="Bearer",  # 🔐 По умолчанию все эндпоинты требуют токен
    )

    api.add_namespace(auth_ns)
    api.add_namespace(twofa_ns, path="/auth/2fa")
    api.add_namespace(package_ns)
    api.add_namespace(wallet_ns)
    api.add_namespace(emcd_ns, path="/emcd")
    api.add_namespace(equipment_ns, path="/equipment")
    api.add_namespace(kafka_ns)
    api.add_namespace(user_ns)
    api.add_namespace(token_ns, path="/tokens")
    api.add_namespace(cashback_ns, path="/cashback")

    app.register_blueprint(bp)
