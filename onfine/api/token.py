import logging
from typing import Any, Dict, List

from flask import request
from flask_jwt_extended import get_jwt_identity, jwt_required
from flask_restx import Namespace, Resource, fields

from onfine.models.user import User
from onfine.services import token_service as svc

from ..api.error_handlers import (
    InternalServerError,
    TrackedTokenNotFoundError,
    UserNotFoundError,
    register_error_handlers,
)

logger = logging.getLogger(__name__)

# Создаём пространство имён API для токенов пользователя
# Создаём пространство имён API для токенов пользователя
ns = Namespace("tokens", description="Управление токенами пользователя")
register_error_handlers(ns)

VALID_NETWORKS = ("erc20", "bep20", "trc20")

err_model = ns.model(
    "Error",
    {
        "error": fields.String(description="Код ошибки"),
        "message": fields.String(description="Сообщение об ошибке"),
    },
)

# Модель одного токена
# Модель одного токена
blockchain_token_out = ns.model(
    "BlockchainTokenOut",
    {
        "id": fields.Integer(description="ID токена"),
        "symbol": fields.String(description="Символ токена"),
        "contract_address": fields.String(description="Адрес контракта токена"),
        "tracked": fields.Boolean(description="Отслеживается ли токен пользователем"),
    },
)

# Модель-обёртка списка токенов с ключом "tokens"
blockchain_tokens_list_out = ns.model(
    "BlockchainTokensListOut",
    {
        "tokens": fields.List(fields.Nested(blockchain_token_out), description="Список токенов"),
    },
)

