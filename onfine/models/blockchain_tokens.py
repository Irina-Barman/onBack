from datetime import datetime

from ..extensions import db


class BlockchainTokens(db.Model):
    """
    Модель токена блокчейна.

    Представляет токен или нативную монету в определённой сети.

    Атрибуты:
        id (int): Уникальный идентификатор записи.
        network (str): Название сети (например, 'erc', 'bep', 'trc', 'ethereum', 'bsc', 'tron').
        symbol (str): Символ токена (например, 'USDT', 'ETH', 'BNB').
        contract_address (str | None): Адрес контракта токена. Для нативных токенов (ETH, BNB, TRX) может быть None.
        decimals (int): Количество десятичных знаков токена. Обычно 18.
        is_native_gas (bool): Флаг, указывающий, что токен является нативным токеном газа сети.
        is_active (bool): Флаг активности токена (используется для фильтрации).
        created_at (datetime): Время создания записи.
    """

    __tablename__ = "blockchain_tokens"
    __table_args__ = (db.UniqueConstraint("network", "symbol"),)
    # Уникальное ограничение по паре (network, symbol) — нельзя два токена с одинаковым символом в одной сети

    id = db.Column(db.Integer, primary_key=True)
    network = db.Column(
        db.String(16),
        nullable=False,
        comment="Сеть токена, например ERC20, BEP20, TRC20, или 'ethereum', 'bsc', 'tron'",
    )
    symbol = db.Column(db.String(16), nullable=False, comment="Символ токена (тикер)")
    contract_address = db.Column(
        db.String(100),
        nullable=True,
        comment="Адрес контракта токена. Для нативных токенов (ETH, BNB, TRX) может быть None",
    )
    decimals = db.Column(
        db.Integer, nullable=False, default=18, comment="Количество десятичных знаков"
    )
    is_native_gas = db.Column(
        db.Boolean,
        default=False,
        nullable=False,
        comment="Флаг, указывающий, что токен является нативным токеном газа сети",
    )
    is_active = db.Column(
        db.Boolean, default=True, comment="Флаг активности токена для фильтрации"
    )
    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        comment="Дата и время создания записи",
    )

    def __repr__(self) -> str:
        """
        Человеко-читаемое представление объекта.

        Returns:
            str: Строка с ключевыми атрибутами токена.
        """
        return (
            f"<BlockchainToken network={self.network} symbol={self.symbol} "
            f"native_gas={self.is_native_gas}>"
        )
