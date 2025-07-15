"""
onfine/services/wallet_service.py
--------------------------------
Высоко-уровневый сервис работы с кошельками и финансами пользователя:
* генерация trio-кошельков (ERC/BEP/TRC);
* хранение приватного ключа зашифрованным (Fernet);
* вывод средств (MVP-вариант: реальный вызов transfer + запись pending Tx);
* расчёт «псевдо-баланса» на основе подтверждённых депозитов/выводов;
* история транзакций.

Все публичные функции используются REST-namespace-ом
onfine/api/wallet_api.py.
"""

from __future__ import annotations

import logging
import os
from decimal import Decimal
from typing import Dict, List, Tuple

from multicall import Call, Multicall
from sqlalchemy import func
from web3 import Web3

from onfine.blockchain.token_abi_loder import abi_by_name
from onfine.models.blockchain_tokens import BlockchainTokens
from onfine.models.user_tracked_blockchain_tokens import (
    UserTrackedBlockchainToken,
)

from ..api.error_handlers import RegistrationError
from ..blockchain.providers import BEP20, ERC20, TRC20
from ..extensions import db
from ..models.ledger_entry import LedgerEntry
from ..models.referral_balance import ReferralBalance
from ..models.transactions import Transaction, TxStatus, TxType
from ..models.transfer_fee import TransferFee
from ..models.user import User
from ..models.wallet import Wallet
from ..utils.ledger_decorator import LedgerType, ledger

NETWORKS: Tuple[str, ...] = ("bep", "erc", "trc")

logger = logging.getLogger(__name__)


# ───────── helpers ─────────


def _gen_addr_pk(network: str) -> Tuple[str, str]:
    """
    Генерирует пару (адрес, приватный ключ) для заданной сети.

    Args:
        network (str): Сеть, для которой генерируется кошелёк ('erc', 'bep', 'trc').

    Returns:
        Tuple[str, str]: Кортеж из адреса и приватного ключа.

    Raises:
        ValueError: Если сеть неизвестна.
    """
    if network == "erc":
        return ERC20.generate_wallet()
    if network == "bep":
        return BEP20.generate_wallet()
    if network == "trc":
        return TRC20.generate_wallet()
    raise ValueError("Unknown network")


def _get_rpc_url(network: str) -> str:
    """
    Получает RPC URL для подключения к блокчейн-ноде по сети.

    Args:
        network (str): Сеть ('erc', 'bep', 'trc').

    Returns:
        str: RPC URL.

    Raises:
        ValueError: Если сеть неизвестна или переменная окружения не задана.
    """
    if network == "erc":
        url = os.getenv("ERC_INFURA_URL") or os.getenv("ERC_CHAIN_URL")
    elif network == "bep":
        url = os.getenv("BEP_RPC_URL") or os.getenv("BEP_BSC_URL")
    elif network == "trc":
        url = os.getenv("TRON_FULL_NODE")
    else:
        raise ValueError(f"Unknown network: {network}")

    if not url:
        raise ValueError(f"RPC URL для сети {network} не настроен")
    return url


def _get_web3_and_abi(network: str) -> Tuple[Web3, Dict[str, dict]]:
    """
    Создаёт объект Web3 и загружает ABI для функций balanceOf и decimals токена.

    Args:
        network (str): Сеть ('erc', 'bep', 'trc').

    Returns:
        Tuple[Web3, Dict[str, dict]]: Кортеж из объекта Web3 и словаря ABI.

    Raises:
        RuntimeError: Если ABI не найден.
        ValueError: Если RPC URL не настроен.
    """
    rpc_url = _get_rpc_url(network)
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    abi = abi_by_name()
    balance_of_abi = abi.get("balanceOf")
    decimals_abi = abi.get("decimals")
    if not balance_of_abi or not decimals_abi:
        raise RuntimeError("ABI для balanceOf или decimals не найден")
    return w3, {"balanceOf": balance_of_abi, "decimals": decimals_abi}


