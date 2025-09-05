import logging
from decimal import ROUND_DOWN, Decimal
from typing import Any, Dict

from flask import request
from flask_jwt_extended import get_jwt_identity, jwt_required
from flask_restx import Namespace, Resource, fields
from sqlalchemy.exc import SQLAlchemyError

from onfine.models.user import User
from onfine.services import wallet_service as svc

from ..api.error_handlers import (
    BalanceError,
    WalletCreationError,
    WalletRetrievalError,
    register_error_handlers,
)

logger = logging.getLogger(__name__)

# Создаём пространство имён API для кошельков с описанием
ns = Namespace("wallets", description="Кошельки, баланс, вывод")

# Регистрируем обработчики ошибок для данного namespace
register_error_handlers(ns)

# ----------- Swagger-модели для документации API ----------

VALID_NETWORKS = ("erc20", "bep20", "trc20")
NATIVE_TOKENS = {
    "erc20": "ETH",
    "bep20": "BNB",
    "trc20": "TRX",
}

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
        "erc20": fields.String(description="Адрес кошелька Ethereum"),
        "bep20": fields.String(description="Адрес кошелька Binance Smart Chain"),
        "trc20": fields.String(description="Адрес кошелька Tron"),
    },
)

_wallet_create_in = ns.model(
    "WalletCreateIn",
    {
        "network": fields.List(
            fields.String(enum=["erc20", "bep20", "trc20"]),
            required=False,
            description="Список сетей, для которых нужно создать кошельки.",
            example=["erc20", "trc20"],
        ),
    },
)

_empty = ns.model("Empty", {})

# Модель комиссии по сетям
_fee = ns.model(
    "Fee",
    {
        "ethereum": fields.String(description="Комиссия Ethereum (USDT)"),
        "bsc": fields.String(description="Комиссия Binance Smart Chain (USDT)"),
        "tron": fields.String(description="Комиссия Tron (USDT)"),
    },
)

# Модель входящих данных для запроса вывода средств
_withdraw_in = ns.model(
    "WithdrawIn",
    {
        "network": fields.String(
            required=True,
            enum=VALID_NETWORKS,
            description="Сеть для вывода",
        ),
        "amount": fields.String(required=True, example="50.00", description="Сумма вывода"),
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
        "erc20": fields.String(description="Баланс Ethereum (ETH и токены)"),
        "bep20": fields.String(description="Баланс Binance Smart Chain (BNB и токены)"),
        "trc20": fields.String(description="Баланс Tron (TRX и токены)"),
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
        "timestamp": fields.DateTime(attribute="created_at", description="Время создания"),
    },
)

# Модель для проверки адреса кошелька
_check_in = ns.model(
    "CheckWalletIn",
    {"wallet_address": fields.String(required=True, description="Адрес кошелька для проверки")},
    {"wallet_address": fields.String(required=True, description="Адрес кошелька для проверки")},
)

_check_out = ns.model("CheckWalletOut", {"status": fields.String(description="Статус проверки")})
_check_out = ns.model("CheckWalletOut", {"status": fields.String(description="Статус проверки")})

# Модель баланса рефералов
_ref_bal = ns.model("RefBalance", {"balance": fields.String(description="Баланс рефералов")})
_ref_bal = ns.model("RefBalance", {"balance": fields.String(description="Баланс рефералов")})

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
        "blockchain_token_id": fields.Integer(required=True, description="ID токена для добавления"),
    },
)

remove_blockchain_token_in = ns.model(
    "RemoveBlockchainTokenIn",
    {
        "blockchain_token_id": fields.Integer(required=True, description="ID токена для удаления"),
    },
)

# Модель входных данных (здесь ничего не нужно, но можно оставить для валидации)
_balance_for_purchase_in = ns.model("BalanceForPurchaseIn", {})

# Модель ответа
_balance_for_purchase_out = ns.model(
    "BalanceForPurchaseOut",
    {
        "network": fields.String(description="Сеть (erc20, bep20, trc20)"),
        "package_price_usdt": fields.String(description="Стоимость пакета в USDT"),
        "usdt_balance": fields.String(description="Баланс USDT пользователя"),
        "has_enough_usdt": fields.Boolean(description="Хватает ли USDT для пакета"),
        "native_token": fields.String(description="Нативный токен газа (ETH/BNB/TRX)"),
        "native_balance": fields.String(description="Баланс нативного токена"),
        "estimated_gas_fee_native": fields.String(description="Газ в нативном токене"),
        "estimated_gas_fee_usdt": fields.String(description="Газ в USDT-эквиваленте"),
        "has_enough_gas": fields.Boolean(description="Хватает ли газа"),
        "total_required_usdt": fields.String(description="Общая сумма в USDT, если газа нет (пакет + газ)"),
        "has_enough_total": fields.Boolean(description="Хватает ли средств в целом"),
        "shortfall_usdt": fields.String(description="Сколько не хватает в USDT (если не хватает)"),
    },
)


