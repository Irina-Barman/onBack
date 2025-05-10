from flask import Blueprint, Flask
from flask_restx import Api

from .auth import auth_ns
from .emcd import ns as emcd_ns
from .equipment import ns as equipment_ns
from .package import ns as package_ns
from .wallet import ns as wallet_ns


def register_namespaces(app: Flask) -> None:
    """Регистрирует пространства имен API в приложении Flask.

    Эта функция создает новый Blueprint для API и добавляет в него
    пространства имен для аутентификации, пакетов, кошельков, оборудования
    и EMCD. Затем Blueprint регистрируется в приложении Flask.

    Аргументы:
        app (Flask): Экземпляр приложения Flask,
        в котором регистрируются пространства имен.

    Возвращает:
        None
    """
    bp = Blueprint("api", __name__, url_prefix="/api")
    api = Api(bp, title="Onfine API", version="1.0", doc="/docs")
    api.add_namespace(auth_ns)
    api.add_namespace(package_ns)
    api.add_namespace(wallet_ns)
    api.add_namespace(emcd_ns, path="/emcd")
    api.add_namespace(equipment_ns, path="/equipment")
    app.register_blueprint(bp)
