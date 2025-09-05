"""
Сервис управления криптовалютными кошельками, балансами и транзакциями пользователей.

Основные функции:
- Создание кошельков пользователя для поддерживаемых сетей (ERC20, BEP20, TRC20) с генерацией адресов и шифрованием приватных ключей.
- Получение списка кошельков пользователя.
- Получение балансов отслеживаемых пользователем токенов с использованием multicall, если сеть это поддерживает.
- Получение баланса конкретного токена пользователя через провайдер.
- Управление операциями списания, вывода средств, начисления и работы с реферальными балансами (закомментировано в коде).
- Логирование ключевых операций и ошибок.

Константы:
- SUPPORTED_NETWORKS: Кортеж поддерживаемых сетей.
- NATIVE_TOKENS: Сопоставление сети и нативного токена газа.

Ключевые функции:

_gen_addr_pk(network: str) -> Tuple[str, str]
    Генерирует пару (адрес, приватный ключ) для заданной сети через провайдера.

create_wallets(user: User, networks: List[str]) -> Dict[str, str]
    Создаёт кошельки пользователя для указанных сетей, если их ещё нет,
    шифрует приватные ключи и сохраняет в базу.

list_wallets(user: User) -> Optional[Dict[str, str]]
    Возвращает словарь адресов кошельков пользователя по сетям или None, если кошельков нет.

get_tracked_balances(user: User, network: str) -> Dict[str, Decimal]
    Получает балансы всех отслеживаемых токенов пользователя в сети.
    Использует multicall для оптимизации запросов, если провайдер и сеть поддерживают.

get_blockchain_token_balance(user_address: str, network: str, token_contract_address: Optional[str]) -> Decimal
    Возвращает баланс конкретного токена пользователя через провайдера.
    Если token_contract_address не указан, возвращает баланс нативного токена сети.

Закомментированные функции (в коде) включают:
- transfer_fee_table: загрузка таблицы комиссий за переводы.
- get_balance: получение баланса пользователя по токену.
- user_balance_stub: вычисление псевдо-баланса по истории транзакций.
- history: получение истории транзакций пользователя.
- balance_for: получение псевдо-баланса по сети.
- debit, withdraw_funds, ref_balance, ref_credit, ref_debit, credit_to_user_balance, credit_to_network_balance:
  операции списания, вывода, работы с реферальными балансами и начислениями.

Исключения:
- ValueError при ошибках валидации, недостаточном балансе, неверном 2FA-коде.
- Exception при ошибках работы с базой данных или провайдерами.

Логирование:
- Ошибки создания кошельков и сохранения в БД.
- Информационные сообщения при операциях вывода средств (в закомментированных функциях).
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from multicall import Call, Multicall
from web3.exceptions import ContractLogicError

from onfine.blockchain.providers import (
    ProviderManager,
)
from onfine.extensions import db
from onfine.models.user import User
from onfine.models.wallet import Wallet
from onfine.services.token_service import get_tracked_blockchain_tokens

logger = logging.getLogger(__name__)

# Определяем сети и соответствующие нативные токены газа
SUPPORTED_NETWORKS: Tuple[str, ...] = ("erc20", "bep20", "trc20")
NATIVE_TOKENS: Dict[str, str] = {
    "erc20": "eth",
    "bep20": "bnb",
    "trc20": "trx",
}


def _gen_addr_pk(network: str) -> Tuple[str, str]:
    """
    Генерирует пару (адрес, приватный ключ) для заданной сети.

    Args:
        network (str): Название сети.

    Returns:
        Tuple[str, str]: Кортеж (адрес, незашифрованный приватный ключ).
    """
    provider = ProviderManager.get(network)
    return provider.generate_wallet()


def create_wallets(user: User, networks: List[str]) -> Dict[str, str]:
    """
    Создаёт кошельки пользователя для указанных сетей, если их ещё нет.

    Args:
        user (User): Экземпляр пользователя.
        networks (List[str]): Список названий сетей.

    Raises:
        Exception: При ошибках создания кошельков или сохранения в БД.

    Returns:
        Dict[str, str]: Словарь с ключами — названия сетей, значениями — адреса кошельков.
    """
    existing = {w.network: w.address for w in user.wallets}

    for net in networks:
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
        Optional[Dict[str, str]]: Словарь с ключами — названия сетей, значениями — адреса кошельков,
            либо None, если кошельков нет.
    """
    wallets = {w.network: w.address for w in user.wallets}
    return wallets or None


