import logging
from typing import Any, Dict, List

from flask import request
from flask_jwt_extended import (
    get_jwt_identity,
    jwt_required,
    verify_jwt_in_request,
)
from flask_restx import Namespace, Resource, fields

from onfine.models.user import User
from onfine.services import package_service as svc

from ..api.error_handlers import register_error_handlers as err

ns = Namespace("packages", description="Каталог пакетов и покупки")
err(ns)

logger = logging.getLogger(__name__)


# ---------- swagger models ----------

_pkg = ns.model(
    "Package",
    {
        "id": fields.Integer,
        "name": fields.String,
        "type": fields.String,
        "price_usdt": fields.String,
        "description": fields.String,
        "popular": fields.Boolean(description="Флаг популярного пакета"),
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
    {  # тело запроса для покупки
        "package_id": fields.Integer(required=True, description="ID пакета для покупки"),
        "network": fields.String(
            required=True,
            enum=["bep", "erc", "trc"],
            description="Сеть для оплаты",
        ),
    },
)

_buy_out = ns.model(
    "PurchaseOut",
    {  # тело ответа после создания/получения покупки
        "purchase_id": fields.Integer(description="ID покупки"),
        "status": fields.String(description="Статус покупки"),
        "summ": fields.String(description="Сумма в USDT"),
        "gas": fields.String(description="Стоимость газа в USDT"),
        "from_database": fields.Boolean(description="Флаг, указывающий, что покупка взята из базы"),
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
        "purchase_id": fields.Integer(description="ID покупки"),
        "status": fields.String(description="Статус покупки после подтверждения"),
    },
)

_package_list_model = ns.model(
    "PackageList",
    {
        "items": fields.List(fields.Nested(_pkg), description="Список пакетов"),
    },
)


# ---------- /packages ----------
@ns.route("/")
class PackageList(Resource):
    @ns.marshal_with(_package_list_model)
    def get(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Получает список доступных пакетов.

        Если передан валидный JWT токен — возвращает пакеты со стоимостью.
        Если токен отсутствует или недействителен — возвращает пакеты без стоимости.

        Example request:
            curl -X GET "http://127.0.0.1:5500/api/packages/" \
                -H "Accept: application/json"

            curl -X GET "http://127.0.0.1:5500/api/packages/" \
                -H "Accept: application/json" \
                -H "Authorization: Bearer <your_jwt_token>"

        """
        try:
            # Попытка проверить токен без обязательного требования
            verify_jwt_in_request(optional=True)
            user_id = get_jwt_identity()
            if user_id is not None:
                # Есть валидный токен — возвращаем полные данные
                packages = svc.list_packages()
            else:
                # Токена нет, возвращаем без цены
                packages = svc.list_packages_no_price()
        except Exception:
            # Ошибка валидации токена — считаем, что токена нет
            packages = svc.list_packages_no_price()

        return {"items": packages}


# ---------- /purchases ----------
@ns.route("/purchases")
class Purchase(Resource):
    @jwt_required()
    @ns.expect(_buy_in)
    @ns.marshal_with(_buy_out, code=201)
    def post(self) -> tuple[Dict[str, Any], int]:
        """
        Создает или возвращает ожидающую покупку пакета.

        Получает данные из тела запроса (JSON) с package_id и network.

        Returns:
            tuple: Кортеж из словаря с информацией о покупке и HTTP-кода 201.
        """
        user = User.query.get(get_jwt_identity())
        data: Dict[str, Any] = request.json  # безопасный доступ к телу запроса

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
            "from_database": from_database,
        }, 201


# ---------- /purchases/<id>/confirm ----------
@ns.route("/purchases/<int:purchase_id>/confirm")
class PurchaseConfirm(Resource):
    @jwt_required()
    @ns.expect(_confirm_in)
    @ns.marshal_with(_confirm_out)
    def post(self, purchase_id: int) -> Dict[str, Any]:
        """
        Подтверждает оплату (или отменяет).

        Args:
            purchase_id (int): ID покупки для подтверждения.

        Returns:
            dict: Информация о подтвержденной покупке, включая ID и статус.
        """
        data: Dict[str, Any] = request.json
        success: bool = data["success"]

        try:
            p = svc.process_purchase_confirmation(purchase_id, success)
            return {"purchase_id": p.id, "status": p.status.value}
        except ValueError as e:
            # Обработка ошибок валидации (не найдена покупка или неверный статус)
            ns.abort(400, str(e))
        except Exception as e:
            # Обработка других исключений (например, ошибки базы данных или email)
            logger.error(f"Ошибка при подтверждении покупки {purchase_id}: {e}")
            ns.abort(500, "Internal server error")