# Модель-обёртка списка токенов с ключом "tokens"
blockchain_tokens_list_out = ns.model(
    "BlockchainTokensListOut",
    {
        "tokens": fields.List(fields.Nested(blockchain_token_out), description="Список токенов"),
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


@ns.route("/blockchain-tokens/<string:network>")
class BlockchainTokensList(Resource):
    """
    Получение списка всех активных токенов и тех, что отслеживает пользователь в указанной сети.
    """

    @jwt_required()
    @ns.marshal_with(blockchain_tokens_list_out)
    def get(self, network: str) -> Dict[str, List[Dict[str, Any]]]:
        """
        Получить список токенов в сети с отметкой отслеживаемых пользователем.

        Returns:
            dict: {"tokens": [...список токенов...]} с полями id, symbol, contract_address, tracked.
            dict: {"tokens": [...список токенов...]} с полями id, symbol, contract_address, tracked.

        Raises:
            ValueError: Если сеть не поддерживается (400).
            UserNotFoundError: Если пользователь не найден (404).

        Example request:
        curl -X GET "http://127.0.0.1:5500/api/tokens/blockchain-tokens/erc20" \
            -H "Accept: application/json" \
            -H "Authorization: Bearer <your_jwt_token>"

        """
        if network not in VALID_NETWORKS:
            raise ValueError(f"Unsupported network '{network}'")
            raise ValueError(f"Unsupported network '{network}'")

        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        if not user:
            logger.error(f"User with ID {user_id} not found")
            raise UserNotFoundError()
            logger.error(f"User with ID {user_id} not found")
            raise UserNotFoundError()

        all_tokens = svc.get_all_active_blockchain_tokens(network)
        tracked_tokens = svc.get_tracked_blockchain_tokens(user, network)
        tracked_ids = {t.id for t in tracked_tokens}

        tokens = [
            {
                "id": token.id,
                "symbol": token.symbol,
                "contract_address": token.contract_address,
                "tracked": token.id in tracked_ids,
            }
            for token in all_tokens
        ]

        return {"tokens": tokens}

        return {"tokens": tokens}


@ns.route("/tokens/add")
class TokensAdd(Resource):
    """
    Добавление токена в список отслеживаемых пользователем.
    """

    @jwt_required()
    @ns.expect(add_blockchain_token_in)
    def post(self) -> tuple[Dict[str, Any], int]:
        """
        Добавить токен в отслеживаемые текущим пользователем.

        Returns:
            dict, int: Сообщение об успешном добавлении и HTTP статус 201.
            dict, int: Сообщение об успешном добавлении и HTTP статус 201.

        Raises:
            UserNotFoundError: Если пользователь не найден (404).
            ValueError: Для ошибок валидации или бизнес-логики (400).
            Exception: Для неожиданных ошибок (500).
            UserNotFoundError: Если пользователь не найден (404).
            ValueError: Для ошибок валидации или бизнес-логики (400).
            Exception: Для неожиданных ошибок (500).
        """
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        if not user:
            logger.error(f"User with ID {user_id} not found")
            raise UserNotFoundError()

        data = request.get_json()
        if not data or "blockchain_token_id" not in data:
            logger.error("Missing 'blockchain_token_id' in request body")
            raise ValueError("blockchain_token_id is required")

        blockchain_token_id = data["blockchain_token_id"]
        if not isinstance(blockchain_token_id, int) or blockchain_token_id <= 0:
            logger.error(f"Invalid 'blockchain_token_id': {blockchain_token_id}")
            raise ValueError("blockchain_token_id must be a positive integer")
            logger.error(f"User with ID {user_id} not found")
            raise UserNotFoundError()

        data = request.get_json()
        if not data or "blockchain_token_id" not in data:
            logger.error("Missing 'blockchain_token_id' in request body")
            raise ValueError("blockchain_token_id is required")

        blockchain_token_id = data["blockchain_token_id"]
        if not isinstance(blockchain_token_id, int) or blockchain_token_id <= 0:
            logger.error(f"Invalid 'blockchain_token_id': {blockchain_token_id}")
            raise ValueError("blockchain_token_id must be a positive integer")

        try:
            tracked = svc.add_tracked_token(user, blockchain_token_id)
            logger.info(f"User {user.id} added token {blockchain_token_id} to tracked")
            return {
                "message": "Token added successfully",
                "blockchain_token_id": tracked.blockchain_token_id,
            }, 201
            logger.info(f"User {user.id} added token {blockchain_token_id} to tracked")
            return {
                "message": "Token added successfully",
                "blockchain_token_id": tracked.blockchain_token_id,
            }, 201
        except Exception as e:
            logger.error(f"Unexpected error in add_tracked_token for user {user.id}: {e}")
            raise InternalServerError(f"Failed to remove token: {str(e)}")
            logger.error(f"Unexpected error in add_tracked_token for user {user.id}: {e}")
            raise InternalServerError(f"Failed to remove token: {str(e)}")


@ns.route("/tokens/remove")
class TokensRemove(Resource):
    """
    Удаление токена из списка отслеживаемых пользователем.
    """

    @jwt_required()
    @ns.expect(remove_blockchain_token_in)
    def delete(self) -> tuple[Dict[str, Any], int]:
        """
        Удаляет токен из списка отслеживаемых текущим пользователем.

        Returns:
            dict, int: Подтверждение удаления и HTTP статус 200.

        Returns:
            dict, int: Подтверждение удаления и HTTP статус 200.

        Raises:
            UserNotFoundError: Если пользователь не найден (404).
            ValueError: Для ошибок валидации (400).
            TrackedTokenNotFoundError: Если токен не найден в отслеживаемых (404).
            requests.HTTPError: Для HTTP-ошибок от внешних запросов (404 или 500).
            Exception: Для неожиданных ошибок (500).
            UserNotFoundError: Если пользователь не найден (404).
            ValueError: Для ошибок валидации (400).
            TrackedTokenNotFoundError: Если токен не найден в отслеживаемых (404).
            requests.HTTPError: Для HTTP-ошибок от внешних запросов (404 или 500).
            Exception: Для неожиданных ошибок (500).
        """
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        if not user:
            logger.error(f"User with ID {user_id} not found")
            raise UserNotFoundError()

        data = request.get_json()
        if not data or "blockchain_token_id" not in data:
            logger.error("Missing 'blockchain_token_id' in request body")
            raise ValueError("blockchain_token_id is required")

        blockchain_token_id = data["blockchain_token_id"]
        if not isinstance(blockchain_token_id, int) or blockchain_token_id <= 0:
            logger.error(f"Invalid 'blockchain_token_id': {blockchain_token_id}")
            raise ValueError("blockchain_token_id must be a positive integer")
            logger.error(f"User with ID {user_id} not found")
            raise UserNotFoundError()

        data = request.get_json()
        if not data or "blockchain_token_id" not in data:
            logger.error("Missing 'blockchain_token_id' in request body")
            raise ValueError("blockchain_token_id is required")

        blockchain_token_id = data["blockchain_token_id"]
        if not isinstance(blockchain_token_id, int) or blockchain_token_id <= 0:
            logger.error(f"Invalid 'blockchain_token_id': {blockchain_token_id}")
            raise ValueError("blockchain_token_id must be a positive integer")

        try:
            removed = svc.remove_tracked_token(user, blockchain_token_id)
            if not removed:
                logger.warning(f"Token {blockchain_token_id} not found in tracked list for user {user.id}")
                raise TrackedTokenNotFoundError()
            logger.info(f"User {user.id} removed token {blockchain_token_id} from tracked")
            return {
                "message": "Token removed successfully",
                "blockchain_token_id": blockchain_token_id,
            }, 200
            logger.warning(f"Token {blockchain_token_id} not found in tracked list for user {user.id}")
            raise TrackedTokenNotFoundError()
            logger.info(f"User {user.id} removed token {blockchain_token_id} from tracked")
            return {
                "message": "Token removed successfully",
                "blockchain_token_id": blockchain_token_id,
            }, 200
        except Exception as e:
            logger.error(f"Unexpected error in remove_tracked_token for user {user.id}: {e}")
            raise InternalServerError(f"Failed to remove token: {str(e)}")
            logger.error(f"Unexpected error in remove_tracked_token for user {user.id}: {e}")
            raise InternalServerError(f"Failed to remove token: {str(e)}")
