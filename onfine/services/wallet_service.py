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
from decimal import Decimal
from threading import Lock
import time
from typing import Dict, List

from sqlalchemy import func

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

NETWORKS: tuple[str, ...] = ("bep", "erc", "trc")


logger = logging.getLogger(__name__)


# ───────── helpers
def _gen_addr_pk(network: str) -> tuple[str, str]:
    """
    Генерирует адрес и приватный ключ для заданной сети.

    Функция создает новый адрес и соответствующий приватный ключ в зависимости от
    указанной сети. Поддерживаются сети ERC20, BEP20 и TRC20.

    Args:
    ----------
    network : str
        Название сети, для которой необходимо сгенерировать адрес и приватный ключ.

    Return:
    ----------
    tuple[str, str]
        Кортеж, содержащий сгенерированный адрес и приватный ключ.

    Exceptions:
    -----------
    ValueError
        Если указана неизвестная сеть.
    """
    if network == "erc":
        return ERC20.generate_wallet()
    if network == "bep":
        return BEP20.generate_wallet()
    if network == "trc":
        return TRC20.generate_wallet()

    raise ValueError("Unknown network")


# ───────── wallet CRUD
def create_wallets(user: User) -> Dict[str, str]:
    """
    Создать кошельки для пользователя во всех сетях из NETWORKS, отсутствующих у него.

    Проверяет, какие кошельки уже существуют у пользователя, и для
    отсутствующих сетей генерирует новые адреса и зашифрованные приватные ключи.
    Созданные кошельки добавляются в сессию базы данных и сохраняются.

    Args:
    ----------
    user : User
        Объект пользователя, для которого создаются кошельки.

    Return:
    ----------
    Dict[str, str]
        Словарь с сетями в качестве ключей и соответствующими адресами кошельков.

    Exceptions:
    -----------
    ValueError
        Если произошла ошибка при генерации адреса или приватного ключа для сети.
    RegistrationError
        Если произошла ошибка при сохранении новых кошельков в базе данных.
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
    Получить словарь с адресами кошельков пользователя по сетям.

    Формирует словарь, где ключ — название сети, а значение —
    адрес кошелька пользователя в этой сети. Если у пользователя нет
    ни одного кошелька, Возвращается None.

    Args:
    ----------
    user : User
        Объект пользователя, для которого извлекаются кошельки.

    Return:
    ----------
    Dict[str, str] | None
        Словарь с сетями и соответствующими адресами кошельков пользователя,
        либо None, если кошельков нет.
    """
    rows = {w.network: w.address for w in user.wallets}
    return rows or None


# ───────── fees / balance

# Кеш: ключ - user_id, значение - (timestamp, balances)
_balance_cache: dict[int, tuple[float, dict[str, Decimal]]] = {}
_cache_lock = Lock()
_CACHE_TTL = 30  # кеш хранится 30 секунд


def invalidate_balance_cache(user_id: int):
    """Сброс кэша баланса"""
    with _cache_lock:
        if user_id in _balance_cache:
            del _balance_cache[user_id]


def transfer_fee_table() -> Dict[str, Decimal]:
    """
    Получить таблицу комиссий за переводы для всех сетей.

    Извлекает из базы данных комиссии за переводы (в USDT) для сетей,
    перечисленных в константе NETWORKS. Возвращается словарь, где ключ —
    название сети, а значение — комиссия в виде Decimal.

    Return:
    ----------
    Dict[str, Decimal]
        Словарь с комиссиями за переводы по сетям.

    Exceptions:
    -----------
    ValueError
        Если отсутствуют комиссии для одной или нескольких сетей из NETWORKS.
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
    Получить реальный баланс пользователя из блокчейна для указанной сети.

    Args:
        user (User): Пользователь.
        network (str): Сеть ('erc', 'bep', 'trc').

    Returns:
        Decimal: Баланс пользователя в сети.
    """
    if network == "trc":
        wallet = next((w for w in user.wallets if w.network == "trc"), None)
        if not wallet:
            return Decimal(0)
        return TRC20.balance(wallet.address)
    if network == "erc":
        wallet = next((w for w in user.wallets if w.network == "erc"), None)
        if not wallet:
            return Decimal(0)
        return ERC20.balance(wallet.address)
    if network == "bep":
        wallet = next((w for w in user.wallets if w.network == "bep"), None)
        if not wallet:
            return Decimal(0)
        return BEP20.balance(wallet.address)
    raise ValueError(f"Unknown network: {network}")


