from flask import Flask

from .api import register_namespaces
from .config import Config
from .extensions import db, jwt, migrate

# authorizations = {
#     'Bearer': {
#         'type': 'apiKey',
#         'in': 'header',
#         'name': 'Authorization',
#         'description': 'JWT Authorization header using the Bearer scheme. Example: "Bearer <token>"'
#     }
# }


def create_app() -> Flask:
    """Создает и настраивает экземпляр Flask приложения.

    Return:
        Flask: Настроенный экземпляр приложения Flask.
    """
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)

    register_namespaces(app)

    # Запуск WebSocket-листенеров после инициализации db

    from onfine.services.websocket_listener import start_websocket_listeners

    start_websocket_listeners(db.session)

    return app
