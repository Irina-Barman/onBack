from decimal import Decimal
from flask_restx import Namespace, Resource, fields
from flask_jwt_extended import jwt_required, get_jwt_identity
from onfine.services.round_invest import invest
from onfine.models.funding_round import FundingRound, RoundState
from onfine.models.user import User

ns = Namespace("rounds", description="Фанд-раунды майнинга")

_round = ns.model("Round", {
    "id": fields.Integer, "cap_usdt": fields.String,
    "collected_usdt": fields.String, "state": fields.String
})
_inv = ns.model("InvestIn", {"amount": fields.String(required=True)})

@ns.route("/")
class RoundList(Resource):
    @ns.marshal_list_with(_round)
    def get(self):
        return FundingRound.query.all()

@ns.route("/invest")
class RoundInvest(Resource):
    @jwt_required()
    @ns.expect(_inv)
    def post(self):
        user=User.query.get(get_jwt_identity())
        inv=invest(user, Decimal(ns.payload["amount"]))
        return {"round_id": inv.round_id, "net_amount": str(inv.amount)}, 201