def user_balance_stub(user: User) -> Dict[str, Decimal]:
    """
    Рассчитывает баланс пользователя для каждой сети с кешированием.

    Функция суммирует подтвержденные транзакции пользователя (депозиты и выводы)
    для каждой сети из списка NETWORKS, формируя баланс как разницу между суммами
    депозитов и выводов. Результат кешируется на короткий промежуток времени (_CACHE_TTL),
    чтобы снизить нагрузку на базу при частых запросах.

    При ошибках запроса к базе данных или конвертации данных функция не ломается,
    возвращая текущий рассчитанный (возможно пустой) баланс, а кеш обновляется
    только при успешном выполнении.

    Args:
    ----------
    user : User
        Объект пользователя, для которого необходимо рассчитать баланс.

    Returns:
    ----------
    Dict[str, Decimal]
        Словарь с ключами вида "<название_сети>_balance" и значениями балансов
        пользователя по каждой сети.

    Примечания:
    ----------
    - Кеш реализован через глобальный словарь _balance_cache с блокировкой _cache_lock
      для потокобезопасности.
    - Время жизни кеша определяется константой _CACHE_TTL (в секундах).
    - Возвращается копия словаря балансов, чтобы избежать внешних изменений кеша.
    - При возникновении ошибок в запросе или подсчёте баланс возвращается без обновления кеша,
      а ошибка логируется.
    """
    now = time.time()
    with _cache_lock:
        cached = _balance_cache.get(user.id)
        if cached:
            timestamp, balances = cached
            # Если кеш ещё актуален - возвращаем копию, чтобы избежать мутаций
            if now - timestamp < _CACHE_TTL:
                return balances.copy()

    # Если кеш отсутствует или устарел - пересчитываем баланс
    balances = {f"{net}_balance": Decimal(0) for net in NETWORKS}

    try:
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

        # Обновляем кеш только после успешного подсчёта
        with _cache_lock:
            _balance_cache[user.id] = (now, balances.copy())

    except Exception as e:
        # Логируем ошибку, возвращаем текущий (возможно пустой) баланс без обновления кеша
        import logging

        logger = logging.getLogger(__name__)
        logger.error(
            f"Ошибка при подсчёте баланса пользователя {user.id}: {e}"
        )

    return balances.copy()


# ───────── history
def history(user: User) -> List[Transaction]:
    """
    Получить историю транзакций пользователя.

    Извлекает все транзакции, связанные с указанным пользователем,
    сортируя их по времени создания в порядке убывания. Возвращается
    список объектов Transaction.

    Args:
    ----------
    user : User
        Объект пользователя, для которого извлекается история транзакций.

    Return:
    ----------
    List[Transaction]
        Список транзакций пользователя, отсортированных по времени создания.
    """
    return (
        Transaction.query.filter_by(user_id=user.id)
        .order_by(Transaction.created_at.desc())
        .all()
    )


