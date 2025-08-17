from __future__ import annotations

import logging
from typing import List

from onfine.extensions import db
from onfine.models.blockchain_tokens import BlockchainTokens
from onfine.models.user import User
from onfine.models.user_tracked_blockchain_tokens import (
    UserTrackedBlockchainToken,
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
    """
    existing = UserTrackedBlockchainToken.query.filter_by(
        user_id=user.id,
        blockchain_token_id=blockchain_token_id,
    ).first()
    if existing:
        return existing
    tracked = UserTrackedBlockchainToken(user_id=user.id, blockchain_token_id=blockchain_token_id)
    db.session.add(tracked)
    db.session.commit()
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
        Exception: При ошибках удаления из базы данных.
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
    except Exception as e:
        db.session.rollback()
        logger.error(f"Ошибка удаления отслеживаемого токена: {e}")
        raise
    return True
