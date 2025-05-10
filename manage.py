#!/usr/bin/env python
from flask.cli import with_appcontext
from flask_migrate import init, migrate, upgrade

from onfine.app_factory import create_app  # функция для создания приложения

app = create_app()


@app.cli.command("db-init")
@with_appcontext
def db_init() -> None:
    """Инициализация базы данных, создание миграций и обновление базы данных.

    Эта команда выполняет инициализацию базы данных, создает начальные миграции
    и обновляет базу данных до последней версии.
    """
    init()
    migrate(message="initial")
    upgrade()


@app.cli.command("db-migrate")
@with_appcontext
def db_migrate() -> None:
    """Создание миграций базы данных.

    Эта команда автоматически создает миграции
    для изменений в модели базы данных.
    """
    migrate(auto=True)


@app.cli.command("db-upgrade")
@with_appcontext
def db_upgrade() -> None:
    """Обновление базы данных до последней версии.

    Эта команда применяет все непримененные миграции к базе данных.
    """
    upgrade()
