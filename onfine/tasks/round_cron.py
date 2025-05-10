from onfine.app_factory import create_app
from onfine.models.funding_round import FundingRound, RoundState
from onfine.services.pool_income import distribute_round, fetch_pool_income

app = create_app()
with app.app_context():
    fetch_pool_income()  # записываем дневной доход
    for r in FundingRound.query.filter_by(state=RoundState.MINING).all():
        distribute_round(r.id)  # делим средства внутри раунда


# docker compose exec api python -m onfine.tasks.round_cron
