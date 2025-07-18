from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List

from flask import request
from flask_jwt_extended import get_jwt_identity, jwt_required
from flask_restx import Namespace, Resource, fields

from onfine.models.user import User
from onfine.services import invest_service as isvc
from onfine.services import profit_service as psvc

ns = Namespace("equipment", description="Майнинг-оборудование и инвестиции")

_eq = ns.model(
    "Equipment",
    {
        "id": fields.Integer(description="ID оборудования"),
        "name": fields.String(description="Название оборудования"),
        "cost_usdt": fields.String(description="Стоимость в USDT"),
        "opex_pct": fields.String(description="Операционные расходы в %"),
    },
)

_inv_in = ns.model(
    "InvestIn",
    {
        "equipment_id": fields.Integer(required=True, description="ID оборудования"),
        "amount": fields.String(required=True, description="Сумма инвестиций в USDT"),
    },
)

_batch_in = ns.model(
    "BatchIn",
    {
        "equipment_id": fields.Integer(required=True, description="ID оборудования"),
        "mined_usdt": fields.String(required=True, description="Сумма добытого в USDT"),
        "period_start": fields.DateTime(required=True, description="Начало периода"),
        "period_end": fields.DateTime(required=True, description="Конец периода"),
    },
)


@ns.route("/")
class EqList(Resource):
    @ns.marshal_with(ns.model("EquipmentListResponse", {
        "items": fields.List(fields.Nested(_eq), description="Список оборудования")
    }))
    def get(self) -> Dict[str, List[Any]]:
        """
        Получает список доступного майнинг-оборудования.

        Returns:
            dict: Словарь с ключом "items", содержащим список оборудования.
        """
        from onfine.models.mining_equipment import MiningEquipment

        equipment_list = MiningEquipment.query.all()
        return {"items": equipment_list}


@ns.route("/invest")
class Invest(Resource):
    @jwt_required()
    @ns.expect(_inv_in)
    def post(self) -> Dict[str, str]:
        """
        Создает инвестицию в оборудование.

        Ожидает JSON с полями:
            - equipment_id: ID оборудования
            - amount: сумма инвестиций в USDT

        Returns:
            dict: Статус операции.
        """
        data = request.json
        user = User.query.get(get_jwt_identity())
        isvc.invest(user, data["equipment_id"], Decimal(data["amount"]))
        return {"status": "ok"}


@ns.route("/batch")
class Batch(Resource):
    @ns.expect(_batch_in)  # В реальном коде — ограничить доступ только админам
    def post(self) -> Dict[str, int]:
        """
        Записывает данные о полученном оборудовании.

        Ожидает JSON с полями:
            - equipment_id: ID оборудования
            - mined_usdt: сумма добытого в USDT
            - period_start: начало периода (ISO 8601)
            - period_end: конец периода (ISO 8601)

        Returns:
            dict: Словарь с ID созданной партии.
        """
        data = request.json
        batch = psvc.record_mined(
            data["equipment_id"],
            Decimal(data["mined_usdt"]),
            datetime.fromisoformat(data["period_start"]),
            datetime.fromisoformat(data["period_end"]),
        )
        psvc.distribute_batch(batch.id)
        return {"batch_id": batch.id}
