import logging
import os
import time
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import List, Tuple

import jwt
from cryptography.fernet import Fernet
from tronpy import Tron
from tronpy.keys import PrivateKey
from tronpy.providers import HTTPProvider
from web3 import Web3
from web3.contract import Contract

FERNET = Fernet(os.getenv("FERNET_KEY").encode())

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


# ---------------------------------------------------------------------- base
class TokenNetwork(ABC):
    symbol = "USDT"
    decimals = 6

    @staticmethod
    @abstractmethod
    def generate_wallet() -> Tuple[str, str]:
        """Создает новый кошелек и Return адрес и приватный ключ.

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


# ------------------------------------------------------------------ ERC-20
class ERC20(TokenNetwork):
    w3 = Web3(Web3.HTTPProvider(os.getenv("ERC_URL")))
    contract_addr = Web3.to_checksum_address(
        os.getenv("USDT_ERC_CONTRACT_ADDR")
    )

    @staticmethod
    def _contract(abi: list) -> Contract:
        """Создает и Return объект контракта на основе заданного ABI.

        Args:
            abi (list): ABI контракта.

        Returns:
            Contract: Объект контракта, связанный с заданным адресом и ABI.
        """
        return ERC20.w3.eth.contract(address=ERC20.contract_addr, abi=abi)

    # ---------- wallet ----------
    @staticmethod
    def generate_wallet() -> Tuple[str, str]:
        """Создает новый кошелек и Return адрес и приватный ключ.

        Returns:
            Tuple[str, str]: Кортеж с адресом и приватным ключом.
        """
        acc = ERC20.w3.eth.account.create()
        return acc.address, acc.key.hex()

    # ---------- balance ----------
    @staticmethod
    def balance(addr: str) -> Decimal:
        """
        Получает баланс токена ERC20 для указанного адреса.

        :param addr: Адрес, для которого нужно получить баланс (в формате строки).
        :return: Баланс токена в виде Decimal.
        :raises ValueError: Если адрес не является корректным адресом Ethereum.
        """
        abi = [
            {
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "type": "function",
            },
        ]

        # Получение баланса
        bal = (
            ERC20._contract(abi)
            .functions.balanceOf(Web3.to_checksum_address(addr))
            .call()
        )
        return Decimal(bal) / (10**ERC20.decimals)

    # ---------- gas ----------
    @staticmethod
    def estimate_fee(pk: str, amount: Decimal, to_addr: str) -> Decimal:
        """
        Оценивает комиссию за транзакцию при переводе токенов ERC20.

        :param pk: Приватный ключ отправителя (в формате строки).
        :param amount: Сумма токенов для перевода (в формате Decimal).
        :param to_addr: Адрес получателя (в формате строки).
        :return: Оценочная комиссия за транзакцию в ETH (в формате Decimal).
        """
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
                Web3.to_checksum_address(to_addr),
                int(amount * (10**ERC20.decimals)),
            )
            .build_transaction({"from": from_addr})
        )
        gas = ERC20.w3.eth.estimate_gas(tx)
        gas_price = ERC20.w3.eth.gas_price
        return Decimal(gas * gas_price) / (10**18)  # ETH → ETH

    # ---------- transfer ----------
    @staticmethod
    def transfer(pk: str, to_addr: str, amount: Decimal) -> str:
        """Переводит токены на указанный адрес.

        Args:
            pk (str): Приватный ключ отправителя.
            to_addr (str): Адрес получателя.
            amount (Decimal): Сумма перевода.

        Returns:
            str: ID транзакции.
        """
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
                Web3.to_checksum_address(to_addr),
                int(amount * (10**ERC20.decimals)),
            )
            .build_transaction(
                {
                    "from": acct.address,
                    "nonce": nonce,
                    "gasPrice": ERC20.w3.eth.gas_price,
                },
            )
        )
        signed = acct.sign_transaction(tx)
        return ERC20.w3.eth.send_raw_transaction(signed.rawTransaction).hex()


# ------------------------------------------------------------------ BEP-20
class BEP20(TokenNetwork):
    w3 = Web3(Web3.HTTPProvider(os.getenv("BEP_URL")))
    contract_addr = Web3.to_checksum_address(
        os.getenv("USDT_BEP_CONTRACT_ADDR")
    )

    @staticmethod
    def _contract(abi: List[dict]) -> Contract:
        """
        Создает и Return объект контракта на основе заданного ABI.

        Args:
            abi (List[dict]): ABI контракта.

        Returns:
            Contract: Объект контракта, связанный с заданным адресом и ABI.
        """
        return BEP20.w3.eth.contract(address=BEP20.contract_addr, abi=abi)

    @staticmethod
    def generate_wallet() -> Tuple[str, str]:
        """
        Создает новый кошелек и Return адрес и приватный ключ.

        Returns:
            Tuple[str, str]: Кортеж с адресом и приватным ключом.
        """
        acc = BEP20.w3.eth.account.create()
        return acc.address, acc.key.hex()

    @staticmethod
    def balance(addr: str) -> Decimal:
        """
        Получает баланс токенов по адресу.

        Args:
            addr (str): Адрес кошелька.

        Returns:
            Decimal: Баланс токенов.
        """
        abi = [
            {
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "type": "function",
            },
        ]
        bal = (
            BEP20._contract(abi)
            .functions.balanceOf(Web3.to_checksum_address(addr))
            .call()
        )
        return Decimal(bal) / (10**BEP20.decimals)

    @staticmethod
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
                Web3.to_checksum_address(to_addr),
                int(amount * (10**BEP20.decimals)),
            )
            .build_transaction({"from": from_addr})
        )
        gas = BEP20.w3.eth.estimate_gas(tx)
        gas_price = BEP20.w3.eth.gas_price
        return Decimal(gas * gas_price) / (10**18)  # BNB → BNB

    @staticmethod
    def transfer(pk: str, to_addr: str, amount: Decimal) -> str:
        """
        Переводит токены на указанный адрес.

        Args:
            pk (str): Приватный ключ отправителя.
            to_addr (str): Адрес получателя.
            amount (Decimal): Сумма перевода.

        Returns:
            str: ID транзакции.
        """
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
                Web3.to_checksum_address(to_addr),
                int(amount * (10**BEP20.decimals)),
            )
            .build_transaction(
                {
                    "from": acct.address,
                    "nonce": nonce,
                    "gasPrice": BEP20.w3.eth.gas_price,
                },
            )
        )
        signed = acct.sign_transaction(tx)
        return BEP20.w3.eth.send_raw_transaction(signed.rawTransaction).hex()


# ------------------------------------------------------------------ TRC-20


class TronGridJWT:
    def __init__(
        self, private_key_path: str, kid: str, expire_seconds: int = 3600
    ):
        self.private_key_path = private_key_path
        self.kid = kid
        self.expire_seconds = expire_seconds
        self._load_private_key()

    def _load_private_key(self):
        with open(self.private_key_path, "rb") as f:
            self.private_key = f.read()

    def generate_token(self) -> str:
        now = int(time.time())
        payload = {
            "aud": "trongrid.io",
            "exp": now + self.expire_seconds,
        }
        headers = {
            "alg": "RS256",
            "typ": "JWT",
            "kid": self.kid,
        }
        token = jwt.encode(
            payload,
            self.private_key,
            algorithm="RS256",
            headers=headers,
        )
        if isinstance(token, bytes):
            token = token.decode("utf-8")
        return token


class LoggingHTTPProvider(HTTPProvider):
    def __init__(self, endpoint_uri=None, headers=None, **kwargs):
        super().__init__(endpoint_uri=endpoint_uri, **kwargs)
        self._default_headers = headers or {}

    def request(
        self, method: str, path: str, params=None, data=None, headers=None
    ):
        # Объединяем дефолтные заголовки и переданные в вызове
        combined_headers = dict(self._default_headers)
        if headers:
            combined_headers.update(headers)

        logger.info(f"HTTP {method} {self.endpoint_uri}{path}")
        logger.info(f"Headers sent: {combined_headers}")
        logger.info(f"Params: {params}")
        logger.info(f"Data: {data}")

        response = super().request(
            method, path, params, data, combined_headers
        )

        logger.info(f"Response status: {response.status_code}")
        logger.info(f"Response headers: {response.headers}")
        logger.info(f"Response body: {response.text}")

        return response


class TRC20(TokenNetwork):
    contract_addr = os.getenv("USDT_TRC_CONTRACT_ADDR")
    decimals = 6

    # Для JWT авторизации
    _jwt_token = None
    _jwt_expire_at = 0

    # Приватный ключ и kid для JWT
    _jwt_private_key_path = os.getenv(
        "TRONGRID_PRIVATE_KEY_PATH", "private.pem"
    )
    _jwt_kid = os.getenv("TRONGRID_KID")

    @classmethod
    def _get_jwt_token(cls) -> str:
        now = int(time.time())
        # Если токен еще действителен, возвращаем его
        if (
            cls._jwt_token and now < cls._jwt_expire_at - 60
        ):  # обновляем за 1 минуту до истечения
            return cls._jwt_token

        # Иначе генерируем новый токен
        jwt_gen = TronGridJWT(
            private_key_path=cls._jwt_private_key_path,
            kid=cls._jwt_kid,
            expire_seconds=3600,
        )
        cls._jwt_token = jwt_gen.generate_token()
        cls._jwt_expire_at = now + 3600
        logger.info("Generated new TronGrid JWT token")
        return cls._jwt_token

    @classmethod
    def _create_client(cls) -> Tron:
        token = cls._get_jwt_token()
        api_key = os.getenv("TRON_PRO_API_KEY")
        headers = {
            "Authorization": f"Bearer {token}",
            "TRON-PRO-API-KEY": api_key,
            "Content-Type": "application/json",
        }
        provider = LoggingHTTPProvider(
            endpoint_uri="https://api.trongrid.io",
            headers=headers,
        )
        return Tron(provider=provider)

    @classmethod
    def generate_wallet(cls) -> Tuple[str, str]:
        client = cls._create_client()
        acc = client.generate_address()
        return acc["base58check_address"], acc["private_key"]

    @classmethod
    def balance(cls, addr: str) -> Decimal:
        try:
            client = cls._create_client()
            contract = client.get_contract(cls.contract_addr)
            bal = contract.functions.balanceOf(addr).call()
            return Decimal(bal) / (10**cls.decimals)
        except Exception as e:
            logger.error(f"Error getting TRC20 balance for {addr}: {e}")
            return Decimal(0)

    @classmethod
    def estimate_fee(cls, pk: str, amount: Decimal, to_addr: str) -> Decimal:
        try:
            priv = PrivateKey(bytes.fromhex(pk))
            client = cls._create_client()
            contract = client.get_contract(cls.contract_addr)
            txn = (
                contract.functions.transfer(
                    to_addr,
                    int(amount * (10**cls.decimals)),
                )
                .with_owner(priv.public_key.to_base58check_address())
                .fee_limit(10_000_000)
                .build()
            )
            return Decimal(txn.fee_limit) / Decimal(1_000_000)
        except Exception as e:
            logger.error(f"Error estimating fee: {e}")
            return Decimal(0)

    @classmethod
    def transfer(cls, pk: str, to_addr: str, amount: Decimal) -> str:
        try:
            priv = PrivateKey(bytes.fromhex(pk))
            client = cls._create_client()
            contract = client.get_contract(cls.contract_addr)
            txn = (
                contract.functions.transfer(
                    to_addr,
                    int(amount * (10**cls.decimals)),
                )
                .with_owner(priv.public_key.to_base58check_address())
                .fee_limit(10_000_000)
                .build()
                .sign(priv)
            )
            result = txn.broadcast()
            if not result["result"]:
                raise Exception(f"TRC20 transfer failed: {result}")
            return result["txid"]
        except Exception as e:
            logger.error(f"Error during TRC20 transfer: {e}")
            raise