def _to_checksum(address: str) -> str:
    """
    Преобразует адрес в формат checksum Ethereum.

    Args:
        address (str): Адрес в любом регистре.

    Returns:
        str: Адрес в формате checksum.

    Raises:
        ValueError: Если адрес некорректен.
    """
    try:
        return Web3.toChecksumAddress(address)
    except Exception as e:
        logger.error(f"Invalid address {address}: {e}")
        raise ValueError(f"Invalid address: {address}")


def _get_blockchain_token_balance_from_contract(
    w3: Web3,
    token_address: str,
    user_address: str,
    balance_of_abi: dict,
    decimals_abi: dict,
) -> Decimal:
    """
    Получает баланс токена на адресе пользователя, используя контракт токена.

    Args:
        w3 (Web3): Объект Web3.
        token_address (str): Адрес токена (контракта).
        user_address (str): Адрес пользователя.
        balance_of_abi (dict): ABI функции balanceOf.
        decimals_abi (dict): ABI функции decimals.

    Returns:
        Decimal: Баланс токена с учётом десятичных знаков.

    Raises:
        RuntimeError: При ошибках вызова контракта.
    """
    token_address = _to_checksum(token_address)
    user_address = _to_checksum(user_address)
    contract = w3.eth.contract(
        address=token_address, abi=[balance_of_abi, decimals_abi]
    )
    try:
        balance_raw = contract.functions.balanceOf(user_address).call()
        decimals = contract.functions.decimals().call()
    except Exception as e:
        logger.error(f"Ошибка при получении баланса токена: {e}")
        raise RuntimeError(f"Ошибка при получении баланса токена: {e}")
    if decimals is None:
        decimals = 18
    return Decimal(balance_raw) / (10**decimals)


# ───────── wallet CRUD ─────────


def create_wallets(user: User) -> Dict[str, str]:
    """
    Создаёт кошельки для пользователя по всем поддерживаемым сетям,
    если они ещё не созданы.

    Args:
        user (User): Объект пользователя.

    Returns:
        Dict[str, str]: Словарь вида {network: address} с адресами кошельков.

    Raises:
        RegistrationError: При ошибках сохранения в БД.
        ValueError: Если неизвестна сеть.
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
                    pk_enc=Wallet.encrypt_pk(pk),
                )
                db.session.add(w)
                existing[net] = addr
            except ValueError as e:
                logger.error(
                    f"Ошибка при создании кошелька для сети {net}: {str(e)}"
                )
                raise

    try:
        if db.session.new or db.session.dirty:
            db.session.commit()
    except Exception as e:
        logger.error(
            f"Ошибка при сохранении кошельков в базе данных: {str(e)}"
        )
        raise RegistrationError(
            "Ошибка при сохранении кошельков в базе данных."
        )

    return existing


def list_wallets(user: User) -> Dict[str, str] | None:
    """
    Возвращает адреса всех кошельков пользователя.

    Args:
        user (User): Объект пользователя.

    Returns:
        Dict[str, str] | None: Словарь {network: address} или None, если кошельков нет.
    """
    rows = {w.network: w.address for w in user.wallets}
    return rows or None


# --- Работа с отслеживаемыми токенами ---


def get_all_active_blockchain_tokens(
    network: str,
) -> List[BlockchainTokens]:
    """
    Получает список всех активных токенов для указанной сети.

    Args:
        network (str): Название или идентификатор блокчейн-сети (например, 'erc20', 'bsc').

    Returns:
        List[BlockchainTokens]: Список объектов BlockchainTokens, которые активны в указанной сети.
    """
    return BlockchainTokens.query.filter_by(
        network=network, is_active=True
    ).all()


def get_tracked_blockchain_tokens(
    user: User, network: str
) -> List[BlockchainTokens]:
    """
    Получает список токенов, которые пользователь отслеживает в указанной сети.

    Args:
        user (User): Пользователь.
        network (str): Сеть ('erc', 'bep', 'trc').

    Returns:
        List[BlockchainTokens]: Список токенов.
    """
    blockchain_tokens = (
        BlockchainTokens.query.join(
            UserTrackedBlockchainToken,
            BlockchainTokens.id
            == UserTrackedBlockchainToken.blockchain_token_id,
        )
        .filter(
            UserTrackedBlockchainToken.user_id == user.id,
            BlockchainTokens.network == network,
            BlockchainTokens.is_active.is_(True),
        )
        .all()
    )
    return blockchain_tokens


def add_tracked_token(
    user: User, blockchain_token_id: int
) -> UserTrackedBlockchainToken:
    """
    Добавляет токен в список отслеживаемых пользователем.

    Args:
        user (User): Пользователь.
        blockchain_token_id (int): ID токена.

    Returns:
        UserTrackedBlockchainToken: Объект отслеживания токена.
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
        user (User): Пользователь.
        blockchain_token_id (int): ID токена для удаления.

    Returns:
        bool: True, если токен был удалён, False если токен не найден в списке.

    Raises:
        Exception: При ошибках удаления из базы данных.
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
        logger.error(f"Ошибка при удалении отслеживаемого токена: {e}")
        raise

    return True


