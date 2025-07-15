import logging
import os
from decimal import Decimal
from typing import Any, Dict, List

from flask_jwt_extended import get_jwt_identity, jwt_required
from flask_restx import Namespace, Resource, fields
from sqlalchemy.exc import SQLAlchemyError

from onfine.models.user import User
from onfine.services import wallet_service as svc

from ..api.error_handlers import (
    BalanceError,
    ReferralError,
    TransactionError,
    TransferFeeRetrievalError,
    WalletCreationError,
    WalletRetrievalError,
    WithdrawError,
    register_error_handlers,
)

logger = logging.getLogger(__name__)

# Создаём пространство имён API для кошельков с описанием
ns = Namespace("wallets", description="Кошельки, баланс, вывод")

# Регистрируем обработчики ошибок для данного namespace
register_error_handlers(ns)

# ----------- Swagger-модели для документации API ----------

err_model = ns.model(
    "Error",
    {
        "error": fields.String(description="Код ошибки"),
        "message": fields.String(description="Сообщение об ошибке"),
    },
)

# Модель списка кошельков с поддержкой новых сетей
_wallets = ns.model(
    "WalletList",
    {
        "bep": fields.String,
        "erc": fields.String,
        "trc": fields.String,
        "eth": fields.String,
        "bnb": fields.String,
        "trx": fields.String,
    },
)

_empty = ns.model("Empty", {})

# Модель комиссии по сетям
_fee = ns.model(
    "Fee",
    {
        "bep": fields.String,
        "erc": fields.String,
        "trc": fields.String,
        "eth": fields.String,
        "bnb": fields.String,
        "trx": fields.String,
    },
)

# Модель входящих данных для запроса вывода средств
_withdraw_in = ns.model(
    "WithdrawIn",
    {
        "network": fields.String(
            required=True,
            enum=["bep", "erc", "trc", "eth", "bnb", "trx"],
            description="Сеть для вывода",
        ),
        "amount": fields.String(
            required=True, example="50.00", description="Сумма вывода"
        ),
        "destination": fields.String(
            required=True,
            example="0x… / TA… / bnb…",
            description="Адрес получателя",
        ),
        "2fa_code": fields.String(
            required=True,
            example="123456",
            description="Код двухфакторной аутентификации",
        ),
    },
)

# Модель ответа на запрос вывода средств
_withdraw_out = ns.model(
    "WithdrawOut",
    {
        "status": fields.String(description="Статус транзакции"),
        "transaction_id": fields.Integer(description="ID транзакции"),
    },
)

# Модель балансов по сетям с нативными токенами
_balance_out = ns.model(
    "BalanceOut",
    {
        "bep_balance": fields.String(description="Баланс BSC"),
        "erc_balance": fields.String(description="Баланс Ethereum"),
        "trc_balance": fields.String(description="Баланс Tron"),
        "eth_balance": fields.String(description="Баланс Ethereum (native)"),
        "bnb_balance": fields.String(description="Баланс Binance Smart Chain (native)"),
        "trx_balance": fields.String(description="Баланс Tron (native)"),
    },
)

# Модель транзакции для истории
_tx = ns.model(
    "Tx",
    {
        "type": fields.String(description="Тип транзакции"),
        "amount": fields.String(description="Сумма"),
        "network": fields.String(description="Сеть"),
        "status": fields.String(description="Статус транзакции"),
        "timestamp": fields.DateTime(
            attribute="created_at", description="Время создания"
        ),
    },
)

# Модель для проверки адреса кошелька
_check_in = ns.model(
    "CheckWalletIn",
    {
        "wallet_address": fields.String(
            required=True, description="Адрес кошелька для проверки"
        )
    },
)

_check_out = ns.model("CheckWalletOut", {"status": fields.String(description="Статус проверки")})

# Модель баланса рефералов
_ref_bal = ns.model("RefBalance", {"balance": fields.String(description="Баланс рефералов")})

# Модель запроса на вывод с реферального баланса
_ref_wd = ns.model(
    "RefWithdrawIn",
    {
        "amount": fields.String(
            required=True,
            example="25.00",
            description="Сумма вывода реферальных средств",
        )
    },
)

# Модели для управления токенами пользователя
blockchain_token_out = ns.model(
    "BlockchainTokenOut",
    {
        "id": fields.Integer(description="ID токена"),
        "symbol": fields.String(description="Символ токена"),
        "contract_address": fields.String(description="Адрес контракта токена"),
        "tracked": fields.Boolean(description="Отслеживается ли токен пользователем"),
    },
)

balance_out = ns.model(
    "BalanceOutBlockchainTokens",
    {
        "symbol": fields.String(description="Символ токена"),
        "balance": fields.String(description="Баланс токена в виде строки"),
    },
)

