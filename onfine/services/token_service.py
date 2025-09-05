"""
Сервис управления блокчейн-токенами и их отслеживанием пользователями.

Основные функции:
- Получение всех активных токенов для заданной сети.
- Получение токенов, отслеживаемых конкретным пользователем в сети.
- Добавление токена в список отслеживаемых пользователем.
- Удаление токена из списка отслеживаемых пользователем.

Используемые компоненты:
- Модели: BlockchainTokens, User, UserTrackedBlockchainToken.
- SQLAlchemy (db) для работы с базой данных.
- Логирование для аудита операций.
- Кастомное исключение InternalServerError для обработки ошибок базы данных.

Функции:

get_all_active_blockchain_tokens(network: str) -> List[BlockchainTokens]
    Возвращает список всех активных токенов для указанной блокчейн-сети.

get_tracked_blockchain_tokens(user: User, network: str) -> List[BlockchainTokens]
    Возвращает список активных токенов, которые пользователь отслеживает в заданной сети.

add_tracked_token(user: User, blockchain_token_id: int) -> UserTrackedBlockchainToken
    Добавляет токен в список отслеживаемых пользователем.
    Если токен уже отслеживается, возвращает существующую запись.
    При ошибках базы данных вызывает InternalServerError.

remove_tracked_token(user: User, blockchain_token_id: int) -> bool
    Удаляет токен из списка отслеживаемых пользователем.
    Возвращает True при успешном удалении, False если токен не найден.
    При ошибках базы данных вызывает InternalServerError.

Исключения:
- InternalServerError при ошибках работы с базой данных (например, при commit).
"""

from __future__ import annotations

import logging
from typing import List

from onfine.extensions import db
from onfine.models.blockchain_tokens import BlockchainTokens
from onfine.models.user import User
from onfine.models.user_tracked_blockchain_tokens import (
    UserTrackedBlockchainToken,
)

from ..api.error_handlers import (
    InternalServerError,
)

logger = logging.getLogger(__name__)


def get_all_active_blockchain_tokens(network: str) -> List[BlockchainTokens]:
    """
    Получает список всех активных токенов для заданной сети.

    Args:
        network (str): Название сети.

    Returns:
        List[BlockchainTokens]: Список активных токенов.
    """
    return BlockchainTokens.query.filter_by(network=network, is_active=True).all()


def get_tracked_blockchain_tokens(user: User, network: str) -> List[BlockchainTokens]:
    """
    Получает список активных токенов, отслеживаемых пользователем в указанной сети.

    Args:
        user (User): Экземпляр пользователя.
        network (str): Название сети.

    Returns:
        List[BlockchainTokens]: Список отслеживаемых токенов.
    """
    return (
        BlockchainTokens.query.join(
            UserTrackedBlockchainToken,
            BlockchainTokens.id == UserTrackedBlockchainToken.blockchain_token_id,
        )
        .filter(
            UserTrackedBlockchainToken.user_id == user.id,
            BlockchainTokens.network == network,
            BlockchainTokens.is_active.is_(True),
        )
        .all()
    )


def add_tracked_token(user: User, blockchain_token_id: int) -> UserTrackedBlockchainToken:
    """
    Добавляет токен в список отслеживаемых пользователем.

    Args:
        user (User): Экземпляр пользователя.
        blockchain_token_id (int): ID токена в базе.

    Returns:
        UserTrackedBlockchainToken: Созданная или существующая запись об отслеживании токена.

    Raises:
        InternalServerError: При ошибках базы данных (например, commit).
    """
    existing = UserTrackedBlockchainToken.query.filter_by(
        user_id=user.id,
        blockchain_token_id=blockchain_token_id,
    ).first()
    if existing:
        return existing
    tracked = UserTrackedBlockchainToken(user_id=user.id, blockchain_token_id=blockchain_token_id)
    db.session.add(tracked)
    try:
        db.session.commit()
        logger.info(f"Token {blockchain_token_id} added to tracked for user {user.id}")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Database error while adding tracked token for user {user.id}: {e}")
        raise InternalServerError(f"Failed to add tracked token: {str(e)}")
    return tracked


def remove_tracked_token(user: User, blockchain_token_id: int) -> bool:
    """
    Удаляет токен из списка отслеживаемых пользователем.

    Args:
        user (User): Экземпляр пользователя.
        blockchain_token_id (int): ID токена.

    Returns:
        bool: True, если удаление прошло успешно, False если токен не найден.

    Raises:
        InternalServerError: При ошибках базы данных (например, commit).
    """
    tracked = UserTrackedBlockchainToken.query.filter_by(
        user_id=user.id,
        blockchain_token_id=blockchain_token_id,
    ).first()
    if not tracked:
        return False
    db.session.delete(tracked)
    try:
        db.session.commit()
        logger.info(f"Token {blockchain_token_id} removed from tracked for user {user.id}")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Database error while removing tracked token for user {user.id}: {e}")
        raise InternalServerError(f"Failed to remove tracked token: {str(e)}")
    return True
