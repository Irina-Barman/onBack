import logging
import os
from decimal import Decimal
from typing import Any, Dict, List

from flask_jwt_extended import get_jwt_identity, jwt_required
from flask_restx import Namespace, Resource, fields

from onfine.models.user import User
from onfine.services import wallet_service as svc

from ..api.error_handlers import register_error_handlers

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

ns = Namespace("wallets", description="Кошельки, баланс, вывод")

register_error_handlers(ns)

# ----------- Swagger-модели ----------
err_model = ns.model(
    "Error",
    {
        "error": fields.String(description="Error code"),
        "message": fields.String(description="Error message"),
    },
)

_wallets = ns.model(
    "WalletList",
    {
        "bep": fields.String,
        "erc": fields.String,
        "trc": fields.String,
    },
)
_empty = ns.model("Empty", {})

_fee = ns.model(
    "Fee",
    {
        "bep": fields.String,
        "erc": fields.String,
        "trc": fields.String,
    },
)

_withdraw_in = ns.model(
    "WithdrawIn",
    {
        "network": fields.String(required=True, enum=["bep", "erc", "trc"]),
        "amount": fields.String(required=True, example="50.00"),
        "destination": fields.String(
            required=True, example="0x… / TA… / bnb…"
        ),
        "2fa_code": fields.String(required=True, example="123456"),
    },
)
_withdraw_out = ns.model(
    "WithdrawOut",
    {
        "status": fields.String,
        "transaction_id": fields.Integer,
    },
)

_balance_out = ns.model(
    "BalanceOut",
    {
        "bep_balance": fields.String,
        "erc_balance": fields.String,
        "trc_balance": fields.String,
    },
)

_tx = ns.model(
    "Tx",
    {
        "type": fields.String,
        "amount": fields.String,
        "network": fields.String,
        "status": fields.String,
        "timestamp": fields.DateTime(attribute="created_at"),
    },
)

_check_in = ns.model(
    "CheckWalletIn",
    {"wallet_address": fields.String(required=True)},
)
_check_out = ns.model("CheckWalletOut", {"status": fields.String})

_ref_bal = ns.model("RefBalance", {"balance": fields.String})
_ref_wd = ns.model(
    "RefWithdrawIn",
    {"amount": fields.String(required=True, example="25.00")},
)


# ---------- /create_wallet ----------
@ns.route("/create_wallet")
class WalletCreate(Resource):
    @jwt_required()
    @ns.expect(_empty)
    @ns.marshal_with(_wallets)
    def post(self) -> Dict[str, str]:
        """
        Создает новые кошельки для пользователя.

        Return:
            dict: Словарь с адресами созданных кошельков.
        """
        user = User.query.get(get_jwt_identity())
        try:
            result = svc.create_wallets(user)
            logger.info(f"Wallets created for user {user.id}: {result}")
            return result
        except Exception as e:
            logger.error(
                f"Failed to create wallets for user {user.id}: {e}",
                exc_info=True,
            )
            ns.abort(500, f"Failed to create wallets: {e}")


# ---------- /get_wallet ----------
@ns.route("/get_wallet")
class WalletGet(Resource):
    @jwt_required()
    @ns.expect(_empty)
    @ns.marshal_with(_wallets, skip_none=True)
    def post(self) -> Dict[str, Any]:
        """
        Получает адреса кошельков пользователя.

        Return:
            dict: Словарь с адресами кошельков или None, если они отсутствуют.
        """
        user = User.query.get(get_jwt_identity())
        try:
            res = svc.list_wallets(user)
            if not res:
                res = {"bep": None, "erc": None, "trc": None}
            logger.info(f"Wallets retrieved for user {user.id}: {res}")
            return res
        except Exception as e:
            logger.error(
                f"Failed to get wallets for user {user.id}: {e}", exc_info=True
            )
            ns.abort(500, f"Failed to get wallets: {e}")


# ---------- /transfer_fee ----------
@ns.route("/transfer_fee")
class TransferFee(Resource):
    @ns.marshal_with(_fee)
    def get(self) -> Dict[str, str]:
        """
        Получает информацию о комиссиях за переводы.

        Return:
            dict: Словарь с комиссиями для различных сетей.
        """
        try:
            fees = {k: str(v) for k, v in svc.transfer_fee_table().items()}
            logger.info(f"Transfer fees requested: {fees}")
            return fees
        except Exception as e:
            logger.error(f"Failed to get transfer fees: {e}", exc_info=True)
            ns.abort(500, f"Failed to get transfer fees: {e}")


