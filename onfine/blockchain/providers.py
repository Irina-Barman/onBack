import logging
import os
from decimal import Decimal
from typing import Optional, Tuple

from tronpy import Tron
from tronpy.keys import PrivateKey
from tronpy.providers import HTTPProvider
from web3 import Web3
from web3.types import TxParams

from onfine.blockchain.abi_loader import fetch_abi

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
        """
        Создаёт новый кошелёк.

        Returns:
            Tuple[str, str]: Кортеж (адрес, приватный ключ).
        """
        raise NotImplementedError()

    @staticmethod
    def supports_multicall() -> bool:
        """
        Указывает, поддерживает ли сеть мультивызовы (multicall).

        Returns:
            bool: True, если поддерживает, иначе False.
        """
        return False

    def balance(self, address: str) -> Decimal:
        """
        Получает баланс токена на указанном адресе.

        Args:
            address (str): Адрес кошелька.

        Returns:
            Decimal: Баланс токена.
        """
        raise NotImplementedError()

    def balance_native(self, addr: str) -> Decimal:  # noqa: D417
        """
        Получает баланс токена на указанном адресе.

        Args:
            address (str): Адрес кошелька.

        Returns:
            Decimal: Баланс токена.
        """
        raise NotImplementedError()

    def transfer(self, pk: str, to_addr: str, amount: Decimal) -> str:
        """
        Отправляет токены с приватного ключа на указанный адрес.

        Args:
            pk (str): Приватный ключ отправителя.
            to_addr (str): Адрес получателя.
            amount (Decimal): Количество токенов для перевода.

        Returns:
            str: Хэш или ID транзакции.
        """
        raise NotImplementedError()

    def estimate_fee(self, pk: str, amount: Decimal, to_addr: str) -> Decimal:
        """
        Оценивает комиссию за перевод токенов.

        Args:
            pk (str): Приватный ключ отправителя.
            amount (Decimal): Сумма перевода.
            to_addr (str): Адрес получателя.

        Returns:
            Decimal: Оценка комиссии.
        """
        raise NotImplementedError()

    def validate_contract(self) -> bool:
        """
        Проверяет валидность контракта токена.

        Returns:
            bool: True, если контракт валиден, иначе False.
        """
        raise NotImplementedError()