add_blockchain_token_in = ns.model(
    "AddBlockchainTokenIn",
    {
        "blockchain_token_id": fields.Integer(
            required=True, description="ID токена для добавления"
        ),
    },
)

remove_blockchain_token_in = ns.model(
    "RemoveBlockchainTokenIn",
    {
        "blockchain_token_id": fields.Integer(
            required=True, description="ID токена для удаления"
        ),
    },
)


@ns.route("/create_wallet")
class WalletCreate(Resource):
    """
    Создание новых кошельков для пользователя или получение существующих.

    POST:
        - Создаёт кошельки для всех поддерживаемых сетей для текущего пользователя,
          если их ещё нет.
        - Возвращает словарь с адресами кошельков по сетям.
    """

    @jwt_required()
    @ns.expect(_empty)
    @ns.marshal_with(_wallets)
    def post(self) -> Dict[str, str]:
        user = User.query.get(get_jwt_identity())
        try:
            result = svc.create_wallets(user)
            logger.info(f"Wallets created/found for user {user.id}: {result}")
            return result
        except SQLAlchemyError as e:
            logger.error(f"DB error creating wallets for user {user.id}: {e}", exc_info=True)
            raise WalletCreationError("Database error occurred.")
        except Exception as e:
            logger.error(f"Failed to create wallets for user {user.id}: {e}", exc_info=True)
            raise WalletCreationError("Failed to create wallets.")


@ns.route("/get_wallet")
class WalletGet(Resource):
    """
    Получение адресов кошельков пользователя.

    POST:
        - Возвращает адреса кошельков по всем поддерживаемым сетям для текущего пользователя.
        - Если кошельки не найдены, выбрасывает WalletRetrievalError.
    """

    @jwt_required()
    @ns.expect(_empty)
    @ns.marshal_with(_wallets, skip_none=True)
    def post(self) -> Dict[str, Any]:
        user = User.query.get(get_jwt_identity())
        try:
            res = svc.list_wallets(user)
            if not res:
                raise WalletRetrievalError("Wallets not found.")
            logger.info(f"Wallet addresses retrieved for user {user.id}: {res}")
            return res
        except SQLAlchemyError as e:
            logger.error(f"DB error retrieving wallets for user {user.id}: {e}", exc_info=True)
            raise WalletRetrievalError("Database error occurred.")
        except WalletRetrievalError as e:
            logger.warning(f"{e.message} for user {user.id}")
            raise
        except Exception as e:
            logger.error(f"Failed to get wallets for user {user.id}: {e}", exc_info=True)
            raise WalletRetrievalError("Failed to get wallets.")


@ns.route("/transfer_fee")
class TransferFee(Resource):
    """
    Получение таблицы комиссий за переводы в разных сетях.

    GET:
        - Возвращает словарь с комиссиями за перевод в USDT по каждой поддерживаемой сети.
        - Если комиссии не найдены или произошла ошибка, возвращает соответствующую ошибку.
    """

    @ns.marshal_with(_fee)
    def get(self) -> Dict[str, str]:
        try:
            fees = {k: str(v) for k, v in svc.transfer_fee_table().items()}
            if not fees:
                logger.warning("Transfer fees not found.")
                return {}, 204
            logger.info(f"Transfer fees requested: {fees}")
            return fees
        except SQLAlchemyError as e:
            logger.error(f"DB error getting transfer fees: {e}", exc_info=True)
            raise TransferFeeRetrievalError("Database error occurred.")
        except Exception as e:
            logger.error(f"Failed to get transfer fees: {e}", exc_info=True)
            raise TransferFeeRetrievalError("Failed to get transfer fees.")


@ns.route("/withdraw")
class Withdraw(Resource):
    """
    Запрос на вывод средств с кошелька пользователя.

    POST:
        - Принимает данные: сеть, сумму, адрес назначения, 2FA код.
        - Проводит валидацию и инициирует транзакцию вывода.
        - Возвращает статус и ID транзакции.
        - В случае ошибок выбрасывает соответствующие исключения.
    """

    @jwt_required()
    @ns.expect(_withdraw_in)
    @ns.marshal_with(_withdraw_out, code=201)
    def post(self) -> Dict[str, Any]:
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
                f"Withdraw request from user {user.id}: network={data['network']}, amount={data['amount']}, dest={data['destination']}, tx_id={tx.id}"
            )
            return {"status": tx.status.value, "transaction_id": tx.id}, 201
        except ValueError as e:
            logger.warning(f"Invalid withdraw request from user {user.id}: {e}")
            raise WithdrawError("Invalid request for withdrawal.")
        except SQLAlchemyError as e:
            logger.error(f"DB error withdrawing funds for user {user.id}: {e}", exc_info=True)
            raise WithdrawError("Database error occurred.")
        except Exception as e:
            logger.error(f"Failed to withdraw funds for user {user.id}: {e}", exc_info=True)
            raise WithdrawError("Failed to withdraw funds.")


