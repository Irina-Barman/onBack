from typing import Any, Dict, List

from flask_jwt_extended import get_jwt_identity, jwt_required
from flask_restx import Namespace, Resource, fields

from onfine.models.user import User
from onfine.services import package_service as svc

from ..api.error_handlers import register_error_handlers as err

ns = Namespace("packages", description="Каталог пакетов и покупки")
err(ns)

# ---------- swagger models ----------
_pkg = ns.model(
    "Package",
    {
        "id": fields.Integer,
        "name": fields.String,
        "type": fields.String,
        "price_usdt": fields.String,
        "description": fields.String,
        # Добавляем поля из PackageProperty
        "term_months": fields.Integer,
        "interest_rate_from": fields.String,
        "interest_rate_to": fields.String,
        "bonuses": fields.String,
        "target_audience": fields.String,
    },
)

_gas = ns.model(
    "Gas",
    {"bep": fields.String, "erc": fields.String, "trc": fields.String},
)

_buy_in = ns.model(
    "BuyIn",
    {  # тело запроса
        "package_id": fields.Integer(required=True),
        "network": fields.String(required=True, enum=["bep", "erc", "trc"]),
    },
)

_buy_out = ns.model(
    "PurchaseOut",
    {  # тело ответа
        "purchase_id": fields.Integer,
        "status": fields.String,
        "summ": fields.String,
        "gas": fields.String,
        "from_database": fields.Boolean,  # возвращаем флаг
    },
)

_confirm_in = ns.model(
    "ConfirmIn",
    {
        "success": fields.Boolean(
            required=True,
            description="true — оплата прошла, false — отмена.",
        ),
    },
)

_confirm_out = ns.model(
    "ConfirmOut",
    {
        "purchase_id": fields.Integer,
        "status": fields.String,
    },
)


# ---------- /packages ----------
@ns.route("/")
class PackageList(Resource):
    @ns.marshal_list_with(_pkg)
    def get(self) -> List[Dict[str, Any]]:
        """Получает список доступных пакетов.

        Return:
            list: Список объектов пакетов.
        """
        return svc.list_packages()


# ---------- /packages/gas ----------
@ns.route("/gas")
class Gas(Resource):
    @ns.marshal_with(_gas)
    def get(self) -> Dict[str, str]:
        """Получает информацию о газовых сетях.

        Return:
            dict: Словарь с информацией о газовых сетях.
        """
        return {k: str(v) for k, v in svc.gas_table().items()}


# ---------- /purchases ----------
@ns.route("/purchases")
class Purchase(Resource):
    @jwt_required()
    @ns.expect(_buy_in)  # показывает body в Swagger
    @ns.marshal_with(_buy_out, code=201)
    def post(self) -> Dict[str, Any]:
        """Создает или возвращает ожидающую покупку пакета.

        Return:
            dict: Информация о покупке, включая ID, статус, сумму и газ.
        """
        user = User.query.get(get_jwt_identity())
        data = ns.payload

        # Проверяем наличие существующей покупки с статусом 'pending'
        purchase_result = svc.check_or_create_purchase(
            user,
            package_id=data["package_id"],
            network=data["network"],
        )

        p = purchase_result["purchase"]
        from_database = purchase_result["from_database"]

        return {
            "purchase_id": p.id,
            "status": p.status.value,
            "summ": str(p.amount_usdt),
            "gas": str(p.gas_usdt),
            "from_database": from_database,  # флаг, откуда получены данные
        }, 201


# ---------- /purchases/<id>/confirm ----------
@ns.route("/purchases/<int:purchase_id>/confirm")
class PurchaseConfirm(Resource):
    @jwt_required()
    @ns.expect(_confirm_in)
    @ns.marshal_with(_confirm_out)
    def post(self, purchase_id: int) -> Dict[str, Any]:
        """Подтверждает оплату (или отменяет).

        Аргументы:
            purchase_id (int): ID покупки для подтверждения.

        Return:
            dict: Информация о подтвержденной покупке, включая ID и статус.
        """
        success = ns.payload["success"]
        p = svc.process_purchase_confirmation(purchase_id, success)
        return {"purchase_id": p.id, "status": p.status.value}
