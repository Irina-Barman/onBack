import os
from decimal import Decimal
from typing import Tuple

from tronpy import Tron
from tronpy.keys import PrivateKey
from tronpy.providers import HTTPProvider
from web3 import Web3
from web3.contract import Contract

from onfine.blockchain.token_abi_loder import load_abi

# Загружаем полный ABI стандарта ERC20 один раз для повторного использования
ERC20_ABI = load_abi()


class TokenNetwork:
    """
    Абстрактный базовый класс для работы с токенами в разных сетях.

    Атрибуты:
        decimals (int): Количество десятичных знаков токена (по умолчанию 6).

    Методы (статические, должны быть реализованы в наследниках):
        generate_wallet() -> Tuple[str, str]:
            Генерация нового кошелька (адрес и приватный ключ).

        balance(address: str) -> Decimal:
            Получение баланса токена на указанном адресе.

        estimate_fee(pk: str, amount: Decimal, to_addr: str) -> Decimal:
            Оценка комиссии (газа) за перевод токена.

        transfer(pk: str, to_addr: str, amount: Decimal) -> str:
            Отправка токена с приватного ключа на указанный адрес,
            возвращает хэш транзакции.
    """

    decimals = 6  # Значение по умолчанию, может быть переопределено в наследниках

    @staticmethod
    def generate_wallet() -> Tuple[str, str]:
        raise NotImplementedError()

    @staticmethod
    def balance(address: str) -> Decimal:
        raise NotImplementedError()

    @staticmethod
    def estimate_fee(pk: str, amount: Decimal, to_addr: str) -> Decimal:
        raise NotImplementedError()

    @staticmethod
    def transfer(pk: str, to_addr: str, amount: Decimal) -> str:
        raise NotImplementedError()


class ERC20(TokenNetwork):
    """
    Класс для работы с ERC20 токенами в сети Ethereum.

    Использует Web3.py для взаимодействия с Ethereum узлом.
    Все методы статические, работают через переменные класса.

    Атрибуты:
        decimals (int): Количество десятичных знаков токена (6).
        w3 (Web3): Экземпляр Web3, инициализированный через HTTP провайдера.
        contract_addr (str): Адрес контракта токена в сети Ethereum.
        abi (list): ABI контракта токена (ERC20 стандарт).
    """

    decimals = 6
    w3 = Web3(Web3.HTTPProvider(os.getenv("ERC_ANKR_HTTP_URL")))
    contract_addr = Web3.toChecksumAddress(os.getenv("USDT_ERC_CONTRACT_ADDR"))
    abi = ERC20_ABI

    @staticmethod
    def _contract() -> Contract:
        """
        Возвращает объект контракта ERC20 для взаимодействия.
        """
        return ERC20.w3.eth.contract(address=ERC20.contract_addr, abi=ERC20.abi)

    @staticmethod
    def generate_wallet() -> Tuple[str, str]:
        """
        Генерирует новый Ethereum-адрес и приватный ключ.

        Возвращает:
            Tuple[str, str]: Кортеж с адресом и приватным ключом в hex.
        """
        acct = ERC20.w3.eth.account.create()
        return acct.address, acct.key.hex()

    @staticmethod
    def balance(addr: str) -> Decimal:
        """
        Получает баланс токена ERC20 на указанном адресе.

        Args:
            addr (str): Ethereum-адрес.

        Returns:
            Decimal: Баланс токена с учётом десятичных знаков.
        """
        addr = Web3.toChecksumAddress(addr)
        contract = ERC20._contract()
        bal = contract.functions.balanceOf(addr).call()
        decimals = contract.functions.decimals().call()
        return Decimal(bal) / (10 ** decimals)

    @staticmethod
    def estimate_fee(pk: str, amount: Decimal, to_addr: str) -> Decimal:
        """
        Оценивает комиссию за перевод ERC20 токена.

        Args:
            pk (str): Приватный ключ отправителя в hex.
            amount (Decimal): Сумма токенов для перевода.
            to_addr (str): Адрес получателя.

        Returns:
            Decimal: Оценка комиссии в ETH.
        """
        acct = ERC20.w3.eth.account.privateKeyToAccount(pk)
        to_addr = Web3.toChecksumAddress(to_addr)
        contract = ERC20._contract()
        tx = contract.functions.transfer(
            to_addr,
            int(amount * (10 ** ERC20.decimals)),
        ).buildTransaction({"from": acct.address})
        gas = ERC20.w3.eth.estimateGas(tx)
        gas_price = ERC20.w3.eth.gas_price
        return Decimal(gas * gas_price) / Decimal(10 ** 18)

    @staticmethod
    def transfer(pk: str, to_addr: str, amount: Decimal) -> str:
        """
        Отправляет ERC20 токены с кошелька, заданного приватным ключом.

        Args:
            pk (str): Приватный ключ отправителя в hex.
            to_addr (str): Адрес получателя.
            amount (Decimal): Количество токенов для перевода.

        Returns:
            str: Хэш транзакции.
        """
        acct = ERC20.w3.eth.account.privateKeyToAccount(pk)
        to_addr = Web3.toChecksumAddress(to_addr)
        nonce = ERC20.w3.eth.getTransactionCount(acct.address)
        contract = ERC20._contract()
        tx = contract.functions.transfer(
            to_addr,
            int(amount * (10 ** ERC20.decimals)),
        ).buildTransaction(
            {
                "from": acct.address,
                "nonce": nonce,
                "gasPrice": ERC20.w3.eth.gas_price,
            }
        )
        signed = acct.signTransaction(tx)
        tx_hash = ERC20.w3.eth.sendRawTransaction(signed.rawTransaction)
        return tx_hash.hex()


