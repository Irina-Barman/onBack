#!/usr/bin/env python
import click
from flask_migrate import init, migrate, upgrade
import click
from flask.cli import with_appcontext
from onfine.app_factory import create_app           # ← тут

app = create_app()

@app.cli.command("db-init")
@with_appcontext
def db_init():
    init()
    migrate(message="initial")
    upgrade()

@app.cli.command("db-migrate")
@with_appcontext
def db_migrate():
    migrate(auto=True)

@app.cli.command("db-upgrade")
@with_appcontext
def db_upgrade():
    upgrade()