@ns.route("/create-wallet")
class WalletCreate(Resource):
    """
    Создание новых кошельков для пользователя или получение существующих.
    """

    @jwt_required()
    @ns.expect(_wallet_create_in)
    @ns.marshal_with(_wallets)
    def post(self) -> Dict[str, str]:
        """
        Создаёт кошельки для указанных сетей (или всех, если не указано) для текущего пользователя.

        Returns:
            Dict[str, str]: Адреса кошельков по сетям.
        """
        user = User.query.get(get_jwt_identity())
        networks = ns.payload.get("network")
        if networks is None:
            networks = []  # Пустой список, если networks не было передано
        try:
            result = svc.create_wallets(user=user, networks=networks)
            logger.info(f"Wallet created/found for user {user.id}: {result}")
            return result
        except SQLAlchemyError as e:
            logger.error(
                f"DB error creating wallets for user {user.id}: {e}",
                exc_info=True,
            )
            raise WalletCreationError("Database error occurred.")
        except Exception as e:
            logger.error(
                f"Failed to create wallets for user {user.id}: {e}",
                exc_info=True,
            )
            raise WalletCreationError("Failed to create wallets.")


@ns.route("/get-wallet")
class WalletGet(Resource):
    """
    Получение адресов кошельков пользователя.
    """

    @jwt_required()
    @ns.marshal_with(_wallets, skip_none=True)
    def get(self) -> Dict[str, Any]:
        """
        Возвращает адреса кошельков по всем поддерживаемым сетям для текущего пользователя.

        Returns:
            Dict[str, Any]: Адреса кошельков.

        Example request:
        curl -X GET "http://127.0.0.1:5500/api/wallets/get-wallet" \
            -H "Authorization: Bearer <your_jwt_token>" \
            -H "Accept: application/json"

        """
        user = User.query.get(get_jwt_identity())
        try:
            res = svc.list_wallets(user)
            if not res:
                raise WalletRetrievalError("Wallets not found.")
            logger.info(f"Wallet addresses retrieved for user {user.id}: {res}")
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
            logger.error(f"Failed to get wallets for user {user.id}: {e}", exc_info=True)
            raise WalletRetrievalError("Failed to get wallets.")


@ns.route("/check-wallet")
class CheckWallet(Resource):
    """
    Проверка безопасности адреса кошелька.

    POST:
        - TODO: реализовать реальную проверку безопасности.
    """

    @ns.expect(_check_in)
    @ns.marshal_with(_check_out)
    def post(self) -> Dict[str, str]:
        """
        Проверить безопасность адреса кошелька.

        Returns:
            dict: Статус проверки безопасности (например, {"status": "safe"}).
        """
        wallet_address = ns.payload.get("wallet_address")
        logger.info(f"Wallet check requested for address: {wallet_address}")
        # TODO: добавить реальную логику проверки безопасности адреса
        return {"status": "safe"}


# @ns.route("/transfer-fee")
# class TransferFee(Resource):
#     """
#     Получение таблицы комиссий за переводы в разных сетях.
#     """

#     @ns.marshal_with(_fee)
#     def get(self) -> Dict[str, str]:
#         """
#         Возвращает комиссии за перевод в USDT по каждой поддерживаемой сети.

#         Returns:
#             Dict[str, str]: Комиссии по сетям.
#         """
#         try:
#             fees = {k: str(v) for k, v in svc.transfer_fee_table().items() if k in VALID_NETWORKS}
#             if not fees:
#                 logger.warning("Transfer fees not found.")
#                 return {}, 204
#             logger.info(f"Transfer fees requested: {fees}")
#             return fees
#         except SQLAlchemyError as e:
#             logger.error(f"DB error getting transfer fees: {e}", exc_info=True)
#             raise TransferFeeRetrievalError("Database error occurred.")
#         except Exception as e:
#             logger.error(f"Failed to get transfer fees: {e}", exc_info=True)
#             raise TransferFeeRetrievalError("Failed to get transfer fees.")