def get_tracked_balances(user: User, network: str) -> Dict[str, Decimal]:
    """
    Получает балансы всех отслеживаемых токенов пользователя в сети с использованием multicall, если это поддерживается.

    Args:
        user (User): Экземпляр пользователя.
        network (str): Название сети.

    Returns:
        Dict[str, Decimal]: Словарь с ключами — символы токенов, значениями — балансы.
            Пустой словарь, если кошелька или токенов нет.
    """
    wallet = Wallet.query.filter_by(user_id=user.id, network=network).first()
    if not wallet:
        return {}

    blockchain_tokens = get_tracked_blockchain_tokens(user, network)
    if not blockchain_tokens:
        return {}

    provider = ProviderManager.get(network)
    balances: Dict[str, Decimal] = {}

    def _normalize(raw: int | str, decimals: int) -> Decimal:
        try:
            iv = int(raw)
        except Exception:
            iv = 0
        scale = Decimal(10) ** int(decimals)
        return Decimal(iv) / scale

    if provider.supports_multicall():
        w3 = provider.get_web3()
        calls = []

        for t in blockchain_tokens:
            if t.is_native_gas:
                continue
            provider = ProviderManager.get(network.lower(), contract_addr=t.contract_address)
            calls.append(
                Call(
                    provider.contract_addr,
                    ["balanceOf(address)(uint256)", wallet.address],
                    [[f"{t.contract_address}.balance", None]],
                ),
            )

        try:
            multi = Multicall(calls, _w3=w3)
            results = multi()
        except Exception:
            results = None

        # сначала нативный газ
        for t in blockchain_tokens:
            if t.is_native_gas:
                balances[t.symbol] = provider.balance_native(wallet.address)

        if results is not None:
            # нормализуем по decimals из ваших метаданных
            for t in blockchain_tokens:
                if t.is_native_gas:
                    continue
                raw = results.get(f"{t.contract_address}.balance", 0) or 0
                balances[t.symbol] = _normalize(raw, getattr(t, "decimals", 18))
            return balances

    for t in blockchain_tokens:
        try:
            instance = ProviderManager.get(network.lower(), contract_addr=t.contract_address)
            if t.is_native_gas:
                bal = instance.balance_native(wallet.address)
                balances[t.symbol] = Decimal(bal)
            else:
                bal = instance.balance(wallet.address)
                if not isinstance(bal, Decimal):
                    bal = _normalize(bal, getattr(t, "decimals", 18))
                balances[t.symbol] = Decimal(bal)
        except (ContractLogicError, ValueError):
            continue
        except Exception:
            continue

    return balances


