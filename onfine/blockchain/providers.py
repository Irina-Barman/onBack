import logging
import os
from decimal import Decimal
from typing import Optional, Tuple

from tronpy import Tron
from tronpy.keys import PrivateKey
from tronpy.providers import HTTPProvider
from web3 import Web3

from onfine.blockchain.token_abi_loder import get_token_abi

logger = logging.getLogger(__name__)


class TokenNetwork:
    """
    Абстрактный базовый класс для работы с токенами в разных блокчейн-сетях.

    Определяет интерфейс для наследников, которые реализуют работу с конкретными сетями.

    Атрибуты:
        decimals (int): Количество десятичных знаков токена (по умолчанию 6).

    Методы (статические, должны быть реализованы в наследниках):
        generate_wallet() -> Tuple[str, str]:
            Создаёт новый кошелёк (адрес и приватный ключ).

        balance(address: str) -> Decimal:
            Возвращает баланс токена на указанном адресе.

        estimate_fee(pk: str, amount: Decimal, to_addr: str) -> Decimal:
            Оценивает комиссию за перевод токенов.

        transfer(pk: str, to_addr: str, amount: Decimal) -> str:
            Отправляет токены с приватного ключа на указанный адрес,
            возвращает хэш или ID транзакции.
    """

    @staticmethod
    def generate_wallet() -> Tuple[str, str]:
        raise NotImplementedError()

    @staticmethod
    def supports_multicall() -> bool:
        return False

    def balance(self, address: str) -> Decimal:
        raise NotImplementedError()

    def transfer(self, pk: str, to_addr: str, amount: Decimal) -> str:
        raise NotImplementedError()

    def estimate_fee(self, pk: str, amount: Decimal, to_addr: str) -> Decimal:
        raise NotImplementedError()

    def validate_contract(self) -> bool:
        raise NotImplementedError()


class ERC20(TokenNetwork):
    def __init__(self, contract_addr: Optional[str] = None):
        self.network = "ERC20"
        self.w3 = self._w3()
        self.contract_addr = Web3.to_checksum_address(contract_addr or os.getenv("USDT_ERC_CONTRACT_ADDR"))
        self.abi = get_token_abi(network=self.network, contract_addr=self.contract_addr)
        self.contract = self.w3.eth.contract(address=self.contract_addr, abi=self.abi)
        self._decimals = self._get_decimals()

    @staticmethod
    def _w3() -> Web3:
        return Web3(Web3.HTTPProvider(os.getenv("ERC_ANKR_HTTP_URL")))

    @staticmethod
    def generate_wallet() -> Tuple[str, str]:
        """
        Генерирует новый Ethereum-кошелёк (адрес и приватный ключ).

        Returns:
            Tuple[str, str]: (адрес, приватный ключ в hex)
        """
        w3 = ERC20._w3()
        acct = w3.eth.account.create()
        return acct.address, acct.key.hex()

    @classmethod
    def get_web3(cls) -> Web3:
        return cls._w3()

    @staticmethod
    def to_checksum(addr: str) -> str:
        return Web3.to_checksum_address(addr)

    @staticmethod
    def supports_multicall() -> bool:
        return True

    def _get_decimals(self) -> int:
        try:
            return self.contract.functions.decimals().call()
        except Exception as e:
            logger.info(f"[ERC20] Error getting decimals from {self.contract_addr}, fallback to 18: {e}")
            return 18

    def balance(self, addr: str) -> Decimal:
        """
        Получает баланс токена ERC20 на указанном адресе.

        Args:
            addr (str): Ethereum-адрес.

        Returns:
            Decimal: Баланс токена с учётом десятичных знаков.
        """
        addr = Web3.to_checksum_address(addr)
        bal = self.contract.functions.balanceOf(addr).call()
        return Decimal(bal) / (10**self._decimals)

    def balance_native(self, addr: str) -> Decimal:
        """
        Получаем баланс нативного токена

        Args:
            addr (str): Ethereum-адрес.

        Returns:
            Decimal: Баланс токена с учётом десятичных знаков.
        """
        addr = Web3.to_checksum_address(addr)
        bal = self.w3.eth.get_balance(addr)
        return Decimal(bal) / Decimal(10**18)

    def estimate_fee(self, pk: str, amount: Decimal, to_addr: str) -> Decimal:
        """
        Оценивает комиссию за перевод ERC20 токена.

        Args:
            pk (str): Приватный ключ отправителя в hex.
            amount (Decimal): Сумма токенов для перевода.
            to_addr (str): Адрес получателя.

        Returns:
            Decimal: Оценка комиссии в ETH.
        """
        acct = self.w3.eth.account.privateKeyToAccount(pk)
        to_addr = Web3.to_checksum_address(to_addr)
        tx = self.contract.functions.transfer(to_addr, int(amount * (10**self._decimals))).build_transaction(
            {"from": acct.address},
        )
        gas = self.w3.eth.estimateGas(tx)
        gas_price = self.w3.eth.gas_price
        return Decimal(gas * gas_price) / Decimal(10**18)

    def transfer(self, pk: str, to_addr: str, amount: Decimal) -> str:
        """
        Отправляет ERC20 токены с кошелька, заданного приватным ключом.

        Args:
            pk (str): Приватный ключ отправителя в hex.
            to_addr (str): Адрес получателя.
            amount (Decimal): Количество токенов для перевода.

        Returns:
            str: Хэш транзакции.
        """
        acct = self.w3.eth.account.privateKeyToAccount(pk)
        to_addr = Web3.to_checksum_address(to_addr)
        nonce = self.w3.eth.getTransactionCount(acct.address)
        tx = self.contract.functions.transfer(to_addr, int(amount * (10**self._decimals))).build_transaction(
            {
                "from": acct.address,
                "nonce": nonce,
                "gasPrice": self.w3.eth.gas_price,
            },
        )
        signed = acct.signTransaction(tx)
        tx_hash = self.w3.eth.sendRawTransaction(signed.rawTransaction)
        return tx_hash.hex()

    def validate_contract(self) -> bool:
        code = self.w3.eth.get_code(self.contract_addr)
        return bool(code and code != b"\x00")