def get_tracked_balances(user: User, network: str) -> Dict[str, Decimal]:
    """
    Получает балансы всех отслеживаемых токенов пользователя в указанной сети.

    Используется multicall для оптимизации запросов.

    Args:
        user (User): Пользователь.
        network (str): Сеть ('erc', 'bep', 'trc').

    Returns:
        Dict[str, Decimal]: Словарь {символ_токена: баланс}.
    """
    w3, abi = _get_web3_and_abi(network)

    wallet = Wallet.query.filter_by(user_id=user.id, network=network).first()
    if not wallet:
        return {}

    blockchain_tokens = get_tracked_blockchain_tokens(
        user, network
    )
    if not blockchain_tokens:
        return {}

    balance_of_abi = abi["balanceOf"]
    decimals_abi = abi["decimals"]

    calls = []
    for token in blockchain_tokens:
        token_address = _to_checksum(token.contract_address)
        # Запрос баланса
        calls.append(
            Call(
                token_address,
                [
                    f"{balance_of_abi['name']}(address)(uint256)",
                    wallet.address,
                ],
                [[f"{token.symbol}.balance", None]],
            )
        )
        # Запрос decimals
        calls.append(
            Call(
                token_address,
                [f"{decimals_abi['name']}()(uint8)"],
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
    user_address: str,
    token_contract_address: str,
    network: str,
) -> Decimal:
    """
    Получает баланс конкретного токена у пользователя.

    Args:
        user_address (str): Адрес пользователя.
        token_contract_address (str): Адрес токена (контракта).
        network (str): Сеть ('erc', 'bep', 'trc').

    Returns:
        Decimal: Баланс токена.
    """
    w3, abi = _get_web3_and_abi(network)
    balance_of_abi = abi["balanceOf"]
    decimals_abi = abi["decimals"]
    return _get_blockchain_token_balance_from_contract(
        w3,
        token_contract_address,
        user_address,
        balance_of_abi,
        decimals_abi,
    )


# ───────── fees / balance ─────────


def transfer_fee_table() -> Dict[str, Decimal]:
    """
    Загружает таблицу комиссий за перевод для всех сетей.

    Returns:
        Dict[str, Decimal]: Словарь {network: fee_usdt}.

    Raises:
        ValueError: Если отсутствуют комиссии для каких-либо сетей.
    """
    fees = {r.network: Decimal(r.fee_usdt) for r in TransferFee.query.all()}
    missing_networks = [net for net in NETWORKS if net not in fees]

    if missing_networks:
        logger.error(
            f"Отсутствуют комиссии за перевод для сетей: {', '.join(missing_networks)}"
        )
        raise ValueError(
            f"Missing transfer fees for networks: {', '.join(missing_networks)}"
        )

    return fees


def get_real_balance(user: User, network: str) -> Decimal:
    """
    Получает актуальный баланс пользователя в указанной сети, обращаясь к провайдеру.

    Args:
        user (User): Пользователь.
        network (str): Сеть ('erc', 'bep', 'trc').

    Returns:
        Decimal: Баланс.
    """
    wallet = next((w for w in user.wallets if w.network == network), None)
    if not wallet:
        return Decimal(0)

    if network == "trc":
        return TRC20.balance(wallet.address)
    if network == "erc":
        return ERC20.balance(wallet.address)
    if network == "bep":
        return BEP20.balance(wallet.address)
    raise ValueError(f"Unknown network: {network}")


def user_balance_stub(user: User) -> Dict[str, Decimal]:
    """
    Получает баланс пользователя из истории транзакций (депозиты и выводы).

    Args:
        user (User): Пользователь.

    Returns:
        Dict[str, Decimal]: Балансы по сетям {'erc_balance': ..., 'bep_balance': ..., 'trc_balance': ...}
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


# ───────── history ─────────


def history(user: User) -> List[Transaction]:
    """
    Получает историю всех транзакций пользователя, отсортированную по дате (сначала новые).

    Args:
        user (User): Пользователь.

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
    Получает баланс пользователя в указанной сети из истории транзакций.

    Args:
        user (User): Пользователь.
        network (str): Сеть.

    Returns:
        Decimal: Баланс.
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
    Списывает средства пользователя (например, при покупке).

    Args:
        user (User): Пользователь.
        network (str): Сеть.
        amount (Decimal): Сумма.

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
    user: User,
    network: str,
    amount: Decimal,
    dest: str,
    twofa_code: str,
) -> Transaction:
    """
    Выполняет вывод средств пользователя из указанной сети на внешний адрес.

    Args:
        user (User): Пользователь.
        network (str): Сеть ('erc', 'bep', 'trc').
        amount (Decimal): Сумма вывода.
        dest (str): Адрес получателя.
        twofa_code (str): Код 2FA для подтверждения.

    Returns:
        Transaction: Созданная транзакция вывода.

    Raises:
        ValueError: При недостаточном балансе, неверном 2FA или других ошибках.
    """
    if network not in NETWORKS:
        raise ValueError(f"Unknown network: {network}")
    if twofa_code != "123456":
        raise ValueError("Invalid 2FA")

    try:
        fee = transfer_fee_table()[network]
    except KeyError:
        raise ValueError(f"Transfer fee for network '{network}' not found.")

    total = amount + fee

    if balance_for(user, network) < total:
        raise ValueError("Insufficient balance")

    wallet = next((w for w in user.wallets if w.network == network), None)
    if not wallet:
        raise ValueError("Wallet not found")

    pk = Wallet.decrypt_pk(wallet.pk_enc)

    tx_hash = {
        "erc": lambda: ERC20.transfer(pk, dest, amount),
        "bep": lambda: BEP20.transfer(pk, dest, amount),
        "trc": lambda: TRC20.transfer(pk, dest, amount),
    }[network]()

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
    logger.info(f"[WITHDRAW] {network} hash={tx_hash}")
    return tx


def ref_balance(user: User) -> Decimal:
    """
    Получает баланс реферальных средств пользователя.

    Args:
        user (User): Пользователь.

    Returns:
        Decimal: Баланс рефералов.
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


@ledger(LedgerType.referral, direction="out")  # отрицательное списание
def ref_debit(user: User, amount: Decimal) -> Transaction:
    """
    Списывает реферальные средства пользователя.

    Args:
        user (User): Пользователь.
        amount (Decimal): Сумма списания.

    Returns:
        Transaction: Транзакция списания.

    Raises:
        ValueError: Если недостаточно средств.
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
    user: User,
    network: str,
    amount: Decimal,
) -> Transaction:
    """
    Начисляет средства пользователю (например, прибыль).

    Args:
        user (User): Пользователь.
        network (str): Сеть.
        amount (Decimal): Сумма.

    Returns:
        Transaction: Транзакция начисления.
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
    user_id: int,
    network: str,
    amount: Decimal,
) -> None:
    """
    Начисляет средства пользователю в указанной сети (депозит).

    Args:
        user_id (int): ID пользователя.
        network (str): Сеть.
        amount (Decimal): Сумма.
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
        ),
    )
    db.session.commit()