class ERC20(TokenNetwork):
    def __init__(self, contract_addr: Optional[str] = None) -> None:
        """
        Инициализация ERC20 токена.

        Args:
            contract_addr (Optional[str]): Адрес контракта токена.
                Если None, используется переменная окружения USDT_ERC_CONTRACT_ADDR.
        """
        self.network = "ERC20"
        self.w3 = self._w3()
        self.contract_addr = Web3.to_checksum_address(contract_addr or os.getenv("USDT_ERC_CONTRACT_ADDR"))
        self.abi = fetch_abi(network=self.network, contract_addr=self.contract_addr)
        self.contract = self.w3.eth.contract(address=self.contract_addr, abi=self.abi)
        self._decimals = self._get_decimals()

    @staticmethod
    def _w3() -> Web3:
        """
        Создаёт экземпляр Web3 с HTTP провайдером.

        Returns:
            Web3: Экземпляр Web3.
        """
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
        """
        Получает экземпляр Web3.

        Returns:
            Web3: Экземпляр Web3.
        """
        return cls._w3()

    @staticmethod
    def to_checksum(addr: str) -> str:
        """
        Преобразует адрес в формат checksum.

        Args:
            addr (str): Адрес в любом формате.

        Returns:
            str: Адрес в формате checksum.
        """
        return Web3.to_checksum_address(addr)

    @staticmethod
    def supports_multicall() -> bool:
        """
        Проверяет поддержку multicall.

        Returns:
            bool: True, так как ERC20 поддерживает multicall.
        """
        return True

    def _get_decimals(self) -> int:
        """
        Получает количество десятичных знаков токена.

        Returns:
            int: Количество десятичных знаков.
        """
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
        Получает баланс нативного токена Ethereum (ETH).

        Args:
            addr (str): Ethereum-адрес.

        Returns:
            Decimal: Баланс ETH.
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
        """
        Проверяет валидность контракта ERC20.

        Returns:
            bool: True, если контракт существует и валиден.
        """
        code = self.w3.eth.get_code(self.contract_addr)
        return bool(code and code != b"\x00")

    def build_user_token_transfer(  # noqa: D102
        self,
        user_addr: str,
        to_addr: str,
        amount: Decimal,
        nonce: int,
    ) -> TxParams:  # noqa: D102
        amount_raw = int(amount * (10**self._decimals))
        # стараемся использовать EIP-1559, если нода поддерживает; иначе legacy gasPrice
        base_fee = self.w3.eth.get_block("pending").get("baseFeePerGas")
        gas_limit = self.contract.functions.transfer(to_addr, amount_raw).estimate_gas({"from": user_addr})
        if base_fee is not None:
            max_priority = self.w3.to_wei("1", "gwei")
            max_fee = int(base_fee + max_priority * 2)
            return {
                "from": user_addr,
                "to": self.contract.address,
                "nonce": nonce,
                "data": self.contract.encode_abi(fn_name="transfer", args=[to_addr, amount_raw]),
                "gas": int(gas_limit * 1.2),  # небольшой буфер
                "maxPriorityFeePerGas": max_priority,
                "maxFeePerGas": max_fee,
                "chainId": self.w3.eth.chain_id,
            }
        else:
            gas_price = self.w3.eth.gas_price
            return {
                "from": user_addr,
                "to": self.contract.address,
                "nonce": nonce,
                "data": self.contract.encode_abi(fn_name="transfer", args=[to_addr, amount_raw]),
                "gas": int(gas_limit * 1.2),
                "gasPrice": gas_price,
                "chainId": self.w3.eth.chain_id,
            }

    def sign_user_tx(self, unsigned_tx: dict, user_pk: str) -> tuple[bytes, str]:  # noqa: D102
        signed = self.w3.eth.account.sign_transaction(unsigned_tx, private_key=user_pk)
        return signed.rawTransaction, signed.hash.hex()

    def publish_raw_tx(self, raw_tx: bytes) -> str:  # noqa: D102
        tx_hash = self.w3.eth.send_raw_transaction(raw_tx)
        return tx_hash.hex()

    def estimate_native_for_tx(self, unsigned_tx: dict) -> Decimal:  # noqa: D102
        # EIP-1559 или legacy
        gas = Decimal(unsigned_tx["gas"])
        if "maxFeePerGas" in unsigned_tx:
            fee_per_gas = Decimal(unsigned_tx["maxFeePerGas"])
        else:
            fee_per_gas = Decimal(unsigned_tx["gasPrice"])
        wei = gas * fee_per_gas
        return Decimal(wei) / Decimal(10**18)

    def send_native(self, platform_pk: str, to_addr: str, amount_native: Decimal) -> str:  # noqa: D102
        acct = self.w3.eth.account.from_key(platform_pk)
        nonce = self.w3.eth.get_transaction_count(acct.address, "pending")
        value = int(amount_native * Decimal(10**18))
        base_fee = self.w3.eth.get_block("pending").get("baseFeePerGas")
        if base_fee is not None:
            max_priority = self.w3.to_wei("1", "gwei")
            max_fee = int(base_fee + max_priority * 2)
            tx = {
                "to": Web3.to_checksum_address(to_addr),
                "from": acct.address,
                "value": value,
                "nonce": nonce,
                "gas": 21000,
                "maxPriorityFeePerGas": max_priority,
                "maxFeePerGas": max_fee,
                "chainId": self.w3.eth.chain_id,
            }
        else:
            tx = {
                "to": Web3.to_checksum_address(to_addr),
                "from": acct.address,
                "value": value,
                "nonce": nonce,
                "gas": 21000,
                "gasPrice": self.w3.eth.gas_price,
                "chainId": self.w3.eth.chain_id,
            }
        signed = self.w3.eth.account.sign_transaction(tx, private_key=platform_pk)
        tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)
        return tx_hash.hex()


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

    def __init__(self, contract_addr: Optional[str] = None) -> None:
        """
        Инициализация BEP20 токена.

        Args:
            contract_addr (Optional[str]): Адрес контракта токена.
                Если None, используется переменная окружения USDT_BEP_CONTRACT_ADDR.
        """
        self.network = "BEP20"
        self.w3 = self._w3()
        self.contract_addr = Web3.to_checksum_address(contract_addr or os.getenv("USDT_BEP_CONTRACT_ADDR"))
        self.abi = fetch_abi(network=self.network, contract_addr=self.contract_addr)
        self.contract = self.w3.eth.contract(address=self.contract_addr, abi=self.abi)
        self._decimals = self._get_decimals()

    @staticmethod
    def _w3() -> Web3:
        """
        Создаёт экземпляр Web3 с HTTP провайдером для BSC.

        Returns:
            Web3: Экземпляр Web3.
        """
        return Web3(Web3.HTTPProvider(os.getenv("BEP_ANKR_HTTP_URL")))

    @classmethod
    def get_web3(cls) -> Web3:
        """
        Получает экземпляр Web3 для BSC.

        Returns:
            Web3: Экземпляр Web3.
        """
        return cls._w3()

    @staticmethod
    def to_checksum(addr: str) -> str:
        """
        Преобразует адрес в формат checksum.

        Args:
            addr (str): Адрес в любом формате.

        Returns:
            str: Адрес в формате checksum.
        """
        return Web3.to_checksum_address(addr)

    @staticmethod
    def supports_multicall() -> bool:
        """
        Проверяет поддержку multicall.

        Returns:
            bool: True, так как BEP20 поддерживает multicall.
        """
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
        """
        Получает количество десятичных знаков токена BEP20.

        Returns:
            int: Количество десятичных знаков.
        """
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

    def __init__(self, contract_addr: Optional[str] = None) -> None:
        """
        Инициализация TRC20 токена.

        Args:
            contract_addr (Optional[str]): Адрес контракта TRC20 токена.
                Если None, используется переменная окружения USDT_TRC_CONTRACT_ADDR.
        """
        self.client = Tron(provider=HTTPProvider(api_key=os.getenv("TRONGRID_API_KEY")))
        self.network = "TRC20"
        self.contract_addr = contract_addr or os.getenv("USDT_TRC_CONTRACT_ADDR")
        self.abi = fetch_abi(self.network, self.contract_addr)
        self.contract = self.client.get_contract(self.contract_addr)
        self.contract.abi = self.abi
        self._decimals = self._get_decimals()

    def _get_decimals(self) -> int:
        """
        Получает количество десятичных знаков токена TRC20.

        Returns:
            int: Количество десятичных знаков.
        """
        try:
            return self.contract.functions.decimals()
        except Exception as e:
            logger.info(f"[TRC20] Error getting decimals from {self.contract_addr}, fallback to 6: {e}")
            return 6

    @staticmethod
    def generate_wallet() -> Tuple[str, str]:
        """
        Создаёт новый TRON кошелёк.

        Returns:
            Tuple[str, str]: Кортеж из двух строк:
                - base58check адрес кошелька,
                - приватный ключ в hex формате.
        """
        client = Tron(provider=HTTPProvider(api_key=os.getenv("TRONGRID_API_KEY")))
        acc = client.generate_address()
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
        """
        Проверяет валидность контракта TRC20.

        Returns:
            bool: True, если контракт валиден, иначе False.
        """
        try:
            _ = self.contract.functions.symbol().call()
            return True
        except Exception:
            return False

    def build_user_token_transfer(  # noqa: D102, ANN201
        self,
        user_addr: str,
        to_addr: str,
        amount: Decimal,
        reserved_nonce: int | None = None,  # noqa: ARG002
    ):
        # reserved_nonce для совместимости интерфейса; TRON сам считает nonce
        amount_raw = int(amount * (10**self._decimals))
        txn = (
            self.contract.functions.transfer(to_addr, amount_raw)
            .with_owner(user_addr)
            .fee_limit(10_000_000)  # 10 TRX в sun; подкорректируй при необходимости
            .build()
        )
        return txn  # tronpy Transaction object

    def sign_user_tx(self, unsigned_tx, user_pk: str) -> tuple[bytes, str]:  # noqa: ANN001, D102
        priv = PrivateKey(bytes.fromhex(user_pk))
        signed = unsigned_tx.sign(priv)
        raw = signed.tx.raw_data.hex().encode()  # сохраняем как bytes
        txid = signed.tx.txid
        return raw, txid

    def publish_raw_tx(self, raw_tx: bytes) -> str:  # noqa: D102
        # для TRON нужно восстановить txn — если ты сохраняешь signed в базе, лучше сохранять signed.tx.serialize()
        # здесь предполагаем, что мы публикуем сразу после sign (в типовом воркфлоу)
        raise NotImplementedError("Publish from raw requires full txn object; публикуй сразу после sign в воркере")

    def estimate_native_for_tx(self, unsigned_tx) -> Decimal:  # noqa: D102, ANN001
        return Decimal(unsigned_tx.fee_limit) / Decimal(1_000_000)

    def send_native(self, platform_pk: str, to_addr: str, amount_native: Decimal) -> str:  # noqa: D102
        priv = PrivateKey(bytes.fromhex(platform_pk))
        amount_sun = int(amount_native * Decimal(1_000_000))
        txn = self.client.trx.transfer(priv.public_key.to_base58check_address(), to_addr, amount_sun).build().sign(priv)
        res = txn.broadcast()
        if not res.get("result"):
            raise Exception(f"TRX transfer failed: {res}")
        return res["txid"]


class ProviderManager:
    """
    Менеджер провайдеров для токенов разных сетей.

    Кэширует экземпляры провайдеров для повторного использования.
    """

    _cache = {}

    @classmethod
    def get(cls, network: str, contract_addr: Optional[str] = None) -> TokenNetwork:
        """
        Получает экземпляр провайдера для указанной сети и контракта.

        Args:
            network (str): Название сети ("ERC20", "BEP20", "TRC20").
            contract_addr (Optional[str]): Адрес контракта токена.

        Raises:
            ValueError: Если сеть не поддерживается.

        Returns:
            TokenNetwork: Экземпляр провайдера токена.
        """
        network = network.upper()
        key = (network, contract_addr)
        if key in cls._cache:
            return cls._cache[key]

        if network == "erc20":
            cls._cache[key] = ERC20(contract_addr)
        elif network == "bep20":
            cls._cache[key] = BEP20(contract_addr)
        elif network == "trc20":
            cls._cache[key] = TRC20(contract_addr)
        else:
            raise ValueError(f"Unsupported network: {network}")

        return cls._cache[key]