def balance_for(user: User, network: str) -> Decimal:
    """
    Получить баланс пользователя для указанной сети.

    Возвращает баланс пользователя в заданной сети, используя
    вспомогательную функцию user_balance_stub, которая возвращает словарь
    с балансами по сетям. Ключ словаря формируется как '{network}_balance'.

    Args:
    ----------
    user : User
        Объект пользователя, для которого запрашивается баланс.
    network : str
        Название сети, для которой требуется получить баланс.

    Return:
    ----------
    Decimal
        Баланс пользователя в указанной сети.

    Exceptions:
    -----------
    KeyError
        Если баланс для указанной сети отсутствует в словаре,
        возвращаемом user_balance_stub.
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
    Дебетует указанную сумму с баланса пользователя.

    Создает новую транзакцию типа "покупка" для
    указанного пользователя,уменьшая его баланс на заданную сумму.
    Транзакция сохраняется в базе данных
    и возвращается объект Transaction.

    Args:
    ----------
    user : User
        Объект пользователя, с баланса которого будет списана сумма.
    network : str
        Название сети, в которой производится дебетование.
    amount : Decimal
        Сумма, которую необходимо дебетовать.

    Return:
    ----------
    Transaction
        Объект созданной транзакции.
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
    invalidate_balance_cache(user.id)  # сбрасываем кэш баланса
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
    Инициирует вывод средств пользователя на указанный адрес.

    Функция выполняет следующие шаги:
    - Проверяет, что указанная сеть поддерживается.
    - Проверяет корректность кода двухфакторной аутентификации (2FA).
    - Получает комиссию за перевод для выбранной сети.
    - Проверяет достаточность псевдо-баланса пользователя с использованием кеша.
    - При необходимости запрашивает реальный баланс из блокчейна и обновляет кеш.
    - Проверяет, что реальный баланс достаточен для вывода с учётом комиссии.
    - Находит кошелёк пользователя для выбранной сети и расшифровывает приватный ключ.
    - Выполняет транзакцию перевода средств через соответствующий провайдер сети.
    - Создаёт и сохраняет транзакцию со статусом "pending".
    - Инвалидирует кеш баланса пользователя после успешного создания транзакции.

    Args:
        user (User): Пользователь, инициирующий вывод средств.
        network (str): Название сети ('erc', 'bep', 'trc') для вывода.
        amount (Decimal): Сумма для вывода.
        dest (str): Адрес назначения для перевода средств.
        twofa_code (str): Код двухфакторной аутентификации для подтверждения операции.

    Returns:
        Transaction: Объект созданной транзакции вывода средств.

    Raises:
        ValueError: В случае, если:
            - Сеть не поддерживается.
            - Код 2FA некорректен.
            - Комиссия для сети не найдена.
            - Баланс недостаточен для вывода с учётом комиссии.
            - Кошелёк пользователя для сети не найден.
    """
    # Проверяем, что сеть поддерживается
    if network not in NETWORKS:
        raise ValueError(f"Unknown network: {network}")

    # Проверяем корректность кода 2FA
    if twofa_code != "123456":  # TODO: заменить на реальную проверку
        raise ValueError("Invalid 2FA")

    # Получаем комиссию за перевод для выбранной сети
    try:
        fee = transfer_fee_table()[network]
    except KeyError:
        raise ValueError(f"Transfer fee for network '{network}' not found.")

    total = amount + fee

    now = time.time()
    # Проверяем кешированный баланс и время кеша для оптимизации вызова реального баланса
    with _cache_lock:
        cached = _balance_cache.get(user.id)
        if cached:
            timestamp, balances = cached
            balance = balances.get(f"{network}_balance", Decimal(0))
            cache_age = now - timestamp
        else:
            balance = Decimal(0)
            cache_age = None

    # Решаем, когда запрашивать реальный баланс
    need_real_check = False
    if balance < total:
        need_real_check = True
    elif cache_age is None or cache_age > 30:
        need_real_check = True

    # Если кеш устарел или баланса недостаточно, запрашиваем реальный баланс из блокчейна
    if need_real_check:
        real_balance = get_real_balance(user, network)
        if real_balance < total:
            raise ValueError("Insufficient real balance")
        # Обновляем кеш новым значением баланса, сливая с существующим кешем
        with _cache_lock:
            old = _balance_cache.get(user.id)
            if old:
                _, old_balances = old
                new_balances = old_balances.copy()
            else:
                new_balances = {
                    f"{net}_balance": Decimal(0) for net in NETWORKS
                }
            new_balances[f"{network}_balance"] = real_balance
            _balance_cache[user.id] = (now, new_balances)
    else:
        # Если кеш актуален, но баланс недостаточен — ошибка
        if balance < total:
            raise ValueError("Insufficient balance")

    # Находим кошелёк пользователя для указанной сети
    wallet = next((w for w in user.wallets if w.network == network), None)
    if not wallet:
        raise ValueError("Wallet not found")

    # Расшифровываем приватный ключ кошелька
    pk = Wallet.decrypt_pk(wallet.pk_enc)

    # Выполняем перевод средств через соответствующий провайдер сети
    tx_hash = {
        "erc": lambda: ERC20.transfer(pk, dest, amount),
        "bep": lambda: BEP20.transfer(pk, dest, amount),
        "trc": lambda: TRC20.transfer(pk, dest, amount),
    }[network]()

    # Создаём объект транзакции и сохраняем в базе
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

    # Инвалидируем кеш баланса пользователя, чтобы при следующем запросе баланс обновился
    invalidate_balance_cache(user.id)

    logger.info(f"[WITHDRAW] {network} hash={tx_hash}")
    return tx


