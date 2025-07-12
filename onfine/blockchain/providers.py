import os
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import List, Tuple

from cryptography.fernet import Fernet
from tronpy import Tron
from tronpy.keys import PrivateKey
from tronpy.providers import HTTPProvider
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
    w3 = Web3(Web3.HTTPProvider(os.getenv("ERC_URL")))
    contract_addr = Web3.to_checksum_address(os.getenv("USDT_ERC_CONTRACT_ADDR"))

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
        bal = ERC20._contract(abi).functions.balanceOf(Web3.to_checksum_address(addr)).call()
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
    contract_addr = Web3.to_checksum_address(os.getenv("USDT_BEP_CONTRACT_ADDR"))

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
        bal = BEP20._contract(abi).functions.balanceOf(Web3.to_checksum_address(addr)).call()
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
    client = Tron(provider=HTTPProvider(api_key=os.getenv("TRONGRID_API_KEY")))
    contract_addr = os.getenv("USDT_TRC_CONTRACT_ADDR")
    decimals = 6

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

    @staticmethod
    def balance(addr: str) -> Decimal:
        """
        Получает баланс TRC20 токенов для указанного адреса.

        Args:
            addr (str): Адрес TRON кошелька (base58check формат).

        Returns:
            Decimal: Баланс токенов с учётом десятичных знаков.
        """
        try:
            contract = TRC20.client.get_contract(TRC20.contract_addr)
            bal = contract.functions.balanceOf(addr).call()
            return Decimal(bal) / (10**TRC20.decimals)
        except Exception as e:
            print(f"Error getting TRC20 balance for {addr}: {e}")
            return Decimal(0)

    @staticmethod
    def estimate_fee(pk: str, amount: Decimal, to_addr: str) -> Decimal:
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
        contract = TRC20.client.get_contract(TRC20.contract_addr)

        # Формируем транзакцию вызова transfer с лимитом комиссии (fee_limit)
        txn = (
            contract.functions.transfer(
                to_addr,
                int(amount * (10**TRC20.decimals)),
            )
            .with_owner(priv.public_key.to_base58check_address())
            .fee_limit(10_000_000)  # 10 TRX в сун (1 TRX = 1_000_000 сун)
            .build()
        )
        # Возвращаем fee_limit в TRX
        return Decimal(txn.fee_limit) / Decimal(1_000_000)

    @staticmethod
    def transfer(pk: str, to_addr: str, amount: Decimal) -> str:
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
        contract = TRC20.client.get_contract(TRC20.contract_addr)

        txn = (
            contract.functions.transfer(
                to_addr,
                int(amount * (10**TRC20.decimals)),
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