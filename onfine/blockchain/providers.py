import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from decimal import Decimal
from functools import wraps
from typing import List, Tuple

from cryptography.fernet import Fernet
from requests.exceptions import ConnectionError as RequestsConnectionError
from tronpy import Contract as TronContract
from tronpy import Tron
from tronpy.keys import (
    PrivateKey,
    is_base58check_address,
    to_base58check_address,
    to_hex_address,
)
from tronpy.providers import HTTPProvider
from web3 import Web3
from web3.contract import Contract as Web3Contract
from web3.exceptions import BadFunctionCallOutput, ContractLogicError

from onfine.models.user import User

FERNET = Fernet(os.getenv("FERNET_KEY").encode())

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def ttl_cache(ttl_seconds: int):
    """
    Декоратор для кеширования результатов функции на заданное время (TTL).

    Args:
        ttl_seconds (int): Время жизни кеша в секундах.

    Returns:
        Callable: Обернутая функция с кешированием.
    """

    def decorator(func):
        cache = {}
        lock = threading.Lock()

        @wraps(func)
        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            now = time.time()
            with lock:
                if key in cache:
                    result, timestamp = cache[key]
                    if now - timestamp < ttl_seconds:
                        return result
            result = func(*args, **kwargs)
            with lock:
                cache[key] = (result, now)
            return result

        return wrapper

    return decorator


class TokenNetwork(ABC):
    symbol = "USDT"
    decimals = 6

    @staticmethod
    @abstractmethod
    def generate_wallet() -> Tuple[str, str]:
        """Создает новый кошелек и возвращает адрес и приватный ключ.

        Returns:
            Tuple[str, str]: Кортеж с адресом и приватным ключом.
        """

    @staticmethod
    @abstractmethod
    def balance(addr: str) -> Decimal:
        """Получает баланс токенов по адресу.

        Args:
            addr (str): Адрес кошелька.

        Returns:
            Decimal: Баланс токенов.
        """

    @staticmethod
    @abstractmethod
    def estimate_fee(pk: str, amount: Decimal, to_addr: str) -> Decimal:
        """
        Оценивает комиссию за перевод токенов.

        Args:
            pk (str): Приватный ключ отправителя.
            amount (Decimal): Сумма перевода.
            to_addr (str): Адрес получателя.

        Returns:
            Decimal: Оцененная комиссия.
        """

    @staticmethod
    @abstractmethod
    def transfer(pk: str, to_addr: str, amount: Decimal) -> str:
        """Переводит токены на указанный адрес.

        Args:
            pk (str): Приватный ключ отправителя.
            to_addr (str): Адрес получателя.
            amount (Decimal): Сумма перевода.

        Returns:
            str: ID транзакции.
        """


