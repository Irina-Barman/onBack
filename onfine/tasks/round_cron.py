from onfine.app_factory import create_app
from onfine.services.pool_income import fetch_pool_income, distribute_round
from onfine.models.funding_round import FundingRound, RoundState

app = create_app()
with app.app_context():
    fetch_pool_income()              # записываем дневной доход
    for r in FundingRound.query.filter_by(state=RoundState.MINING).all():
        distribute_round(r.id)       # делим средства внутри раунда


#docker compose exec api python -m onfine.tasks.round_cron
