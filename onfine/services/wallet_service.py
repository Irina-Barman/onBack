from __future__ import annotations

import logging
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from multicall import Call, Multicall
from sqlalchemy import func

from onfine.blockchain.providers import (
    BEP20,
    BNB,
    ERC20,
    ETH,
    TRC20,
    TRX,
)
from onfine.extensions import db
from onfine.models.blockchain_tokens import BlockchainTokens
from onfine.models.ledger_entry import LedgerEntry
from onfine.models.referral_balance import ReferralBalance
from onfine.models.transactions import Transaction, TxStatus, TxType
from onfine.models.transfer_fee import TransferFee
from onfine.models.user import User
from onfine.models.user_tracked_blockchain_tokens import (
    UserTrackedBlockchainToken,
)
from onfine.models.wallet import Wallet
from onfine.utils.ledger_decorator import LedgerType, ledger

logger = logging.getLogger(__name__)

# Поддерживаемые сети, для которых создаются кошельки и ведется учёт
NETWORKS: Tuple[str, ...] = ("bep", "erc", "trc", "eth", "bnb", "trx")


def _get_token_class(network: str, is_native_gas: bool = False):
    """
    Возвращает класс провайдера токена/монеты для указанной сети.

    Args:
        network (str): Название сети (например, "erc", "bep", "trc", "eth", "bnb", "trx").
        is_native_gas (bool): Если True — возвращает класс для нативного токена газа (ETH, BNB, TRX),
            иначе — для токенов стандарта (ERC20, BEP20, TRC20).

    Raises:
        ValueError: Если сеть неизвестна.

    Returns:
        Класс провайдера токена.
    """
    network = network.lower()
    if is_native_gas:
        if network in ("erc", "eth", "ethereum"):
            return ETH
        if network in ("bep", "bnb", "binance"):
            return BNB
        if network in ("trc", "trx", "tron"):
            return TRX
        raise ValueError(f"Unknown native gas network: {network}")
    else:
        if network == "erc":
            return ERC20
        if network == "bep":
            return BEP20
        if network == "trc":
            return TRC20
        raise ValueError(f"Unknown token network: {network}")


def _gen_addr_pk(network: str, is_native_gas: bool = False) -> Tuple[str, str]:
    """
    Генерирует пару (адрес, приватный ключ) для заданной сети.

    Args:
        network (str): Название сети.
        is_native_gas (bool): Использовать ли класс для нативного газа.

    Returns:
        Tuple[str, str]: Кортеж (адрес, приватный ключ).
    """
    TokenClass = _get_token_class(network, is_native_gas)
    return TokenClass.generate_wallet()


def create_wallets(user: User) -> Dict[str, str]:
    """
    Создаёт кошельки пользователя для всех поддерживаемых сетей, если их ещё нет.

    Args:
        user (User): Экземпляр пользователя.

    Raises:
        Exception: При ошибках создания или сохранения кошельков.

    Returns:
        Dict[str, str]: Словарь {сеть: адрес кошелька}.
    """
    existing = {w.network: w.address for w in user.wallets}

    for net in NETWORKS:
        if net not in existing:
            try:
                addr, pk = _gen_addr_pk(net)
                w = Wallet(
                    user_id=user.id,
                    network=net,
                    address=addr,
                    pk_enc=Wallet.encrypt_pk(pk),  # Шифруем приватный ключ перед сохранением
                )
                db.session.add(w)
                existing[net] = addr
            except Exception as e:
                logger.error(f"Ошибка создания кошелька для сети {net}: {e}")
                raise

    try:
        if db.session.new or db.session.dirty:
            db.session.commit()
    except Exception as e:
        logger.error(f"Ошибка сохранения кошельков в БД: {e}")
        raise

    return existing


def list_wallets(user: User) -> Optional[Dict[str, str]]:
    """
    Возвращает адреса всех кошельков пользователя.

    Args:
        user (User): Экземпляр пользователя.

    Returns:
        Optional[Dict[str, str]]: Словарь {сеть: адрес} или None, если кошельков нет.
    """
    wallets = {w.network: w.address for w in user.wallets}
    return wallets or None