# ---------- /withdraw ----------
@ns.route("/withdraw")
class Withdraw(Resource):
    @jwt_required()
    @ns.expect(_withdraw_in)
    @ns.marshal_with(_withdraw_out, code=201)
    def post(self) -> Dict[str, Any]:
        """
        Выводит средства с кошелька пользователя.

        Return:
            dict: Статус операции и ID транзакции.
        """
        user = User.query.get(get_jwt_identity())
        data = ns.payload
        try:
            tx = svc.withdraw_funds(
                user=user,
                network=data["network"],
                amount=Decimal(data["amount"]),
                dest=data["destination"],
                twofa_code=data["2fa_code"],
            )
            logger.info(
                f"Withdrawal requested by user {user.id}:"
                f"network={data['network']}, amount={data['amount']},"
                f"dest={data['destination']}, tx_id={tx.id}",
            )
        except ValueError as e:
            logger.warning(
                f"Invalid withdrawal request by user {user.id}: {e}"
            )
            ns.abort(400, str(e))
        except Exception as e:
            logger.error(
                f"Failed to withdraw funds for user {user.id}: {e}",
                exc_info=True,
            )
            ns.abort(500, f"Failed to withdraw funds: {e}")
        return {"status": tx.status.value, "transaction_id": tx.id}, 201


# ---------- /balance ----------
@ns.route("/balance")
class Balance(Resource):
    @jwt_required()
    @ns.expect(_empty)
    @ns.marshal_with(_balance_out)
    def get(self) -> Dict[str, str]:
        """
        Получает баланс пользователя по всем сетям.

        Return:
            dict: Словарь с балансами для различных сетей.
        """
        user = User.query.get(get_jwt_identity())
        try:
            bep_balance = svc.get_real_balance(user, "bep")
            erc_balance = svc.get_real_balance(user, "erc")
            trc_balance = svc.get_real_balance(user, "trc")
            balances = {
                "bep_balance": str(bep_balance),
                "erc_balance": str(erc_balance),
                "trc_balance": str(trc_balance),
            }
            logger.info(f"Balances retrieved for user {user.id}: {balances}")
            return balances
        except Exception as e:
            logger.error(
                f"Failed to get balance for user {user.id}: {e}", exc_info=True
            )
            ns.abort(500, f"Failed to get balance: {e}")


# ---------- /transactions ----------
@ns.route("/transactions")
class Transactions(Resource):
    @jwt_required()
    @ns.expect(_empty)
    @ns.marshal_list_with(_tx)
    def get(self) -> List[Dict[str, Any]]:
        """
        Получает историю транзакций пользователя.

        Return:
            list: Список транзакций пользователя.
        """
        user = User.query.get(get_jwt_identity())
        try:
            return svc.history(user)
        except Exception as e:
            ns.abort(500, f"Failed to get transaction history: {e}")


# ---------- /check_wallet ----------
@ns.route("/check_wallet")
class CheckWallet(Resource):
    @ns.expect(_check_in)
    @ns.marshal_with(_check_out)
    def post(self) -> Dict[str, str]:
        """
        Проверяет безопасность кошелька.

        Return:
            dict: Статус проверки кошелька.
        """
        # Можно добавить реальную проверку, если нужно
        wallet_address = ns.payload.get("wallet_address")
        logger.info(f"Wallet check requested for address: {wallet_address}")
        return {"status": "safe"}


# ---------- /referral_balance ----------
@ns.route("/referral_balance")
class RefBal(Resource):
    @jwt_required()
    @ns.marshal_with(_ref_bal)
    def get(self) -> Dict[str, str]:
        """
        Получает баланс реферальной программы пользователя.

        Return:
            dict: Словарь с реферальным балансом.
        """
        user = User.query.get(get_jwt_identity())
        try:
            balance = svc.ref_balance(user)
            logger.info(
                f"Referral balance retrieved for user {user.id}: {balance}"
            )
            return {"balance": str(balance)}
        except Exception as e:
            logger.error(
                f"Failed to get referral balance for user {user.id}: {e}",
                exc_info=True,
            )
            ns.abort(500, f"Failed to get referral balance: {e}")


# ---------- /referral_withdraw ----------
@ns.route("/referral_withdraw")
class RefWithdraw(Resource):
    @jwt_required()
    @ns.expect(_ref_wd)
    def post(self) -> Dict[str, str]:
        """
        Выводит средства из реферального баланса пользователя.

        Return:
            dict: Статус операции.
        """
        user = User.query.get(get_jwt_identity())
        try:
            amt = Decimal(ns.payload["amount"])
        except Exception:
            logger.warning(
                f"Invalid referral withdraw amount format by user {user.id}"
            )
            ns.abort(400, "Invalid amount format")
        min_payout = Decimal(os.getenv("REF_MIN_PAYOUT", "10"))
        if amt < min_payout:
            logger.warning(
                f"Referral withdraw amount below minimum by user {user.id}: {amt} < {min_payout}"
            )
            ns.abort(400, f"Amount below minimum payout {min_payout}")
        try:
            svc.ref_debit(user, amt)
            svc.debit(user, "erc", -amt)
            logger.info(
                f"Referral withdraw successful for user {user.id}, amount: {amt}"
            )
        except ValueError as e:
            logger.warning(f"Referral withdraw failed for user {user.id}: {e}")
            ns.abort(400, str(e))
        except Exception as e:
            logger.error(
                f"Failed to withdraw referral funds for user {user.id}: {e}",
                exc_info=True,
            )
            ns.abort(500, f"Failed to withdraw referral funds: {e}")
        return {"status": "ok"}
