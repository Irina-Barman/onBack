from flask import Flask
from .config import Config
from .extensions import db, migrate, jwt
from .api import register_namespaces


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)

    register_namespaces(app)
    return app
