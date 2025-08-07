from flask import Flask

from logging_config import setup_logging

from .api import register_namespaces
from .config import Config
from .extensions import db, jwt, migrate

setup_logging()

# def is_running_in_docker() -> bool:
#     """Проверка: запущено ли приложение внутри Docker."""
#     if os.getenv("DOCKER_ENV") == "1":
#         return True

#     try:
#         with open("/proc/1/cgroup", "rt") as f:  # noqa PTH123
#             return "docker" in f.read() or "kubepods" in f.read()
#     except FileNotFoundError:
#         return False


# env_file_name = ".env" if is_running_in_docker() else ".env.local"
# dotenv_path = Path(__file__).resolve().parents[1] / env_file_name
# load_dotenv(dotenv_path=dotenv_path, override=True)

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

    # Это запускает сокет на получение данных в рантайме на ноде (но не потянем на бабкам пока что)
    # # Запуск WebSocket-листенеров после инициализации db
    # from onfine.services.websocket_listener import start_websocket_listeners
    # start_websocket_listeners(app, db.session)

    return app