# @ns.route("/withdraw")
# class Withdraw(Resource):
#     """
#     Запрос на вывод средств с кошелька пользователя.
#     """

#     @jwt_required()
#     @ns.expect(_withdraw_in)
#     @ns.marshal_with(_withdraw_out, code=201)
#     def post(self) -> Dict[str, Any]:
#         """
#         Инициирует транзакцию вывода средств.

#         Returns:
#             Dict[str, Any]: Статус и ID транзакции.
#         """
#         user = User.query.get(get_jwt_identity())
#         data = ns.payload
#         network = data["network"]
#         if network not in VALID_NETWORKS:
#             ns.abort(400, f"Unsupported network '{network}'")
#         try:
#             tx = svc.withdraw_funds(
#                 user=user,
#                 network=network,
#                 amount=Decimal(data["amount"]),
#                 dest=data["destination"],
#                 twofa_code=data["2fa_code"],
#             )
#             logger.info(
#                 f"Withdraw request from user {user.id}: "
#                 f"network={network}, "
#                 f"amount={data['amount']}, "
#                 f"dest={data['destination']}, "
#                 f"tx_id={tx.id}",
#             )

#             return {"status": tx.status.value, "transaction_id": tx.id}, 201
#         except ValueError as e:
#             logger.warning(f"Invalid withdraw request from user {user.id}: {e}")
#             raise WithdrawError("Invalid request for withdrawal.")
#         except SQLAlchemyError as e:
#             logger.error(
#                 f"DB error withdrawing funds for user {user.id}: {e}",
#                 exc_info=True,
#             )
#             raise WithdrawError("Database error occurred.")
#         except Exception as e:
#             logger.error(
#               f"Failed to withdraw funds for user {user.id}: {e}",
#               f"Failed to withdraw funds for user {user.id}: {e}",
#                 exc_info=True,
#             )
#             raise WithdrawError("Failed to withdraw funds.")


@ns.route("/balances/<string:network>")
class TokenBalances(Resource):
    """
    Возвращает балансы отслеживаемых токенов пользователя в указанной сети.

    Args:
        network (str): Название сети (erc20, bep20, trc20).

    Returns:
        Dict[str, str]: Словарь с символами токенов и их балансами в виде строк.
    """

    @jwt_required()
    def get(self, network: str) -> Dict[str, str]:  # noqa: D102
        if network not in VALID_NETWORKS:
            ns.abort(400, f"Unsupported network '{network}'")

        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        if not user:
            ns.abort(404, "User  not found")

        try:
            balances = svc.get_tracked_balances(user, network)
        except Exception as e:
            ns.abort(500, f"Failed to get balances: {e}")

        q = Decimal("0.000001")
        return {
            sym: str((bal if isinstance(bal, Decimal) else Decimal(bal)).quantize(q, rounding=ROUND_DOWN))
            for sym, bal in balances.items()
        }


@ns.route("/balance-for-purchase/<string:network>")
@ns.param("amount", "Необходимое количество токена для покупки", required=False)
@ns.param("token_symbol", "Символ токена (дефолтный, USDT)", required=False)
class PurchaseBalance(Resource):
    """
    Получение балансов пользователя token_symbol и gas для приобретения пакета
    """

    @jwt_required()
    @ns.marshal_with(_balance_for_purchase_out)
    def get(self, network: str) -> Dict[str, Any]:
        """
        Возвращает баланс пользователя по токену и нативному балансу для оплаты газа.

        Args:
            network (str): Название сети (erc20, bep20, trc20).

        Returns:
            Dict[str, Any]: Информация о балансе, достаточности токенов и газа.

        Example request:
        curl -X GET "http://127.0.0.1:5500/api/wallets/balance-for-purchase/erc20?amount=100.00&token_symbol=USDT" \
            -H "Authorization: Bearer <your_jwt_token>" \
            -H "Accept: application/json"

        amount — необязательный, сумма токенов для покупки (например, 100.00).
        token_symbol — необязательный, символ токена (по умолчанию USDT).
        """
        amount: Decimal | None = None
        user = User.query.get(get_jwt_identity())
        amount_str = request.args.get("amount")
        token_symbol = request.args.get("token_symbol")
        if not token_symbol:
            token_symbol = "USDT"
        if amount_str:
            try:
                amount = Decimal(amount_str)
            except Exception:
                ns.abort(400, "'amount' должен быть числом.")
        try:
            # balance = svc.get_balance(
            #     user=user, network=network, token_symbol=token_symbol
            # )

            balances = {
                # "ethereum_balance": str(ethereum_balance),
                # "bsc_balance": str(bsc_balance),
                # "tron_balance": str(tron_balance),
            }
            logger.info(f"Balances retrieved for user {user.id}: {balances}")
            return balances
        except SQLAlchemyError as e:
            logger.error(
                f"DB error getting balance for user {user.id}: {e}",
                exc_info=True,
            )
            raise BalanceError("Database error occurred.")
        except Exception as e:
            logger.error(f"Failed to get balance for user {user.id}: {e}", exc_info=True)
            logger.error(f"Failed to get balance for user {user.id}: {e}", exc_info=True)
            raise BalanceError("Failed to get balance.")

        try:
            result = svc.get_balance_info_for_purchase(
                user=user,
                network=network,
                token_symbol=token_symbol,
                amount=amount,  # может быть None
            )

            # Если amount не передан — удалим поля из ответа
            if amount is None:
                result.pop("required_token_amount", None)
                result.pop("has_enough_token", None)
                result.pop("estimated_gas_fee", None)
                result.pop("estimated_gas_fee_usdt", None)
                result.pop("has_enough_gas", None)

            return result

        except Exception as e:
            logger.error(f"Ошибка при получении баланса для покупки: {e}", exc_info=True)
            logger.error(f"Ошибка при получении баланса для покупки: {e}", exc_info=True)
            raise BalanceError("Не удалось получить баланс для покупки.")


