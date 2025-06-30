import logging
import os
from decimal import Decimal
from typing import Any, Dict, List

from flask_jwt_extended import get_jwt_identity, jwt_required
from flask_restx import Namespace, Resource, fields
from sqlalchemy.exc import SQLAlchemyError

from onfine.models.user import User
from onfine.services import wallet_service as svc

from ..api.error_handlers import register_error_handlers as err

logger = logging.getLogger(__name__)

ns = Namespace("wallets", description="Кошельки, баланс, вывод")

err(ns)

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
        "destination": fields.String(required=True, example="0x… / TA… / bnb…"),
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
            logger.info(f"Кошельки созданы или были найдены в db для пользователя {user.id}: {result}")
            return result
        except SQLAlchemyError as e:
            logger.error(
                f"Ошибка базы данных при создании кошельков для пользователя {user.id}: {e}",
                exc_info=True,
            )
            raise err.WalletCreationError("Database error occurred.")
        except Exception as e:
            logger.error(
                f"Не удалось создать кошельки для пользователя {user.id}: {e}",
                exc_info=True,
            )
            raise err.WalletCreationError("Failed to create wallets.")


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
                raise err.WalletRetrievalError("Wallets not found.")
            logger.info(f"Адреса кошельков получены для пользователя {user.id}: {res}")
            return res
        except SQLAlchemyError as e:
            logger.error(
                f"Ошибка базы данных при получении адресов кошельков для пользователя {user.id}: {e}",
                exc_info=True,
            )
            raise err.WalletRetrievalError("Database error occurred.")
        except err.WalletRetrievalError as e:
            logger.warning(f"{e.message} для пользователя {user.id}")
            raise
        except Exception as e:
            logger.error(
                f"Не удалось получить адреса кошельков для пользователя {user.id}: {e}",
                exc_info=True,
            )
            raise err.WalletRetrievalError("Failed to get wallets.")


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
            if not fees:
                logger.warning("Комиссии за переводы не найдены.")
                return {}, 204
            logger.info(f"Запрошены комиссии за переводы: {fees}")
            return fees
        except SQLAlchemyError as e:
            logger.error(
                f"Произошла ошибка базы данных при получении комиссий за переводы: {e}",
                exc_info=True,
            )
            raise err.TransferFeeRetrievalError("Database error occurred.")
        except Exception as e:
            logger.error(f"Не удалось получить комиссии за переводы: {e}", exc_info=True)
            raise err.TransferFeeRetrievalError("Failed to get transfer fees.")


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
                f"Запрос на вывод средств от пользователя {user.id}:(network={data['network']}, "
                f"amount={data['amount']}, dest={data['destination']}, tx_id={tx.id}",
            )
            return {"status": tx.status.value, "transaction_id": tx.id}, 201
        except ValueError as e:
            logger.warning(f"Некорректный запрос на вывод средств от пользователя {user.id}: {e}")
            raise err.WithdrawError("Invalid request for withdrawal.")
        except SQLAlchemyError as e:
            logger.error(
                f"Ошибка базы данных при выводе средств для пользователя {user.id}: {e}",
                exc_info=True,
            )
            raise err.WithdrawError("Database error occurred.")
        except Exception as e:
            logger.error(
                f"Не удалось вывести средства для пользователя {user.id}: {e}",
                exc_info=True,
            )
            raise err.WithdrawError("Failed to withdraw funds.")


# ---------- /balance ----------
@ns.route("/balance")
class Balance(Resource):
    @jwt_required()
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
            # trc_balance = svc.get_real_balance(user, "trc")
            balances = {
                "bep_balance": str(bep_balance),
                "erc_balance": str(erc_balance),
                # "trc_balance": str(trc_balance),
            }
            logger.info(f"Баланс получен для пользователя {user.id}: {balances}")
            return balances
        except SQLAlchemyError as e:
            logger.error(
                f"Ошибка базы данных при получении баланса для пользователя {user.id}: {e}",
                exc_info=True,
            )
            raise err.BalanceError("Database error occurred.")
        except Exception as e:
            logger.error(
                f"Не удалось получить баланс для пользователя {user.id}: {e}",
                exc_info=True,
            )
            raise err.BalanceError("Failed to get balance.")


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
            logger.error(
                f"Ошибка при получении истории транзакций пользователя {user.id}: {e}",
                exc_info=True,
            )
            raise err.TransactionError("Failed to get transaction history.")


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
            logger.info(f"Баланс рефералов для пользователя {user.id}: {balance}")
            return {"balance": str(balance)}
        except Exception as e:
            logger.error(
                f"Ошибка при получении баланса рефералов пользователя {user.id}: {e}",
                exc_info=True,
            )
            raise err.ReferralError("Failed to get referral balance.")


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
            logger.warning(f"Неверный формат суммы вывода рефералов от пользователя {user.id}")
            ns.abort(400, "Invalid amount format")

        min_payout = Decimal(os.getenv("REF_MIN_PAYOUT", "10"))
        if amt < min_payout:
            logger.warning(f"Сумма вывода рефералов меньше минимальной у пользователя {user.id}: {amt} < {min_payout}")
            ns.abort(400, f"Amount below minimum payout {min_payout}")

        try:
            svc.ref_debit(user, amt)
            svc.debit(user, "erc", -amt)
            logger.info(f"Успешный вывод рефералов у пользователя {user.id}, сумма: {amt}")
        except ValueError as e:
            logger.warning(f"Ошибка вывода рефералов у пользователя {user.id}: {e}")
            ns.abort(400, str(e))
        except Exception as e:
            logger.error(
                f"Ошибка при выводе рефералов у пользователя {user.id}: {e}",
                exc_info=True,
            )
            raise err.ReferralError("Failed to withdraw referral funds.")

        return {"status": "ok"}