@ns.route("/balance")
class Balance(Resource):
    """
    Получение балансов пользователя по основным сетям.

    GET:
        - Возвращает баланс пользователя по сетям BEP, ERC, TRC, а также нативным токенам ETH, BNB, TRX.
        - В случае ошибок выбрасывает BalanceError.
    """

    @jwt_required()
    @ns.marshal_with(_balance_out)
    def get(self) -> Dict[str, str]:
        
        user = User.query.get(get_jwt_identity())
        try:
            bep_balance = svc.get_real_balance(user, "bep")
            erc_balance = svc.get_real_balance(user, "erc")
            trc_balance = svc.get_real_balance(user, "trc")
            eth_balance = svc.get_real_balance(user, "eth")
            bnb_balance = svc.get_real_balance(user, "bnb")
            trx_balance = svc.get_real_balance(user, "trx")
            balances = {
                "bep_balance": str(bep_balance),
                "erc_balance": str(erc_balance),
                "trc_balance": str(trc_balance),
                "eth_balance": str(eth_balance),
                "bnb_balance": str(bnb_balance),
                "trx_balance": str(trx_balance),
            }
            logger.info(f"Balances retrieved for user {user.id}: {balances}")
            return balances
        except SQLAlchemyError as e:
            logger.error(f"DB error getting balance for user {user.id}: {e}", exc_info=True)
            raise BalanceError("Database error occurred.")
        except Exception as e:
            logger.error(f"Failed to get balance for user {user.id}: {e}", exc_info=True)
            raise BalanceError("Failed to get balance.")


@ns.route("/transactions")
class Transactions(Resource):
    """
    Получение истории транзакций пользователя.

    GET:
        - Возвращает список транзакций пользователя с типом, суммой, сетью, статусом и временем.
        - В случае ошибки выбрасывает TransactionError.
    """

    @jwt_required()
    @ns.expect(_empty)
    @ns.marshal_list_with(_tx)
    def get(self) -> List[Dict[str, Any]]:
        user = User.query.get(get_jwt_identity())
        try:
            return svc.history(user)
        except Exception as e:
            logger.error(f"Error getting transaction history for user {user.id}: {e}", exc_info=True)
            raise TransactionError("Failed to get transaction history.")


@ns.route("/check_wallet")
class CheckWallet(Resource):
    """
    Проверка безопасности адреса кошелька.

    POST:
        - Принимает адрес кошелька.
        - Возвращает статус безопасности (пока заглушка).
        - TODO: реализовать реальную проверку безопасности.
    """

    @ns.expect(_check_in)
    @ns.marshal_with(_check_out)
    def post(self) -> Dict[str, str]:
        wallet_address = ns.payload.get("wallet_address")
        logger.info(f"Wallet check requested for address: {wallet_address}")
        # TODO: добавить реальную логику проверки безопасности адреса
        return {"status": "safe"}


@ns.route("/referral_balance")
class RefBal(Resource):
    """
    Получение баланса реферальных начислений пользователя.

    GET:
        - Возвращает баланс рефералов пользователя.
        - В случае ошибки выбрасывает ReferralError.
    """

    @jwt_required()
    @ns.marshal_with(_ref_bal)
    def get(self) -> Dict[str, str]:
        user = User.query.get(get_jwt_identity())
        try:
            balance = svc.ref_balance(user)
            logger.info(f"Referral balance for user {user.id}: {balance}")
            return {"balance": str(balance)}
        except Exception as e:
            logger.error(f"Error getting referral balance for user {user.id}: {e}", exc_info=True)
            raise ReferralError("Failed to get referral balance.")