class BEP20(ERC20):
    """
    Класс для работы с BEP20 токенами в сети Binance Smart Chain.

    BEP20 — совместим с ERC20, поэтому используется тот же ABI и интерфейс.

    Атрибуты:
        decimals (int): Количество десятичных знаков (6).
        w3 (Web3): Экземпляр Web3 для BSC.
        contract_addr (str): Адрес контракта токена BEP20.
        abi (list): ABI контракта токена (тот же, что и ERC20).
    """

    def __init__(self, contract_addr: Optional[str] = None):
        self.network = "BEP20"
        self.w3 = self._w3()
        self.contract_addr = Web3.to_checksum_address(contract_addr or os.getenv("USDT_BEP_CONTRACT_ADDR"))
        self.abi = get_token_abi(network=self.network, contract_addr=self.contract_addr)
        self.contract = self.w3.eth.contract(address=self.contract_addr, abi=self.abi)
        self._decimals = self._get_decimals()

    @staticmethod
    def _w3() -> Web3:
        return Web3(Web3.HTTPProvider(os.getenv("BEP_ANKR_HTTP_URL")))

    @classmethod
    def get_web3(cls) -> Web3:
        return cls._w3()

    @staticmethod
    def to_checksum(addr: str) -> str:
        return Web3.to_checksum_address(addr)

    @staticmethod
    def supports_multicall() -> bool:
        return True

    @staticmethod
    def generate_wallet() -> Tuple[str, str]:
        """
        Генерирует новый BEP-кошелёк (адрес и приватный ключ).

        Returns:
            Tuple[str, str]: (адрес, приватный ключ в hex)
        """
        w3 = BEP20._w3()
        acct = w3.eth.account.create()
        return acct.address, acct.key.hex()

    def _get_decimals(self) -> int:
        try:
            return self.contract.functions.decimals().call()
        except Exception as e:
            logger.info(f"[BEP20] Error getting decimals from {self.contract_addr}, fallback to 18: {e}")
            return 18


