from flask import Flask

from .api import register_namespaces
from .config import Config
from .extensions import db, jwt, migrate


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
    return app