@ns.route("/referral_withdraw")
class RefWithdraw(Resource):
    """
    Вывод средств с реферального баланса.

    POST:
        - Принимает сумму вывода.
        - Проверяет минимальный порог вывода.
        - Списывает средства с реферального баланса и зачисляет на основной баланс.
        - В случае ошибок возвращает соответствующие сообщения.
    """

    @jwt_required()
    @ns.expect(_ref_wd)
    def post(self) -> Dict[str, str]:
        user = User.query.get(get_jwt_identity())
        try:
            amt = Decimal(ns.payload["amount"])
        except Exception:
            logger.warning(f"Invalid referral withdraw amount format from user {user.id}")
            ns.abort(400, "Invalid amount format")

        min_payout = Decimal(os.getenv("REF_MIN_PAYOUT", "10"))
        if amt < min_payout:
            logger.warning(f"Referral withdraw amount below minimum for user {user.id}: {amt} < {min_payout}")
            ns.abort(400, f"Amount below minimum payout {min_payout}")

        try:
            svc.ref_debit(user, amt)
            svc.debit(user, "erc", -amt)
            logger.info(f"Successful referral withdraw for user {user.id}, amount: {amt}")
        except ValueError as e:
            logger.warning(f"Referral withdraw error for user {user.id}: {e}")
            ns.abort(400, str(e))
        except Exception as e:
            logger.error(f"Error during referral withdraw for user {user.id}: {e}", exc_info=True)
            raise ReferralError("Failed to withdraw referral funds.")

        return {"status": "ok"}


@ns.route("/blockchain_tokens/<string:network>")
class BlockchainTokensList(Resource):
    """
    Получение списка всех активных токенов и тех, что отслеживает пользователь в указанной сети.

    GET:
        - Проверяет поддержку сети.
        - Возвращает список всех активных токенов и помечает, какие из них отслеживаются текущим пользователем.
    """

    @jwt_required()
    @ns.marshal_list_with(blockchain_token_out)
    def get(self, network):
        valid_networks = ("bep", "erc", "trc", "eth", "bnb", "trx")
        if network not in valid_networks:
            ns.abort(400, f"Unsupported network '{network}'")

        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        if not user:
            ns.abort(404, "User not found")

        all_tokens = svc.get_all_active_blockchain_tokens(network)
        tracked_tokens = svc.get_tracked_blockchain_tokens(user, network)
        tracked_ids = {t.id for t in tracked_tokens}

        return [
            {
                "id": token.id,
                "symbol": token.symbol,
                "contract_address": token.contract_address,
                "tracked": token.id in tracked_ids,
            }
            for token in all_tokens
        ]


@ns.route("/tokens")
class TokensAdd(Resource):
    """
    Добавление токена в список отслеживаемых пользователем.

    POST:
        - Принимает ID токена.
        - Добавляет токен в список отслеживаемых для текущего пользователя.
        - Возвращает подтверждение с ID добавленного токена.
    """

    @jwt_required()
    @ns.expect(add_blockchain_token_in)
    def post(self):
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        if not user:
            ns.abort(404, "User not found")

        blockchain_token_id = ns.payload.get("blockchain_token_id")
        if not blockchain_token_id:
            ns.abort(400, "blockchain_token_id required")

        try:
            tracked = svc.add_tracked_token(user, blockchain_token_id)
        except Exception as e:
            ns.abort(400, str(e))

        return {
            "message": "Token added",
            "blockchain_token_id": tracked.blockchain_token_id,
        }, 201


@ns.route("/tokens/remove")
class TokensRemove(Resource):
    """
    Удаление токена из списка отслеживаемых пользователем.

    DELETE:
        - Принимает ID токена.
        - Удаляет токен из списка отслеживаемых для текущего пользователя.
        - Возвращает подтверждение удаления.
    """

    @jwt_required()
    @ns.expect(remove_blockchain_token_in)
    def delete(self):
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        if not user:
            ns.abort(404, "User not found")

        blockchain_token_id = ns.payload.get("blockchain_token_id")
        if not blockchain_token_id:
            ns.abort(400, "blockchain_token_id required")

        try:
            removed = svc.remove_tracked_token(user, blockchain_token_id)
            if not removed:
                ns.abort(404, "Token not found in tracked list")
        except Exception as e:
            ns.abort(500, f"Failed to remove token: {e}")

        logger.info(f"User {user.id} removed token {blockchain_token_id} from tracked")
        return {
            "message": "Token removed",
            "blockchain_token_id": blockchain_token_id,
        }, 200


@ns.route("/balances/<string:network>")
class TokenBalances(Resource):
    """
    Получение балансов отслеживаемых токенов пользователя в указанной сети.

    GET:
        - Проверяет поддержку сети.
        - Возвращает словарь балансов токенов с символами и значениями.
    """

    @jwt_required()
    def get(self, network):
        valid_networks = ("bep", "erc", "trc", "eth", "bnb", "trx")
        if network not in valid_networks:
            ns.abort(400, f"Unsupported network '{network}'")

        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        if not user:
            ns.abort(404, "User not found")

        try:
            balances = svc.get_tracked_balances(user, network)
        except Exception as e:
            ns.abort(500, f"Failed to get balances: {e}")

        # Приводим балансы к строковому виду с 6 знаками после запятой
        return {
            sym: str(balance.quantize(Decimal("1.000000")))
            for sym, balance in balances.items()
        }