class TRC20(TokenNetwork):
    """
    Класс для работы с TRC20 токенами в сети Tron.

    Использует tronpy для взаимодействия с TronGrid API.

    Атрибуты:
        decimals (int): Количество десятичных знаков токена (6).
        client (Tron): Клиент TronPy с HTTP провайдером.
        contract_addr (str): Адрес контракта TRC20 токена.
    """

    def __init__(self, contract_addr: Optional[str] = None):
        self.client = Tron(provider=HTTPProvider(api_key=os.getenv("TRONGRID_API_KEY")))
        self.network = "TRC20"
        self.contract_addr = contract_addr or os.getenv("USDT_TRC_CONTRACT_ADDR")
        self.abi = get_token_abi(self.network, self.contract_addr)
        self.contract = self.client.get_contract(self.contract_addr)
        self.contract.abi = self.abi
        self._decimals = self._get_decimals()

    def _get_decimals(self) -> int:
        try:
            return self.contract.functions.decimals()
        except Exception as e:
            logger.info(f"[TRC20] Error getting decimals from {self.contract_addr}, fallback to 6: {e}")
            return 6

    @staticmethod
    def generate_wallet() -> Tuple[str, str]:
        """
        Создает новый TRON кошелек.

        Returns:
            Tuple[str, str]: Кортеж из двух строк:
                - base58check адрес кошелька,
                - приватный ключ в шестнадцатеричном формате.
        """
        acc = TRC20.client.generate_address()
        return acc["base58check_address"], acc["private_key"]

    def balance_native(self, addr: str) -> Decimal:
        """
        Получает баланс TRX (нативный токен Tron) по адресу.

        Args:
            addr (str): Адрес Tron в base58check формате.

        Returns:
            Decimal: Баланс TRX.
        """
        try:
            raw_balance = self.client.get_account_balance(addr)
            return Decimal(raw_balance)
        except Exception as e:
            logger.warning(f"[TRC20] Error getting native TRX balance for {addr}: {e}")
            return Decimal(0)

    def balance(self, addr: str) -> Decimal:
        """
        Получает баланс TRC20 токенов для указанного адреса.

        Args:
            addr (str): Адрес TRON кошелька (base58check формат).

        Returns:
            Decimal: Баланс токенов с учётом десятичных знаков.
        """
        try:
            bal = self.contract.functions.balanceOf(addr).call()
            return Decimal(bal) / (10**self._decimals)
        except Exception as e:
            logger.warning(f"Error getting TRC20 balance for {addr}: {e}")
            return Decimal(0)

    def estimate_fee(self, pk: str, amount: Decimal, to_addr: str) -> Decimal:
        """
        Оценивает комиссию за перевод TRC20 токенов.

        Args:
            pk (str): Приватный ключ отправителя в hex формате.
            amount (Decimal): Сумма перевода токенов.
            to_addr (str): Адрес получателя (base58check формат).

        Returns:
            Decimal: Оцененная комиссия в TRX.
        """
        priv = PrivateKey(bytes.fromhex(pk))
        txn = (
            self.contract.functions.transfer(to_addr, int(amount * (10**self._decimals)))
            .with_owner(priv.public_key.to_base58check_address())
            .fee_limit(10_000_000)
            .build()
        )
        return Decimal(txn.fee_limit) / Decimal(1_000_000)

    def transfer(self, pk: str, to_addr: str, amount: Decimal) -> str:
        """
        Выполняет перевод TRC20 токенов на указанный адрес.

        Args:
            pk (str): Приватный ключ отправителя в hex формате.
            to_addr (str): Адрес получателя (base58check формат).
            amount (Decimal): Сумма перевода токенов.

        Returns:
            str: ID транзакции (txid).

        Raises:
            Exception: Если транзакция не была успешно отправлена.
        """
        priv = PrivateKey(bytes.fromhex(pk))
        txn = (
            self.contract.functions.transfer(to_addr, int(amount * (10**self._decimals)))
            .with_owner(priv.public_key.to_base58check_address())
            .fee_limit(10_000_000)
            .build()
            .sign(priv)
        )
        result = txn.broadcast()
        if not result["result"]:
            raise Exception(f"TRC20 transfer failed: {result}")
        return result["txid"]

    def validate_contract(self) -> bool:
        try:
            _ = self.contract.functions.symbol().call()
            return True
        except Exception:
            return False


class ProviderManager:
    _cache = {}

    @classmethod
    def get(cls, network: str, contract_addr: Optional[str] = None):
        key = (network, contract_addr)
        if key in cls._cache:
            return cls._cache[key]

        if network == "ERC20":
            cls._cache[key] = ERC20(contract_addr)
        elif network == "BEP20":
            cls._cache[key] = BEP20(contract_addr)
        elif network == "TRC20":
            cls._cache[key] = TRC20(contract_addr)
        else:
            raise ValueError(f"Unsupported network: {network}")

        return cls._cache[key]
