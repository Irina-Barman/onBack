import os
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import List, Tuple

from cryptography.fernet import Fernet
from tronpy import Tron
from tronpy.keys import PrivateKey
from web3 import Web3
from web3.contract import Contract

FERNET = Fernet(os.getenv("FERNET_KEY").encode())


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
    infura_key = os.getenv("INFURA_API_KEY")
    w3 = Web3(Web3.HTTPProvider(f"https://mainnet.infura.io/v3/{infura_key}"))
    contract_addr = Web3.to_checksum_address(
        "0xdAC17F958D2ee523a2206206994597C13D831ec7",
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
    w3 = Web3(Web3.HTTPProvider("https://bsc-dataseed.binance.org"))
    contract_addr = Web3.to_checksum_address(
        "0x55d398326f99059fF775485246999027B3197955",
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
class TRC20(TokenNetwork):
    client = Tron()
    contract_addr = "TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf"

    @staticmethod
    def generate_wallet() -> Tuple[str, str]:
        """
        Создает новый кошелек и Return адрес и приватный ключ.

        Returns:
            Tuple[str, str]: Кортеж с адресом и приватным ключом.
        """
        acc = TRC20.client.generate_address()
        return acc["base58check_address"], acc["private_key"]

    @staticmethod
    def balance(addr: str) -> Decimal:
        """
        Получает баланс токенов по адресу.

        Args:
            addr (str): Адрес кошелька.

        Returns:
            Decimal: Баланс токенов.
        """
        contract = TRC20.client.get_contract(TRC20.contract_addr)
        bal = contract.functions.balanceOf(addr)
        return Decimal(bal) / (10**TRC20.decimals)

    @staticmethod
    def estimate_fee(pk: str, amount: Decimal, to_addr: str) -> Decimal:
        """
        Оценивает комиссию за перевод токенов.

        Args:
            pk (str): Приватный ключ отправителя в шестнадцатеричном формате.
            amount (Decimal): Сумма перевода.
            to_addr (str): Адрес получателя.

        Returns:
            Decimal: Оцененная комиссия.
        """
        priv = PrivateKey(bytes.fromhex(pk))
        txn = (
            TRC20.client.trx.transfer(
                priv.public_key.to_base58check_address(),
                to_addr,
                int(amount * (10**TRC20.decimals)),
            )
            .build()
            .inspect()
        )
        return Decimal(txn.fee) / (10**6)

    @staticmethod
    def transfer(pk: str, to_addr: str, amount: Decimal) -> str:
        """Переводит токены на указанный адрес.

        Args:
            pk (str): Приватный ключ отправителя в шестнадцатеричном формате.
            to_addr (str): Адрес получателя.
            amount (Decimal): Сумма перевода.

        Returns:
            str: ID транзакции.
        """
        priv = PrivateKey(bytes.fromhex(pk))
        tx = (
            TRC20.client.trx.transfer(
                priv.public_key.to_base58check_address(),
                to_addr,
                int(amount * (10**TRC20.decimals)),
            )
            .build()
            .sign(priv)
            .broadcast()
        )
        return tx["txid"]
