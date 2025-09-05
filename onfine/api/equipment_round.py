from decimal import Decimal
from typing import Any, Dict, List

from flask import request
from flask_jwt_extended import get_jwt_identity, jwt_required
from flask_restx import Namespace, Resource, fields

from onfine.models.funding_round import FundingRound
from onfine.models.user import User
from onfine.services.round_invest import invest

ns = Namespace("rounds", description="Фанд-раунды майнинга")

_round = ns.model(
    "Round",
    {
        "id": fields.Integer(required=True, description="ID фанд-раунда"),
        "cap_usdt": fields.String(required=True, description="Кап фанд-раунда в USDT"),
        "collected_usdt": fields.String(required=True, description="Собранная сумма в USDT"),
        "state": fields.String(required=True, description="Статус раунда"),
    },
)

_inv = ns.model(
    "InvestIn",
    {"amount": fields.String(
        required=True, description="Сумма инвестиций в USDT")},
)


@ns.route("/")
class RoundList(Resource):
    @ns.marshal_list_with(_round)
    def get(self) -> List[FundingRound]:
        """
        Получает список всех фанд-раундов.

        Returns:
            List[FundingRound]: Список объектов фанд-раундов.

        Example request:
        curl -X GET "http://127.0.0.1:5500/api/rounds/" \
            -H "Accept: application/json"

        """
        return FundingRound.query.all()


@ns.route("/invest")
class RoundInvest(Resource):
    @jwt_required()
    @ns.expect(_inv)
    def post(self) -> Dict[str, Any]:
        """
        Инвестирует в фанд-раунд от имени текущего пользователя.

        Ожидает JSON с полем:
            - amount: сумма инвестиций в USDT (строка, например "100.00")

        Returns:
            Dict[str, Any]: Словарь с ID раунда и суммой инвестиций.
        """
        payload = request.json
        amount_str = payload.get("amount")
        user = User.query.get(get_jwt_identity())
        inv = invest(user, Decimal(amount_str))
        return {"round_id": inv.round_id, "net_amount": str(inv.amount)}, 201