def ref_balance(user: User) -> Decimal:
    """
    Возвращает реферальный баланс пользователя.

    Функция пытается получить объект ReferralBalance по идентификатору пользователя.
    Если объект найден, возвращается его баланс в виде Decimal, иначе возвращается 0.

    Args:
    ----------
    user : User
        Объект пользователя, для которого запрашивается реферальный баланс.

    Return:
    ----------
    Decimal
        Реферальный баланс пользователя.
    """  # noqa: E501
    rb = ReferralBalance.query.get(user.id)
    return Decimal(rb.balance) if rb else Decimal(0)


def ref_credit(user_id: int, amount: Decimal) -> None:
    """
    Кредитует реферальный баланс пользователя.

    Функция добавляет указанную сумму к реферальному балансу пользователя с заданным user_id.
    Если запись о реферальном балансе отсутствует, создается новая с начальным балансом amount.

    Args:
    ----------
    user_id : int
        Идентификатор пользователя, чей реферальный баланс будет увеличен.
    amount : Decimal
        Сумма, которую необходимо добавить к реферальному балансу.

    Return:
    ----------
    None
    """
    rb = ReferralBalance.query.get(user_id)
    if not rb:
        rb = ReferralBalance(user_id=user_id, balance=amount)
        db.session.add(rb)
    else:
        rb.balance += amount
    db.session.flush()
    invalidate_balance_cache(user_id)  # сбрасываем кэш баланса


@ledger(LedgerType.referral, direction="out")  # отрицательное списание
def ref_debit(user: User, amount: Decimal) -> Transaction:
    """
    Дебетует сумму из реферального баланса пользователя.

    Функция проверяет наличие реферального баланса и его достаточность для
    списания указанной суммы. Если баланс достаточен сумма списывается,
    и создается объект Transaction, который сохраняется в базе данных.

    Args:
    ----------
    user : User
        Объект пользователя, у которого будет списана сумма.
    amount : Decimal
        Сумма, которую необходимо дебетовать из реферального баланса.

    Return:
    ----------
    Transaction
        Объект созданной транзакции.

    Exceptions:
    -----------
    ValueError
        Если реферальный баланс недостаточен или отсутствует.
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
    invalidate_balance_cache(user.id)  # сбрасываем кэш баланса

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
    Кредитует сумму на баланс пользователя.

    Функция создает транзакцию, которая вычитает указанную сумму из баланса
    пользователя в заданной сети. Транзакция сохраняется в базе данных
    с состоянием 'подтверждено'.

    Args:
    ----------
    user : User
        Объект пользователя, которому будет зачислена сумма.
    network : str
        Название сети, в которой производится зачисление.
    amount : Decimal
        Сумма, которую необходимо зачислить на баланс пользователя.

    Returns:
    ----------
    Transaction
        Объект созданной транзакции, представляющий операцию зачисления.
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
    invalidate_balance_cache(user.id)  # сбрасываем кэш баланса
    return tx


#  Переименовано с credit_to_balance
def credit_to_network_balance(
    user_id: int,
    network: str,
    amount: Decimal,
) -> None:
    """
    Кредитует указанную сумму на баланс пользователя для заданной сети.

    Создаёт транзакцию типа "депозит" со статусом "подтверждён" и
    соответствующую запись в бухгалтерском журнале (LedgerEntry),
    затем сохраняет изменения в базе данных.

    Args:
        user_id (int): Идентификатор пользователя, которому начисляется сумма.
        network (str): Название или идентификатор сети, для которой проводится операция.
        amount (Decimal): Сумма для зачисления на баланс.

    Returns:
        None
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
    invalidate_balance_cache(user_id)  # сбрасываем кэш баланса