class BEP20(TokenNetwork):
    """
    Класс для работы с BEP20 токенами в сети Binance Smart Chain.

    BEP20 — это стандарт токенов, совместимый с ERC20,
    поэтому используется тот же ABI и аналогичный интерфейс.

    Атрибуты:
        decimals (int): Количество десятичных знаков (6).
        w3 (Web3): Экземпляр Web3 для BSC.
        contract_addr (str): Адрес контракта токена BEP20.
        abi (list): ABI контракта токена (тот же, что и ERC20).
    """

    decimals = 6
    w3 = Web3(Web3.HTTPProvider(os.getenv("BEP_ANKR_HTTP_URL")))
    contract_addr = Web3.toChecksumAddress(os.getenv("USDT_BEP_CONTRACT_ADDR"))
    abi = ERC20_ABI  # BEP20 — тот же стандарт ERC20

    @staticmethod
    def _contract() -> Contract:
        """
        Возвращает объект контракта BEP20 для взаимодействия.
        """
        return BEP20.w3.eth.contract(address=BEP20.contract_addr, abi=BEP20.abi)

    @staticmethod
    def generate_wallet() -> Tuple[str, str]:
        """
        Генерирует новый BSC-адрес и приватный ключ.

        Возвращает:
            Tuple[str, str]: Кортеж с адресом и приватным ключом в hex.
        """
        acct = BEP20.w3.eth.account.create()
        return acct.address, acct.key.hex()

    @staticmethod
    def balance(addr: str) -> Decimal:
        """
        Получает баланс токена BEP20 на указанном адресе.

        Args:
            addr (str): BSC-адрес.

        Returns:
            Decimal: Баланс токена с учётом десятичных знаков.
        """
        addr = Web3.toChecksumAddress(addr)
        contract = BEP20._contract()
        bal = contract.functions.balanceOf(addr).call()
        decimals = contract.functions.decimals().call()
        return Decimal(bal) / (10 ** decimals)

    @staticmethod
    def estimate_fee(pk: str, amount: Decimal, to_addr: str) -> Decimal:
        """
        Оценивает комиссию за перевод BEP20 токена.

        Args:
            pk (str): Приватный ключ отправителя в hex.
            amount (Decimal): Сумма токенов для перевода.
            to_addr (str): Адрес получателя.

        Returns:
            Decimal: Оценка комиссии в BNB.
        """
        acct = BEP20.w3.eth.account.privateKeyToAccount(pk)
        to_addr = Web3.toChecksumAddress(to_addr)
        contract = BEP20._contract()
        tx = contract.functions.transfer(
            to_addr,
            int(amount * (10 ** BEP20.decimals)),
        ).buildTransaction({"from": acct.address})
        gas = BEP20.w3.eth.estimateGas(tx)
        gas_price = BEP20.w3.eth.gas_price
        return Decimal(gas * gas_price) / Decimal(10 ** 18)

    @staticmethod
    def transfer(pk: str, to_addr: str, amount: Decimal) -> str:
        """
        Отправляет BEP20 токены с кошелька, заданного приватным ключом.

        Args:
            pk (str): Приватный ключ отправителя в hex.
            to_addr (str): Адрес получателя.
            amount (Decimal): Количество токенов для перевода.

        Returns:
            str: Хэш транзакции.
        """
        acct = BEP20.w3.eth.account.privateKeyToAccount(pk)
        to_addr = Web3.toChecksumAddress(to_addr)
        nonce = BEP20.w3.eth.getTransactionCount(acct.address)
        contract = BEP20._contract()
        tx = contract.functions.transfer(
            to_addr,
            int(amount * (10 ** BEP20.decimals)),
        ).buildTransaction(
            {
                "from": acct.address,
                "nonce": nonce,
                "gasPrice": BEP20.w3.eth.gas_price,
            }
        )
        signed = acct.signTransaction(tx)
        tx_hash = BEP20.w3.eth.sendRawTransaction(signed.rawTransaction)
        return tx_hash.hex()