# @ns.route("/ready/<string:network>")
# class WalletReadiness(Resource):
#     """
#     Проверка, достаточно ли средств для покупки токена с учетом газа.
#     """

#     @jwt_required()
#     @ns.param("token", "Символ токена, например USDT")
#     @ns.param("amount", "Требуемая сумма токена")
#     def get(self, network: str):
#         if network not in VALID_NETWORKS:
#             ns.abort(400, f"Unsupported network '{network}'")

#         user = User.query.get(get_jwt_identity())
#         if not user:
#             ns.abort(404, "User not found")

#         token_symbol = request.args.get("token")
#         try:
#             amount = Decimal(request.args.get("amount"))
#         except:
#             ns.abort(400, "Invalid or missing 'amount'")

#         # Получаем баланс токена
#         balances = svc.get_tracked_balances(user, network)
#         token_balance = balances.get(token_symbol, Decimal("0"))

#         # Получаем баланс газа
#         native_token = {
#             "erc20": "ETH",
#             "bep20": "BNB",
#             "trc20": "TRX"
#         }.get(network)

#         native_balance = svc.get_real_balance(user, network)
#         estimated_gas = svc.estimate_gas_fee(network, token_symbol)

#         return {
#             "network": network,
#             "token": token_symbol,
#             "token_balance": str(token_balance),
#             "required_token_amount": str(amount),
#             "has_enough_token": token_balance >= amount,
#             "native_balance": str(native_balance),
#             "estimated_gas_fee": str(estimated_gas),
#             "has_enough_gas": native_balance >= estimated_gas,
#         }


@ns.route("/transactions")
class Transactions(Resource):
    """
    Получение истории транзакций пользователя.

    Example request:
    curl -X GET "http://127.0.0.1:5500/api/wallets/transactions" \
        -H "Authorization: Bearer <your_jwt_token>" \
        -H "Accept: application/json"

    """


# _____МЕТОД ТРЕБУЕТ ДОРАБОТКИ___
# @jwt_required()
# @ns.marshal_list_with(_tx)
# def get(self) -> Dict[str, List[Dict[str, Any]]]:
#     """
#     Получить историю транзакций текущего пользователя.

#     Returns:
#         dict: Словарь с ключом "transactions", содержащий список транзакций.
#             Каждая транзакция — словарь с полями типа, суммы, сети, статуса и времени.

#     Raises:
#         TransactionError: Если не удалось получить историю транзакций.
#     """
#     user = User.query.get(get_jwt_identity())
#     try:
#         # ТУТА НАДА ПЕРЕДЕЛАТЬ НА ПОЛУЧЕНИЕ ИСТОРИИ ИЗ СКАНЕРА
#         txs = svc.history(user)
#         return {"transactions": txs}
#     except Exception as e:
#         logger.error(
#             f"Error getting transaction history for user {user.id}: {e}",
#             exc_info=True,
#         )
#         raise TransactionError("Failed to get transaction history.")