def get_blockchain_token_balance(
    user_address: str,
    network: str,
    token_contract_address: Optional[str] = None,
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
    provider = ProviderManager.get(network=network, contract_addr=token_contract_address)
    if not token_contract_address:
        return provider.balance_native(user_address)

    return provider.balance(user_address)


# def transfer_fee_table() -> Dict[str, Decimal]:
#     """
#     Загружает таблицу комиссий за перевод из базы данных.

#     Raises:
#         ValueError: Если для каких-то токенов отсутствуют данные по комиссии.

#     Returns:
#         Dict[str, Decimal]: Словарь с ключами — названия токенов, значениями — комиссии в USDT.
#     """
#     fees = {r.network: Decimal(r.fee_usdt) for r in TransferFee.query.all()}
#     missing = [token for token in NATIVE_TOKENS.values() if token not in fees]
#     if missing:
#         logger.error(f"Отсутствуют комиссии для токенов: {', '.join(missing)}")
#         raise ValueError(f"Missing transfer fees for native tokens: {', '.join(missing)}")
#     return fees


# def get_balance(user: User, network: str, token_symbol: Optional[str] = None) -> Decimal:
#     """
#     Получает баланс пользователя в указанной сети через класс провайдера.

#     Args:
#         user (User): Экземпляр пользователя.
#         network (str): Название сети.
#         token_symbol (Optional[str]): Символ токена (если None — баланс нативного токена).

#     Returns:
#         Decimal: Баланс пользователя.
#     """
#     wallet = next((w for w in user.wallets if w.network == network), None)
#     if not wallet:
#         return Decimal(0)
#     TokenClass = _get_token_class(network)
#     return TokenClass.balance(wallet.address, token_symbol)


# def user_balance_stub(user: User) -> Dict[str, Decimal]:
#     """
#     Вычисляет псевдо-баланс пользователя на основе истории подтверждённых транзакций.

#     Args:
#         user (User): Экземпляр пользователя.

#     Returns:
#         Dict[str, Decimal]: Словарь с ключами в формате "{сеть}_balance" и значениями — суммами балансов.
#     """
#     balances = {f"{net}_balance": Decimal(0) for net in SUPPORTED_NETWORKS}

#     results = (
#         db.session.query(
#             Transaction.network,
#             Transaction.type,
#             func.coalesce(func.sum(Transaction.amount), 0),
#         )
#         .filter(
#             Transaction.user_id == user.id,
#             Transaction.network.in_(SUPPORTED_NETWORKS),
#             Transaction.status == TxStatus.confirmed,
#             Transaction.type.in_([TxType.deposit, TxType.withdraw]),
#         )
#         .group_by(Transaction.network, Transaction.type)
#         .all()
#     )

#     for network, tx_type, amount_sum in results:
#         key = f"{network}_balance"
#         if tx_type == TxType.deposit:
#             balances[key] += Decimal(amount_sum)
#         elif tx_type == TxType.withdraw:
#             balances[key] -= Decimal(amount_sum)

#     return balances


# def history(user: User) -> List[Transaction]:
#     """
#     Возвращает историю транзакций пользователя, отсортированную по дате от новых к старым.

#     Args:
#         user (User): Экземпляр пользователя.

#     Returns:
#         List[Transaction]: Список транзакций пользователя.
#     """
#     return Transaction.query.filter_by(user_id=user.id).order_by(Transaction.created_at.desc()).all()


# def balance_for(user: User, network: str) -> Decimal:
#     """
#     Возвращает псевдо-баланс пользователя по указанной сети.

#     Args:
#         user (User): Экземпляр пользователя.
#         network (str): Название сети.

#     Returns:
#         Decimal: Баланс пользователя.
#     """
#     return user_balance_stub(user)[f"{network}_balance"]


# @ledger(
#     LedgerType.purchase,
#     direction="out",
#     network_from_arg="network",
#     amount_from_arg="amount",
# )
# def debit(user: User, network: str, amount: Decimal) -> Transaction:
#     """
#     Списывает средства пользователя (операция покупки).

#     Args:
#         user (User): Экземпляр пользователя.
#         network (str): Название сети.
#         amount (Decimal): Сумма списания.

#     Returns:
#         Transaction: Созданная транзакция списания.
#     """
#     tx = Transaction(
#         user_id=user.id,
#         type=TxType.purchase,
#         status=TxStatus.confirmed,
#         network=network,
#         amount=amount,
#     )
#     db.session.add(tx)
#     db.session.commit()
#     return tx


# @ledger(
#     LedgerType.withdraw,
#     direction="out",
#     network_from_arg="network",
#     amount_from_arg="amount",
# )
# def withdraw_funds(user: User, network: str, amount: Decimal, dest: str, twofa_code: str) -> Transaction:
#     """
#     Выполняет вывод средств пользователя из указанной сети на внешний адрес.

#     Args:
#         user (User): Экземпляр пользователя.
#         network (str): Название сети.
#         amount (Decimal): Сумма вывода.
#         dest (str): Адрес получателя.
#         twofa_code (str): Код двухфакторной аутентификации.

#     Raises:
#         ValueError: При неизвестной сети, неверном 2FA-коде, недостаточном балансе или отсутствии кошелька.

#     Returns:
#         Transaction: Созданная транзакция вывода.
#     """
#     if network not in SUPPORTED_NETWORKS:
#         raise ValueError(f"Unknown network: {network}")
#     if twofa_code != "123456":
#         raise ValueError("Invalid 2FA-code")

#     native_token = NATIVE_TOKENS.get(network)
#     if native_token is None:
#         raise ValueError(f"No native token defined for network '{network}'")

#     fee_table = transfer_fee_table()
#     fee = fee_table.get(native_token)
#     if fee is None:
#         raise ValueError(f"Transfer fee for token '{native_token}' not found.")

#     total = amount + fee

#     if balance_for(user, network) < total:
#         raise ValueError("Insufficient balance")

#     wallet = next((w for w in user.wallets if w.network == network), None)
#     if not wallet:
#         raise ValueError("Wallet not found")

#     pk = Wallet.decrypt_pk(wallet.pk_enc)

#     # Используем класс нативного токена газа для перевода
#     TokenClass = _get_token_class(network, is_native_gas=True)

#     tx_hash = TokenClass.transfer(pk, dest, amount)

#     tx = Transaction(
#         user_id=user.id,
#         type=TxType.withdraw,
#         status=TxStatus.pending,
#         network=network,
#         amount=amount,
#         fee=fee,
#         address=dest,
#     )
#     db.session.add(tx)
#     db.session.commit()
#     logger.info(f"[WITHDRAW] {network} tx_hash={tx_hash}")
#     return tx


# @ledger(
#     LedgerType.purchase,
#     direction="out",
#     network_from_arg="network",
#     amount_from_arg="amount",
# )
# def credit_to_user_balance(user: User, network: str, amount: Decimal) -> Transaction:
#     """
#     Начисляет средства пользователю (например, прибыль).

#     Args:
#         user (User): Экземпляр пользователя.
#         network (str): Название сети.
#         amount (Decimal): Сумма для начисления.

#     Returns:
#         Transaction: Созданная транзакция начисления.
#     """
#     tx = Transaction(
#         user_id=user.id,
#         type=TxType.profit,
#         status=TxStatus.confirmed,
#         network=network,
#         amount=amount,
#     )
#     db.session.add(tx)
#     db.session.commit()
#     return tx


# def credit_to_network_balance(user_id: int, network: str, amount: Decimal) -> None:
#     """
#     Начисляет средства на баланс пользователя в указанной сети.

#     Args:
#         user_id (int): ID пользователя.
#         network (str): Название сети.
#         amount (Decimal): Сумма для начисления.
#     """
#     tx = Transaction(
#         user_id=user_id,
#         type=TxType.deposit,
#         status=TxStatus.confirmed,
#         network=network,
#         amount=amount,
#     )
#     db.session.add(tx)
#     db.session.flush()
#     db.session.add(
#         LedgerEntry(
#             user_id=user_id,
#             origin_table="transactions",
#             origin_id=tx.id,
#             type=LedgerType.deposit,
#             direction="in",
#             network=network,
#             amount=amount,
#         ),
#     )
#     db.session.commit()