class TRC20(TokenNetwork):
    """
    Класс для работы с TRC20 токенами в сети Tron.

    Использует библиотеку tronpy для взаимодействия с TronGrid API.

    Атрибуты:
        decimals (int): Количество десятичных знаков токена (6).
        client (Tron): Клиент TronPy с HTTP провайдером.
        contract_addr (str): Адрес контракта TRC20 токена.
    """

    decimals = 6
    client = Tron(provider=HTTPProvider(api_key=os.getenv("TRONGRID_API_KEY")))
    contract_addr = os.getenv("USDT_TRC_CONTRACT_ADDR")

    @staticmethod
    def generate_wallet() -> Tuple[str, str]:
        """
        Генерирует новый Tron-кошелёк.

        Возвращает:
            Tuple[str, str]: Кортеж с адресом в base58check и приватным ключом.
        """
        acc = TRC20.client.generate_address()
        return acc["base58check_address"], acc["private_key"]

    @staticmethod
    def balance(addr: str) -> Decimal:
        """
        Получает баланс TRC20 токена на указанном адресе.

        Args:
            addr (str): Tron адрес (base58check).

        Returns:
            Decimal: Баланс токена с учётом десятичных знаков.
            В случае ошибки возвращает 0 и выводит сообщение.
        """
        try:
            contract = TRC20.client.get_contract(TRC20.contract_addr)
            bal = contract.functions.balanceOf(addr).call()
            return Decimal(bal) / (10 ** TRC20.decimals)
        except Exception as e:
            print(f"Error getting TRC20 balance for {addr}: {e}")
            return Decimal(0)

    @staticmethod
    def estimate_fee(pk: str, amount: Decimal, to_addr: str) -> Decimal:
        """
        Оценивает комиссию за перевод TRC20 токена.

        Args:
            pk (str): Приватный ключ отправителя в hex.
            amount (Decimal): Сумма токенов для перевода.
            to_addr (str): Адрес получателя.

        Returns:
            Decimal: Оценка комиссии в TRX.
        """
        priv = PrivateKey(bytes.fromhex(pk))
        contract = TRC20.client.get_contract(TRC20.contract_addr)
        txn = (
            contract.functions.transfer(
                to_addr,
                int(amount * (10 ** TRC20.decimals)),
            )
            .with_owner(priv.public_key.to_base58check_address())
            .fee_limit(10_000_000)  # Максимальная комиссия 10 TRX (в сун)
            .build()
        )
        return Decimal(txn.fee_limit) / Decimal(1_000_000)

    @staticmethod
    def transfer(pk: str, to_addr: str, amount: Decimal) -> str:
        """
        Отправляет TRC20 токены с кошелька, заданного приватным ключом.

        Args:
            pk (str): Приватный ключ отправителя в hex.
            to_addr (str): Адрес получателя.
            amount (Decimal): Количество токенов для перевода.

        Возвращает:
            str: ID транзакции (txid).

        Исключения:
            Exception: Если транзакция не была успешно отправлена.
        """
        priv = PrivateKey(bytes.fromhex(pk))
        contract = TRC20.client.get_contract(TRC20.contract_addr)
        txn = (
            contract.functions.transfer(
                to_addr,
                int(amount * (10 ** TRC20.decimals)),
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


# Пример использования (закомментирован)
# if __name__ == "__main__":
#     blockcain = TokenNetwork("erc20")
#     blockcain_bep = TokenNetwork("bep20")
#     wallet = blockcain.generate_wallet()
#     BEP20.balance("feffeffee")