class ERC20(TokenNetwork):
    decimals = 6
    infura_key = os.getenv("INFURA_API_KEY")
    w3 = Web3(Web3.HTTPProvider(f"https://mainnet.infura.io/v3/{infura_key}"))
    contract_addr = Web3.to_checksum_address(
        "0xdAC17F958D2ee523a2206206994597C13D831ec7"
    )

    @staticmethod
    def _contract(abi: list) -> Web3Contract:
        """Создает и возвращает объект контракта на основе заданного ABI.

        Args:
            abi (list): ABI контракта.

        Returns:
            Web3Contract: Объект контракта.
        """
        return ERC20.w3.eth.contract(address=ERC20.contract_addr, abi=abi)

    @staticmethod
    def generate_wallet() -> Tuple[str, str]:
        acc = ERC20.w3.eth.account.create()
        return acc.address, acc.privateKey.hex()

    @staticmethod
    @ttl_cache(ttl_seconds=60)
    def balance(addr: str) -> Decimal:
        if not Web3.is_address(addr):
            raise ValueError(f"Invalid Ethereum address: {addr}")
        addr = Web3.to_checksum_address(addr)
        abi = [
            {
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "type": "function",
            },
        ]
        try:
            bal = ERC20._contract(abi).functions.balanceOf(addr).call()
            return Decimal(bal) / (10**ERC20.decimals)
        except (
            BadFunctionCallOutput,
            ContractLogicError,
            RequestsConnectionError,
        ) as e:
            logger.error(
                f"Error fetching ERC20 balance for address {addr}: {e}",
                exc_info=True,
            )
            raise RuntimeError(f"Error fetching ERC20 balance: {e}")

    @staticmethod
    def estimate_fee(pk: str, amount: Decimal, to_addr: str) -> Decimal:
        if not Web3.is_address(to_addr):
            raise ValueError(f"Invalid Ethereum address: {to_addr}")
        to_addr = Web3.to_checksum_address(to_addr)
        try:
            from_addr = ERC20.w3.eth.account.privateKeyToAccount(pk).address
            abi = [
                {
                    "constant": False,
                    "inputs": [
                        {"name": "_to", "type": "address"},
                        {"name": "_value", "type": "uint256"},
                    ],
                    "name": "transfer",
                    "outputs": [{"name": "", "type": "bool"}],
                    "type": "function",
                },
            ]
            tx = (
                ERC20._contract(abi)
                .functions.transfer(
                    to_addr, int(amount * (10**ERC20.decimals))
                )
                .build_transaction({"from": from_addr})
            )
            gas = ERC20.w3.eth.estimate_gas(tx)
            gas_price = ERC20.w3.eth.gas_price
            return Decimal(gas * gas_price) / (10**18)
        except (ValueError, ContractLogicError, RequestsConnectionError) as e:
            logger.error(
                f"Error estimating ERC20 fee from {from_addr} to {to_addr}: {e}",
                exc_info=True,
            )
            raise RuntimeError(f"Error estimating ERC20 fee: {e}")

    @staticmethod
    def transfer(pk: str, to_addr: str, amount: Decimal) -> str:
        if not Web3.is_address(to_addr):
            raise ValueError(f"Invalid Ethereum address: {to_addr}")
        to_addr = Web3.to_checksum_address(to_addr)
        try:
            acct = ERC20.w3.eth.account.privateKeyToAccount(pk)
            nonce = ERC20.w3.eth.get_transaction_count(acct.address)
            abi = [
                {
                    "constant": False,
                    "inputs": [
                        {"name": "_to", "type": "address"},
                        {"name": "_value", "type": "uint256"},
                    ],
                    "name": "transfer",
                    "outputs": [{"name": "", "type": "bool"}],
                    "type": "function",
                },
            ]
            tx = (
                ERC20._contract(abi)
                .functions.transfer(
                    to_addr, int(amount * (10**ERC20.decimals))
                )
                .build_transaction(
                    {
                        "from": acct.address,
                        "nonce": nonce,
                        "gasPrice": ERC20.w3.eth.gas_price,
                    }
                )
            )
            signed = acct.sign_transaction(tx)
            tx_hash = ERC20.w3.eth.send_raw_transaction(
                signed.rawTransaction
            ).hex()
            return tx_hash
        except (ValueError, ContractLogicError, RequestsConnectionError) as e:
            logger.error(
                f"Error sending ERC20 transfer from {acct.address} to {to_addr}: {e}",
                exc_info=True,
            )
            raise RuntimeError(f"Error sending ERC20 transfer: {e}")


class BEP20(TokenNetwork):
    decimals = 18
    w3 = Web3(Web3.HTTPProvider("https://bsc-dataseed.binance.org"))
    contract_addr = Web3.to_checksum_address(
        "0x55d398326f99059fF775485246999027B3197955"
    )

    @staticmethod
    def _contract(abi: List[dict]) -> Web3Contract:
        return BEP20.w3.eth.contract(address=BEP20.contract_addr, abi=abi)

    @staticmethod
    def generate_wallet() -> Tuple[str, str]:
        acc = BEP20.w3.eth.account.create()
        return acc.address, acc.privateKey.hex()

    @staticmethod
    def balance(addr: str) -> Decimal:
        if not Web3.is_address(addr):
            raise ValueError(f"Invalid BSC address: {addr}")
        addr = Web3.to_checksum_address(addr)
        abi = [
            {
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "type": "function",
            },
        ]
        try:
            bal = BEP20._contract(abi).functions.balanceOf(addr).call()
            return Decimal(bal) / (10**BEP20.decimals)
        except (
            BadFunctionCallOutput,
            ContractLogicError,
            RequestsConnectionError,
        ) as e:
            logger.error(
                f"Error fetching BEP20 balance for address {addr}: {e}",
                exc_info=True,
            )
            raise RuntimeError(f"Error fetching BEP20 balance: {e}")

    @staticmethod
    def estimate_fee(pk: str, amount: Decimal, to_addr: str) -> Decimal:
        if not Web3.is_address(to_addr):
            raise ValueError(f"Invalid Ethereum address: {to_addr}")
        to_addr = Web3.to_checksum_address(to_addr)
        try:
            from_addr = BEP20.w3.eth.account.privateKeyToAccount(pk).address
            abi = [
                {
                    "constant": False,
                    "inputs": [
                        {"name": "_to", "type": "address"},
                        {"name": "_value", "type": "uint256"},
                    ],
                    "name": "transfer",
                    "outputs": [{"name": "", "type": "bool"}],
                    "type": "function",
                },
            ]
            tx = (
                BEP20._contract(abi)
                .functions.transfer(
                    to_addr, int(amount * (10**BEP20.decimals))
                )
                .build_transaction({"from": from_addr})
            )
            gas = BEP20.w3.eth.estimate_gas(tx)
            gas_price = BEP20.w3.eth.gas_price
            return Decimal(gas * gas_price) / (10**18)
        except (ValueError, ContractLogicError, RequestsConnectionError) as e:
            logger.error(
                f"Error estimating BEP20 fee from {from_addr} to {to_addr}: {e}",
                exc_info=True,
            )
            raise RuntimeError(f"Error estimating BEP20 fee: {e}")

    @staticmethod
    def transfer(pk: str, to_addr: str, amount: Decimal) -> str:
        if not Web3.is_address(to_addr):
            raise ValueError(f"Invalid BSC address: {to_addr}")
        to_addr = Web3.to_checksum_address(to_addr)
        try:
            acct = BEP20.w3.eth.account.privateKeyToAccount(pk)
            nonce = BEP20.w3.eth.get_transaction_count(acct.address)
            abi = [
                {
                    "constant": False,
                    "inputs": [
                        {"name": "_to", "type": "address"},
                        {"name": "_value", "type": "uint256"},
                    ],
                    "name": "transfer",
                    "outputs": [{"name": "", "type": "bool"}],
                    "type": "function",
                },
            ]
            tx = (
                BEP20._contract(abi)
                .functions.transfer(
                    to_addr, int(amount * (10**BEP20.decimals))
                )
                .build_transaction(
                    {
                        "from": acct.address,
                        "nonce": nonce,
                        "gasPrice": BEP20.w3.eth.gas_price,
                    }
                )
            )
            signed = acct.sign_transaction(tx)
            tx_hash = BEP20.w3.eth.send_raw_transaction(
                signed.rawTransaction
            ).hex()
            return tx_hash
        except (ValueError, ContractLogicError, RequestsConnectionError) as e:
            logger.error(
                f"Error sending BEP20 transfer from {acct.address} to {to_addr}: {e}",
                exc_info=True,
            )
            raise RuntimeError(f"Error sending BEP20 transfer: {e}")


