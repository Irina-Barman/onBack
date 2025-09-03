import logging
import os
from decimal import Decimal
from typing import Dict

from flask_jwt_extended import get_jwt_identity, jwt_required
from flask_restx import Namespace, Resource, fields

from onfine.models.user import User
from onfine.services import cashback_service as svc

from ..api.error_handlers import (
    ReferralError,
    register_error_handlers,
)

logger = logging.getLogger(__name__)

# Создаём пространство имён API для кошельков с описанием
ns = Namespace("cashback", description="Кэшбэк и выплаты")

# Регистрируем обработчики ошибок для данного namespace
register_error_handlers(ns)


err_model = ns.model(
    "Error",
    {
        "error": fields.String(description="Код ошибки"),
        "message": fields.String(description="Сообщение об ошибке"),
    },
)

# Модель баланса рефералов
_ref_bal = ns.model(
    "RefBalance", {"balance": fields.String(description="Баланс рефералов")})

# Модель запроса на вывод с реферального баланса
_ref_wd = ns.model(
    "RefWithdrawIn",
    {
        "amount": fields.String(
            required=True,
            example="25.00",
            description="Сумма вывода реферальных средств",
        ),
    },
)


@ns.route("/referral-balance")
class RefBal(Resource):
    """
    Получение баланса реферальных начислений пользователя.
    """

    @jwt_required()
    @ns.marshal_with(_ref_bal)
    def get(self) -> Dict[str, str]:
        """
        Получить баланс реферальных начислений текущего пользователя.

        Returns:
            dict: Словарь с ключом "balance" и значением в виде строки.

        Raises:
            ReferralError: Если не удалось получить баланс.

        Example request:
            curl -X GET "http://127.0.0.1:5500/api/cashback/referral-balance" \
                -H "Authorization: Bearer <your_jwt_token>" \
                -H "Accept: application/json"

        """
        user = User.query.get(get_jwt_identity())
        try:
            balance = svc.ref_balance(user)
            logger.info(f"Referral balance for user {user.id}: {balance}")
            return {"balance": str(balance)}
        except Exception as e:
            logger.error(
                f"Error getting referral balance for user {user.id}: {e}",
                exc_info=True,
            )
            raise ReferralError("Failed to get referral balance.")


@ns.route("/referral-withdraw")
class RefWithdraw(Resource):
    """
    Вывод средств с реферального баланса.
    """

    @jwt_required()
    @ns.expect(_ref_wd)
    def post(self) -> Dict[str, str]:
        """
        Вывести средства с реферального баланса текущего пользователя.

        Returns:
            Dict[str, str]: Статус операции.

        Raises:
            400: При неверном формате суммы или если сумма ниже минимального порога.
            ReferralError: При ошибках списания средств.
        """
        user = User.query.get(get_jwt_identity())
        try:
            amt = Decimal(ns.payload["amount"])
        except Exception:
            logger.warning(
                f"Invalid referral withdraw amount format from user {user.id}")
            ns.abort(400, "Invalid amount format")

        min_payout = Decimal(os.getenv("REF_MIN_PAYOUT", "10"))
        if amt < min_payout:
            logger.warning(
                f"Referral withdraw amount below minimum for user {user.id}: {amt} < {min_payout}")
            ns.abort(400, f"Amount below minimum payout {min_payout}")

        try:
            svc.ref_debit(user, amt)
            # При списании с основного баланса используем сеть ethereum, например
            svc.debit(user, "ethereum", -amt)
            logger.info(
                f"Successful referral withdraw for user {user.id}, amount: {amt}")
        except ValueError as e:
            logger.warning(f"Referral withdraw error for user {user.id}: {e}")
            ns.abort(400, str(e))
        except Exception as e:
            logger.error(
                f"Error during referral withdraw for user {user.id}: {e}",
                exc_info=True,
            )
            raise ReferralError("Failed to withdraw referral funds.")

        return {"status": "ok"}