def get_all_active_blockchain_tokens(network: str) -> List[BlockchainTokens]:
    """
    Возвращает все активные токены для указанной сети.

    Args:
        network (str): Название сети.

    Returns:
        List[BlockchainTokens]: Список активных токенов.
    """
    return BlockchainTokens.query.filter_by(
        network=network, is_active=True
    ).all()


def get_tracked_blockchain_tokens(
    user: User, network: str
) -> List[BlockchainTokens]:
    """
    Возвращает список активных токенов, отслеживаемых пользователем в сети.

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


def add_tracked_token(
    user: User, blockchain_token_id: int
) -> UserTrackedBlockchainToken:
    """
    Добавляет токен в список отслеживаемых пользователем.

    Args:
        user (User): Экземпляр пользователя.
        blockchain_token_id (int): ID токена в блокчейн базе.

    Returns:
        UserTrackedBlockchainToken: Созданная или существующая запись.
    """
    existing = UserTrackedBlockchainToken.query.filter_by(
        user_id=user.id, blockchain_token_id=blockchain_token_id
    ).first()
    if existing:
        return existing
    tracked = UserTrackedBlockchainToken(
        user_id=user.id, blockchain_token_id=blockchain_token_id
    )
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
        Exception: При ошибках удаления из БД.
    """
    tracked = UserTrackedBlockchainToken.query.filter_by(
        user_id=user.id, blockchain_token_id=blockchain_token_id
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


def get_tracked_balances(user: User, network: str) -> Dict[str, Decimal]:
    """
    Получает балансы всех отслеживаемых токенов пользователя в сети с помощью multicall.

    Args:
        user (User): Экземпляр пользователя.
        network (str): Название сети.

    Returns:
        Dict[str, Decimal]: Словарь {символ токена: баланс}.
    """
    wallet = Wallet.query.filter_by(user_id=user.id, network=network).first()
    if not wallet:
        return {}

    blockchain_tokens = get_tracked_blockchain_tokens(user, network)
    if not blockchain_tokens:
        return {}

    TokenClass = _get_token_class(network)
    w3 = TokenClass.get_web3()

    calls = []
    for token in blockchain_tokens:
        token_address = TokenClass.to_checksum(token.contract_address)
        # Запрос баланса токена для адреса пользователя
        calls.append(
            Call(
                token_address,
                [f"balanceOf(address)(uint256)", wallet.address],
                [[f"{token.symbol}.balance", None]],
            )
        )
        # Запрос количества десятичных знаков токена
        calls.append(
            Call(
                token_address,
                ["decimals()(uint8)"],
                [[f"{token.symbol}.decimals", None]],
            )
        )

    multi = Multicall(calls, _w3=w3)
    results = multi()

    balances = {}
    for token in blockchain_tokens:
        balance_raw = results.get(f"{token.symbol}.balance", 0) or 0
        decimals = results.get(f"{token.symbol}.decimals", 18) or 18
        balances[token.symbol] = Decimal(balance_raw) / (10**decimals)

    return balances


def get_blockchain_token_balance(
    user_address: str, token_contract_address: str, network: str
) -> Decimal:
    """
    Получает баланс конкретного токена пользователя через класс провайдера.

    Args:
        user_address (str): Адрес пользователя.
        token_contract_address (str): Адрес контракта токена.
        network (str): Название сети.

    Returns:
        Decimal: Баланс токена.
    """
    TokenClass = _get_token_class(network)
    return TokenClass.balance_of(token_contract_address, user_address)


def transfer_fee_table() -> Dict[str, Decimal]:
    """
    Загружает таблицу комиссий за перевод из базы.

    Raises:
        ValueError: Если для каких-то сетей отсутствуют данные по комиссии.

    Returns:
        Dict[str, Decimal]: Словарь {сеть: комиссия в USDT}.
    """
    fees = {r.network: Decimal(r.fee_usdt) for r in TransferFee.query.all()}
    missing = [net for net in NETWORKS if net not in fees]
    if missing:
        logger.error(f"Отсутствуют комиссии для сетей: {', '.join(missing)}")
        raise ValueError(
            f"Missing transfer fees for networks: {', '.join(missing)}"
        )
    return fees


def get_real_balance(user: User, network: str) -> Decimal:
    """
    Получает реальный баланс пользователя по сети через класс провайдера.

    Args:
        user (User): Экземпляр пользователя.
        network (str): Название сети.

    Returns:
        Decimal: Баланс пользователя.
    """
    wallet = next((w for w in user.wallets if w.network == network), None)
    if not wallet:
        return Decimal(0)
    TokenClass = _get_token_class(network, is_native_gas=True)
    return TokenClass.balance(wallet.address)


def user_balance_stub(user: User) -> Dict[str, Decimal]:
    """
    Возвращает псевдо-баланс пользователя, вычисленный из истории транзакций.

    Args:
        user (User): Экземпляр пользователя.

    Returns:
        Dict[str, Decimal]: Словарь {сеть_баланс: сумма}.
    """
    balances = {f"{net}_balance": Decimal(0) for net in NETWORKS}

    results = (
        db.session.query(
            Transaction.network,
            Transaction.type,
            func.coalesce(func.sum(Transaction.amount), 0),
        )
        .filter(
            Transaction.user_id == user.id,
            Transaction.network.in_(NETWORKS),
            Transaction.status == TxStatus.confirmed,
            Transaction.type.in_([TxType.deposit, TxType.withdraw]),
        )
        .group_by(Transaction.network, Transaction.type)
        .all()
    )

    for network, tx_type, amount_sum in results:
        key = f"{network}_balance"
        if tx_type == TxType.deposit:
            balances[key] += Decimal(amount_sum)
        elif tx_type == TxType.withdraw:
            balances[key] -= Decimal(amount_sum)

    return balances


def history(user: User) -> List[Transaction]:
    """
    Возвращает историю транзакций пользователя, отсортированную по дате (новые сверху).

    Args:
        user (User): Экземпляр пользователя.

    Returns:
        List[Transaction]: Список транзакций.
    """
    return (
        Transaction.query.filter_by(user_id=user.id)
        .order_by(Transaction.created_at.desc())
        .all()
    )


def balance_for(user: User, network: str) -> Decimal:
    """
    Возвращает псевдо-баланс пользователя по указанной сети.

    Args:
        user (User): Экземпляр пользователя.
        network (str): Название сети.

    Returns:
        Decimal: Баланс пользователя.
    """
    return user_balance_stub(user)[f"{network}_balance"]


@ledger(
    LedgerType.purchase,
    direction="out",
    network_from_arg="network",
    amount_from_arg="amount",
)
def debit(user: User, network: str, amount: Decimal) -> Transaction:
    """
    Списывает средства пользователя (операция покупки).

    Args:
        user (User): Экземпляр пользователя.
        network (str): Название сети.
        amount (Decimal): Сумма списания.

    Returns:
        Transaction: Созданная транзакция.
    """
    tx = Transaction(
        user_id=user.id,
        type=TxType.purchase,
        status=TxStatus.confirmed,
        network=network,
        amount=amount,
    )
    db.session.add(tx)
    db.session.commit()
    return tx


@ledger(
    LedgerType.withdraw,
    direction="out",
    network_from_arg="network",
    amount_from_arg="amount",
)
def withdraw_funds(
    user: User, network: str, amount: Decimal, dest: str, twofa_code: str
) -> Transaction:
    """
    Выводит средства пользователя из указанной сети на внешний адрес.

    Args:
        user (User): Экземпляр пользователя.
        network (str): Название сети.
        amount (Decimal): Сумма вывода.
        dest (str): Адрес получателя.
        twofa_code (str): Код двухфакторной аутентификации.

    Raises:
        ValueError: При неправильной сети, 2FA, недостаточном балансе или отсутствии кошелька.

    Returns:
        Transaction: Созданная транзакция вывода.
    """
    if network not in NETWORKS:
        raise ValueError(f"Unknown network: {network}")
    if twofa_code != "123456":
        raise ValueError("Invalid 2FA")

    fee_table = transfer_fee_table()
    fee = fee_table.get(network)
    if fee is None:
        raise ValueError(f"Transfer fee for network '{network}' not found.")

    total = amount + fee

    if balance_for(user, network) < total:
        raise ValueError("Insufficient balance")

    wallet = next((w for w in user.wallets if w.network == network), None)
    if not wallet:
        raise ValueError("Wallet not found")

    pk = Wallet.decrypt_pk(wallet.pk_enc)

    # Используем нативный токен газа для перечисленных сетей
    is_native = network in ("eth", "bnb", "trx")
    TokenClass = _get_token_class(network, is_native_gas=is_native)

    tx_hash = TokenClass.transfer(pk, dest, amount)

    tx = Transaction(
        user_id=user.id,
        type=TxType.withdraw,
        status=TxStatus.pending,
        network=network,
        amount=amount,
        fee=fee,
        address=dest,
    )
    db.session.add(tx)
    db.session.commit()
    logger.info(f"[WITHDRAW] {network} tx_hash={tx_hash}")
    return tx


def ref_balance(user: User) -> Decimal:
    """
    Возвращает текущий баланс реферальных средств пользователя.

    Args:
        user (User): Экземпляр пользователя.

    Returns:
        Decimal: Баланс реферала, 0 если отсутствует.
    """
    rb = ReferralBalance.query.get(user.id)
    return Decimal(rb.balance) if rb else Decimal(0)


def ref_credit(user_id: int, amount: Decimal) -> None:
    """
    Начисляет реферальные средства пользователю.

    Args:
        user_id (int): ID пользователя.
        amount (Decimal): Сумма для начисления.
    """
    rb = ReferralBalance.query.get(user_id)
    if not rb:
        rb = ReferralBalance(user_id=user_id, balance=amount)
        db.session.add(rb)
    else:
        rb.balance += amount
    db.session.flush()


@ledger(LedgerType.referral, direction="out")
def ref_debit(user: User, amount: Decimal) -> Transaction:
    """
    Списывает реферальные средства пользователя.

    Args:
        user (User): Экземпляр пользователя.
        amount (Decimal): Сумма списания.

    Raises:
        ValueError: Если недостаточно средств.

    Returns:
        Transaction: Созданная транзакция.
    """
    rb = ReferralBalance.query.get(user.id)
    if not rb or rb.balance < amount:
        raise ValueError("Not enough referral balance")

    rb.balance -= amount
    tx = Transaction(
        user_id=user.id,
        type=TxType.referral,
        status=TxStatus.confirmed,
        network="ref",
        amount=-amount,
    )
    db.session.add(tx)
    db.session.flush()
    return tx


@ledger(
    LedgerType.purchase,
    direction="out",
    network_from_arg="network",
    amount_from_arg="amount",
)
def credit_to_user_balance(
    user: User, network: str, amount: Decimal
) -> Transaction:
    """
    Начисляет средства пользователю (например, прибыль).

    Args:
        user (User): Экземпляр пользователя.
        network (str): Название сети.
        amount (Decimal): Сумма для начисления.

    Returns:
        Transaction: Созданная транзакция.
    """
    tx = Transaction(
        user_id=user.id,
        type=TxType.profit,
        status=TxStatus.confirmed,
        network=network,
        amount=amount,
    )
    db.session.add(tx)
    db.session.commit()
    return tx


def credit_to_network_balance(
    user_id: int, network: str, amount: Decimal
) -> None:
    """
    Начисляет средства на баланс сети пользователя.

    Args:
        user_id (int): ID пользователя.
        network (str): Название сети.
        amount (Decimal): Сумма для начисления.
    """
    tx = Transaction(
        user_id=user_id,
        type=TxType.deposit,
        status=TxStatus.confirmed,
        network=network,
        amount=amount,
    )
    db.session.add(tx)
    db.session.flush()
    db.session.add(
        LedgerEntry(
            user_id=user_id,
            origin_table="transactions",
            origin_id=tx.id,
            type=LedgerType.deposit,
            direction="in",
            network=network,
            amount=amount,
        )
    )
    db.session.commit()
