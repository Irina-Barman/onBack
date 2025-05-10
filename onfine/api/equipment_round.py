from decimal import Decimal
from typing import Any, Dict

from flask_jwt_extended import get_jwt_identity, jwt_required
from flask_restx import Namespace, Resource, fields

from onfine.models.funding_round import FundingRound
from onfine.models.user import User
from onfine.services.round_invest import invest

ns = Namespace("rounds", description="Фанд-раунды майнинга")

_round = ns.model(
    "Round",
    {
        "id": fields.Integer,
        "cap_usdt": fields.String,
        "collected_usdt": fields.String,
        "state": fields.String,
    },
)
_inv = ns.model("InvestIn", {"amount": fields.String(required=True)})


@ns.route("/")
class RoundList(Resource):
    @ns.marshal_list_with(_round)
    def post(self) -> Dict[str, Any]:
        """Инвестирует в фанд-раунд от имени текущего пользователя.

        Returns:
            Dict[str, Any]: Словарь с ID раунда и суммой инвестиций.
        """
        """Получает список всех фанд-раундов.

        Returns:
            List[Dict[str, Any]]: Список фанд-раундов.
        """
        return FundingRound.query.all()


@ns.route("/invest")
class RoundInvest(Resource):
    @jwt_required()
    @ns.expect(_inv)
    def post(self) -> Dict[str, Any]:
        """Инвестирует в фанд-раунд от имени текущего пользователя.

        Returns:
            Dict[str, Any]: Словарь с ID раунда и суммой инвестиций.
        """
        user = User.query.get(get_jwt_identity())
        inv = invest(user, Decimal(ns.payload["amount"]))
        return {"round_id": inv.round_id, "net_amount": str(inv.amount)}, 201