TRC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
        "stateMutability": "view",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
        "stateMutability": "view",
    },
]


class TRC20(TokenNetwork):
    client = Tron(provider=HTTPProvider("https://api.trongrid.io"))
    contract_addr = "TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj"
    _contract_instance = None
    decimals = 6

    @classmethod
    def get_contract(cls):
        if cls._contract_instance is None:
            cls._contract_instance = TronContract(
                cls.contract_addr,
                client=cls.client,
                abi=TRC20_ABI,
            )
        return cls._contract_instance

    @classmethod
    def balance(cls, addr: str) -> int:
        if not is_base58check_address(addr):
            raise ValueError(f"Invalid Tron address: {addr}")
        contract = cls.get_contract()
        try:
            return contract.functions.balanceOf(addr).call()
        except Exception as e:
            logger.error(
                f"Error fetching TRC20 balance for address {addr}: {e}",
                exc_info=True,
            )
            raise RuntimeError(f"Error fetching TRC20 balance: {e}")

    @staticmethod
    def generate_wallet() -> Tuple[str, str]:
        acc = TRC20.client.generate_address()
        return acc["base58check_address"], acc["private_key"]

    @classmethod
    def get_balance_for_user(cls, user: User) -> Decimal:
        wallet = next((w for w in user.wallets if w.network == "trc"), None)
        if not wallet:
            return Decimal(0)
        return Decimal(cls.balance(wallet.address)) / (10**cls.decimals)

    @staticmethod
    def estimate_fee(pk: str, amount: Decimal, to_addr: str) -> Decimal:
        try:
            if pk.startswith("0x"):
                pk = pk[2:]
            priv = PrivateKey(bytes.fromhex(pk))
            if not is_base58check_address(to_addr):
                raise ValueError(f"Invalid Tron address: {to_addr}")

            contract = TRC20.get_contract()
            txn = (
                contract.functions.transfer(
                    to_addr, int(amount * (10**TRC20.decimals))
                )
                .with_owner(priv.public_key.to_base58check_address())
                .fee_limit(10_000_000)
                .build()
                .sign(priv)
            )
            fee = (
                Decimal(txn._transaction["raw_data"]["fee_limit"]) / 1_000_000
            )
            return fee
        except Exception as e:
            logger.error(f"Error estimating TRC20 fee: {e}", exc_info=True)
            raise RuntimeError(f"Error estimating TRC20 fee: {e}")

    @staticmethod
    def transfer(pk: str, to_addr: str, amount: Decimal) -> str:
        try:
            if pk.startswith("0x"):
                pk = pk[2:]
            priv = PrivateKey(bytes.fromhex(pk))
            if not is_base58check_address(to_addr):
                raise ValueError(f"Invalid Tron address: {to_addr}")

            contract = TRC20.get_contract()
            tx = (
                contract.functions.transfer(
                    to_addr, int(amount * (10**TRC20.decimals))
                )
                .with_owner(priv.public_key.to_base58check_address())
                .fee_limit(10_000_000)
                .build()
                .sign(priv)
                .broadcast()
            )
            return tx["txid"]
        except Exception as e:
            logger.error(f"Error sending TRC20 transfer: {e}", exc_info=True)
            raise RuntimeError(f"Error sending TRC20 transfer: {e}")
