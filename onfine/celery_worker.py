from .app_factory import create_app

flask_app = create_app()
celery = flask_app.celery


# -------- ЗАДАЧИ ---------- #
@celery.task(name="tasks.distribute_profit")
def distribute_profit(pool_income: float, pool_expenses: float) -> None:
    """
    Считает чистую прибыль пула, удерживает комиссию платформы
    и создаёт бухгалтерские проводки.

    Args:
        pool_income (float): Доход пула.
        pool_expenses (float): Расходы пула.
    """
    """
    Считает чистую прибыль пула, удерживает комиссию платформы
    и создаёт бухгалтерские проводки.
    """
    from decimal import Decimal  # импорт внутри, чтобы celery picklable

    from .extensions import db
    from .models.referral import create_referral_operations
    from .models.transactions import Transaction

    platform_fee = (Decimal(pool_income) - Decimal(pool_expenses)) * flask_app.config["PLATFORM_FEE_PERCENT"]
    distributable = Decimal(pool_income) - Decimal(pool_expenses) - platform_fee

    # пример проводки
    tx = Transaction(
        type="profit_distribution",
        amount=distributable,
        meta={
            "pool_income": pool_income,
            "pool_expenses": pool_expenses,
            "fee": str(platform_fee),
        },
    )
    db.session.add(tx)
    db.session.commit()

    # дальше логика распределения по пайам / рефералке
    create_referral_operations(distributable)
