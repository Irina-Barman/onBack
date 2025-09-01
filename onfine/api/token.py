import logging
from typing import Any, Dict, List

from flask_jwt_extended import get_jwt_identity, jwt_required
from flask_restx import Namespace, Resource, fields

from onfine.models.user import User
from onfine.services import token_service as svc

from ..api.error_handlers import (
    register_error_handlers,
)

logger = logging.getLogger(__name__)

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

        Raises:
            400: Если сеть не поддерживается.
            404: Если пользователь не найден.
        """
        if network not in VALID_NETWORKS:
            ns.abort(400, f"Unsupported network '{network}'")

        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        if not user:
            ns.abort(404, "User  not found")

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

        Raises:
            400 - при отсутствии blockchain_token_id или ошибках сервиса,
            404 - если пользователь не найден.
        """
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        if not user:
            ns.abort(404, "User  not found")

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
    def delete(self) -> tuple[Dict[str, Any], int]:
        """
        Удаляет токен из списка отслеживаемых текущим пользователем.

        Returns:
            dict, int: Подтверждение удаления и HTTP статус 200.

        Raises:
            400 - если blockchain_token_id отсутствует,
            404 - если пользователь или токен не найден,
            500 - при ошибках удаления.
        """
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        if not user:
            ns.abort(404, "User  not found")

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
            f"User  {user.id} removed token {blockchain_token_id} from tracked")
        return {
            "message": "Token removed",
            "blockchain_token_id": blockchain_token_id,
        }, 200
