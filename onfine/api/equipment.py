from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List

from flask_jwt_extended import get_jwt_identity, jwt_required
from flask_restx import Namespace, Resource, fields

from onfine.models.user import User
from onfine.services import invest_service as isvc
from onfine.services import profit_service as psvc

ns = Namespace("equipment", description="Майнинг-оборудование и инвестиции")

_eq = ns.model(
    "Equipment",
    {
        "id": fields.Integer,
        "name": fields.String,
        "cost_usdt": fields.String,
        "opex_pct": fields.String,
    },
)
_inv_in = ns.model(
    "InvestIn",
    {
        "equipment_id": fields.Integer(required=True),
        "amount": fields.String(required=True),
    },
)
_batch_in = ns.model(
    "BatchIn",
    {
        "equipment_id": fields.Integer(required=True),
        "mined_usdt": fields.String(required=True),
        "period_start": fields.DateTime(required=True),
        "period_end": fields.DateTime(required=True),
    },
)


@ns.route("/")
class EqList(Resource):
    @ns.marshal_list_with(_eq)
    def get(self) -> List[Dict[str, Any]]:
        """Получает список доступного майнинг-оборудования.

        Return:
            list: Список объектов оборудования.
        """
        from onfine.models.mining_equipment import MiningEquipment

        return MiningEquipment.query.all()


@ns.route("/invest")
class Invest(Resource):
    @jwt_required()
    @ns.expect(_inv_in)
    def post(self) -> Dict[str, str]:
        """Создает инвестицию в оборудование.

        Return:
            dict: Статус операции.
        """
        user = User.query.get(get_jwt_identity())
        d = ns.payload
        isvc.invest(user, d["equipment_id"], Decimal(d["amount"]))
        return {"status": "ok"}


@ns.route("/batch")
class Batch(Resource):
    @ns.expect(_batch_in)  # ← допускаем только админов в реальном коде
    def post(self) -> Dict[str, int]:
        """Записывает данные о полученом оборудовании.

        Return:
            dict: ID созданной партии.
        """
        d = ns.payload
        b = psvc.record_mined(
            d["equipment_id"],
            Decimal(d["mined_usdt"]),
            datetime.fromisoformat(d["period_start"]),
            datetime.fromisoformat(d["period_end"]),
        )
        psvc.distribute_batch(b.id)
        return {"batch_id": b.id}
