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
        "network": fields.String(
            required=True,
            enum=["bep", "erc", "trc"],
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

_withdraw_out = ns.model(
    "WithdrawOut",
    {
        "status": fields.String(description="Статус транзакции"),
        "transaction_id": fields.Integer(description="ID транзакции"),
    },
)

_balance_out = ns.model(
    "BalanceOut",
    {
        "bep_balance": fields.String(description="Баланс BSC"),
        "erc_balance": fields.String(description="Баланс Ethereum"),
        "trc_balance": fields.String(description="Баланс Tron"),
    },
)

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

_check_in = ns.model(
    "CheckWalletIn",
    {
        "wallet_address": fields.String(
            required=True, description="Адрес кошелька для проверки"
        )
    },
)

_check_out = ns.model(
    "CheckWalletOut", {"status": fields.String(description="Статус проверки")}
)

_ref_bal = ns.model(
    "RefBalance", {"balance": fields.String(description="Баланс рефералов")}
)

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

# --- Модели для токенов ---
blockchain_token_out = ns.model(
    "BlockchainTokenOut",
    {
        "id": fields.Integer(description="ID токена"),
        "symbol": fields.String(description="Символ токена"),
        "contract_address": fields.String(
            description="Адрес контракта токена"
        ),
        "tracked": fields.Boolean(
            description="Отслеживается ли токен пользователем"
        ),
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
    """

    @jwt_required()
    @ns.expect(_empty)
    @ns.marshal_with(_wallets)
    def post(self) -> Dict[str, str]:
        """
        Создаёт кошельки для текущего пользователя в сетях BEP, ERC, TRC.

        Возвращает:
            dict: Словарь с адресами кошельков по сетям.

        Исключения:
            WalletCreationError: При ошибках базы данных или других проблемах.
        """
        user = User.query.get(get_jwt_identity())
        try:
            result = svc.create_wallets(user)
            logger.info(f"Wallets created/found for user {user.id}: {result}")
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


@ns.route("/get_wallet")
class WalletGet(Resource):
    """
    Получение адресов кошельков пользователя.
    """

    @jwt_required()
    @ns.expect(_empty)
    @ns.marshal_with(_wallets, skip_none=True)
    def post(self) -> Dict[str, Any]:
        """
        Возвращает адреса кошельков пользователя.

        Возвращает:
            dict: Адреса кошельков по сетям.

        Исключения:
            WalletRetrievalError: Если кошельки не найдены или произошла ошибка.
        """
        user = User.query.get(get_jwt_identity())
        try:
            res = svc.list_wallets(user)
            if not res:
                raise WalletRetrievalError("Wallets not found.")
            logger.info(
                f"Wallet addresses retrieved for user {user.id}: {res}"
            )
            return res
        except SQLAlchemyError as e:
            logger.error(
                f"DB error retrieving wallets for user {user.id}: {e}",
                exc_info=True,
            )
            raise WalletRetrievalError("Database error occurred.")
        except WalletRetrievalError as e:
            logger.warning(f"{e.message} for user {user.id}")
            raise
        except Exception as e:
            logger.error(
                f"Failed to get wallets for user {user.id}: {e}", exc_info=True
            )
            raise WalletRetrievalError("Failed to get wallets.")


@ns.route("/transfer_fee")
class TransferFee(Resource):
    """
    Получение таблицы комиссий за переводы в разных сетях.
    """

    @ns.marshal_with(_fee)
    def get(self) -> Dict[str, str]:
        """
        Возвращает комиссии за переводы для сетей BEP, ERC, TRC.

        Возвращает:
            dict: Комиссии в виде строк.

        Исключения:
            TransferFeeRetrievalError: При ошибках получения данных.
        """
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
    """

    @jwt_required()
    @ns.expect(_withdraw_in)
    @ns.marshal_with(_withdraw_out, code=201)
    def post(self) -> Dict[str, Any]:
        """
        Создаёт транзакцию вывода средств.

        Ожидает в теле запроса:
            - network (str): Сеть ('bep', 'erc', 'trc')
            - amount (str): Сумма вывода
            - destination (str): Адрес получателя
            - 2fa_code (str): Код двухфакторной аутентификации

        Возвращает:
            dict: Статус и ID транзакции.

        Исключения:
            WithdrawError: При ошибках валидации или БД.
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
                f"Withdraw request from user {user.id}: network={data['network']}, amount={data['amount']}, dest={data['destination']}, tx_id={tx.id}"
            )
            return {"status": tx.status.value, "transaction_id": tx.id}, 201
        except ValueError as e:
            logger.warning(
                f"Invalid withdraw request from user {user.id}: {e}"
            )
            raise WithdrawError("Invalid request for withdrawal.")
        except SQLAlchemyError as e:
            logger.error(
                f"DB error withdrawing funds for user {user.id}: {e}",
                exc_info=True,
            )
            raise WithdrawError("Database error occurred.")
        except Exception as e:
            logger.error(
                f"Failed to withdraw funds for user {user.id}: {e}",
                exc_info=True,
            )
            raise WithdrawError("Failed to withdraw funds.")


@ns.route("/balance")
class Balance(Resource):
    """
    Получение балансов пользователя по основным сетям.
    """

    @jwt_required()
    @ns.marshal_with(_balance_out)
    def get(self) -> Dict[str, str]:
        """
        Возвращает баланс пользователя в сетях BEP, ERC, TRC.

        Возвращает:
            dict: Балансы в виде строк.

        Исключения:
            BalanceError: При ошибках получения данных.
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
        except SQLAlchemyError as e:
            logger.error(
                f"DB error getting balance for user {user.id}: {e}",
                exc_info=True,
            )
            raise BalanceError("Database error occurred.")
        except Exception as e:
            logger.error(
                f"Failed to get balance for user {user.id}: {e}", exc_info=True
            )
            raise BalanceError("Failed to get balance.")


@ns.route("/transactions")
class Transactions(Resource):
    """
    Получение истории транзакций пользователя.
    """

    @jwt_required()
    @ns.expect(_empty)
    @ns.marshal_list_with(_tx)
    def get(self) -> List[Dict[str, Any]]:
        """
        Возвращает список транзакций пользователя.

        Возвращает:
            list: Список транзакций с деталями.

        Исключения:
            TransactionError: При ошибках получения истории.
        """
        user = User.query.get(get_jwt_identity())
        try:
            return svc.history(user)
        except Exception as e:
            logger.error(
                f"Error getting transaction history for user {user.id}: {e}",
                exc_info=True,
            )
            raise TransactionError("Failed to get transaction history.")


@ns.route("/check_wallet")
class CheckWallet(Resource):
    """
    Проверка безопасности адреса кошелька.
    """

    @ns.expect(_check_in)
    @ns.marshal_with(_check_out)
    def post(self) -> Dict[str, str]:
        """
        Проверяет адрес кошелька.

        Входные данные:
            wallet_address (str): Адрес кошелька.

        Возвращает:
            dict: Статус проверки ('safe' / 'unsafe').

        Примечание:
            Реальная логика проверки безопасности адреса должна быть реализована.
        """
        wallet_address = ns.payload.get("wallet_address")
        logger.info(f"Wallet check requested for address: {wallet_address}")
        # TODO: добавить реальную логику проверки безопасности адреса
        return {"status": "safe"}


@ns.route("/referral_balance")
class RefBal(Resource):
    """
    Получение баланса реферальных начислений пользователя.
    """

    @jwt_required()
    @ns.marshal_with(_ref_bal)
    def get(self) -> Dict[str, str]:
        """
        Возвращает баланс рефералов пользователя.

        Возвращает:
            dict: Баланс рефералов в виде строки.

        Исключения:
            ReferralError: При ошибках получения данных.
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


@ns.route("/referral_withdraw")
class RefWithdraw(Resource):
    """
    Вывод средств с реферального баланса.
    """

    @jwt_required()
    @ns.expect(_ref_wd)
    def post(self) -> Dict[str, str]:
        """
        Запрос на вывод средств с реферального баланса.

        Ожидает в теле:
            amount (str): Сумма вывода.

        Возвращает:
            dict: Статус операции.

        Ошибки:
            400 — неверный формат суммы или сумма ниже минимальной.
            ReferralError — при ошибках сервиса.
        """
        user = User.query.get(get_jwt_identity())
        try:
            amt = Decimal(ns.payload["amount"])
        except Exception:
            logger.warning(
                f"Invalid referral withdraw amount format from user {user.id}"
            )
            ns.abort(400, "Invalid amount format")

        min_payout = Decimal(os.getenv("REF_MIN_PAYOUT", "10"))
        if amt < min_payout:
            logger.warning(
                f"Referral withdraw amount below minimum for user {user.id}: {amt} < {min_payout}"
            )
            ns.abort(400, f"Amount below minimum payout {min_payout}")

        try:
            svc.ref_debit(user, amt)
            svc.debit(user, "erc", -amt)
            logger.info(
                f"Successful referral withdraw for user {user.id}, amount: {amt}"
            )
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


@ns.route("/blockchain_tokens/<string:network>")
class BlockchainTokensList(Resource):
    """
    Получение списка всех активных токенов и тех, что отслеживает пользователь в указанной сети.
    """

    @jwt_required()
    @ns.marshal_list_with(blockchain_token_out)
    def get(self, network):
        """
        Возвращает список токенов с отметкой, отслеживает ли пользователь каждый из них.

        Args:
            network (str): Название сети ('bep', 'erc', 'trc').

        Returns:
            list: Список токенов с полями id, symbol, contract_address, tracked.

        Ошибки:
            404 — если пользователь не найден.
        """
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
    """

    @jwt_required()
    @ns.expect(add_blockchain_token_in)
    def post(self):
        """
        Добавляет токен в отслеживаемые.

        Ожидает:
            blockchain_token_id (int): ID токена.

        Возвращает:
            dict: Сообщение об успешном добавлении и ID токена.

        Ошибки:
            400 — если отсутствует ID или ошибка сервиса.
            404 — если пользователь не найден.
        """
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
    """

    @jwt_required()
    @ns.expect(remove_blockchain_token_in)
    def delete(self):
        """
        Удаляет токен из отслеживаемых.

        Ожидает:
            blockchain_token_id (int): ID токена.

        Возвращает:
            dict: Сообщение об успешном удалении и ID токена.

        Ошибки:
            400 — если отсутствует ID.
            404 — если токен не найден в списке.
            404 — если пользователь не найден.
            500 — при ошибках сервиса.
        """
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

        logger.info(
            f"User {user.id} removed token {blockchain_token_id} from tracked"
        )
        return {
            "message": "Token removed",
            "blockchain_token_id": blockchain_token_id,
        }, 200


@ns.route("/balances/<string:network>")
class TokenBalances(Resource):
    """
    Получение балансов отслеживаемых токенов пользователя в указанной сети.
    """

    @jwt_required()
    def get(self, network):
        """
        Возвращает балансы токенов пользователя.

        Args:
            network (str): Название сети ('bep', 'erc', 'trc').

        Returns:
            dict: Балансы токенов в формате {symbol: balance}.

        Ошибки:
            404 — если пользователь не найден.
            500 — при ошибках получения балансов.
        """
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        if not user:
            ns.abort(404, "User not found")

        try:
            balances = svc.get_tracked_balances(user, network)
        except Exception as e:
            ns.abort(500, f"Failed to get balances: {e}")

        # Форматируем decimal с точностью до 6 знаков после запятой
        return {
            sym: str(balance.quantize(Decimal("1.000000")))
            for sym, balance in balances.items()
        }
