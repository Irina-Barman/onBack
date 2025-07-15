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

    decimals = (
        6  # Значение по умолчанию, может быть переопределено в наследниках
    )

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
        Возвращает объект контракта ERC20 для взаимодействия с токеном.
        """
        return ERC20.w3.eth.contract(
            address=ERC20.contract_addr, abi=ERC20.abi
        )

    @staticmethod
    def generate_wallet() -> Tuple[str, str]:
        """
        Генерирует новый Ethereum-адрес и приватный ключ.

        Returns:
            Tuple[str, str]: Кортеж (адрес, приватный ключ в hex).
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
        return Decimal(bal) / (10**decimals)

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
            int(amount * (10**ERC20.decimals)),
        ).buildTransaction({"from": acct.address})
        gas = ERC20.w3.eth.estimateGas(tx)
        gas_price = ERC20.w3.eth.gas_price
        # Конвертация газа в ETH
        return Decimal(gas * gas_price) / Decimal(10**18)

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
            int(amount * (10**ERC20.decimals)),
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

    BEP20 — совместим с ERC20, поэтому используется тот же ABI и интерфейс.

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
        return BEP20.w3.eth.contract(
            address=BEP20.contract_addr, abi=BEP20.abi
        )

    @staticmethod
    def generate_wallet() -> Tuple[str, str]:
        """
        Генерирует новый BSC-адрес и приватный ключ.

        Returns:
            Tuple[str, str]: Кортеж (адрес, приватный ключ в hex).
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
        return Decimal(bal) / (10**decimals)

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
            int(amount * (10**BEP20.decimals)),
        ).buildTransaction({"from": acct.address})
        gas = BEP20.w3.eth.estimateGas(tx)
        gas_price = BEP20.w3.eth.gas_price
        return Decimal(gas * gas_price) / Decimal(10**18)

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
            int(amount * (10**BEP20.decimals)),
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

    Использует tronpy для взаимодействия с TronGrid API.

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

        Returns:
            Tuple[str, str]: Кортеж (адрес base58check, приватный ключ).
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
            При ошибке возвращает 0 и выводит сообщение.
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
                int(amount * (10**TRC20.decimals)),
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


class ETH(TokenNetwork):
    """
    Класс для работы с нативным токеном Ethereum (ETH).

    Атрибуты:
        decimals (int): Количество десятичных знаков (18).
        w3 (Web3): Экземпляр Web3.
    """

    decimals = 18
    w3 = Web3(Web3.HTTPProvider(os.getenv("ERC_ANKR_HTTP_URL")))

    @staticmethod
    def generate_wallet() -> Tuple[str, str]:
        acct = ETH.w3.eth.account.create()
        return acct.address, acct.key.hex()

    @staticmethod
    def balance(addr: str) -> Decimal:
        addr = Web3.toChecksumAddress(addr)
        bal = ETH.w3.eth.get_balance(addr)
        return Decimal(bal) / Decimal(10**ETH.decimals)

    @staticmethod
    def estimate_fee(pk: str, amount: Decimal, to_addr: str) -> Decimal:
        acct = ETH.w3.eth.account.privateKeyToAccount(pk)
        to_addr = Web3.toChecksumAddress(to_addr)
        nonce = ETH.w3.eth.getTransactionCount(acct.address)
        tx = {
            "to": to_addr,
            "value": int(amount * (10**ETH.decimals)),
            "nonce": nonce,
            "gasPrice": ETH.w3.eth.gas_price,
        }
        gas = ETH.w3.eth.estimateGas(tx)
        gas_price = ETH.w3.eth.gas_price
        return Decimal(gas * gas_price) / Decimal(10**18)

    @staticmethod
    def transfer(pk: str, to_addr: str, amount: Decimal) -> str:
        acct = ETH.w3.eth.account.privateKeyToAccount(pk)
        to_addr = Web3.toChecksumAddress(to_addr)
        nonce = ETH.w3.eth.getTransactionCount(acct.address)
        tx = {
            "to": to_addr,
            "value": int(amount * (10**ETH.decimals)),
            "nonce": nonce,
            "gasPrice": ETH.w3.eth.gas_price,
        }
        gas = ETH.w3.eth.estimateGas(tx)
        tx["gas"] = gas
        signed = acct.signTransaction(tx)
        tx_hash = ETH.w3.eth.sendRawTransaction(signed.rawTransaction)
        return tx_hash.hex()


class BNB(TokenNetwork):
    """
    Класс для работы с нативным токеном Binance Smart Chain (BNB).

    Атрибуты:
        decimals (int): Количество десятичных знаков (18).
        w3 (Web3): Экземпляр Web3.
    """

    decimals = 18
    w3 = Web3(Web3.HTTPProvider(os.getenv("BEP_ANKR_HTTP_URL")))

    @staticmethod
    def generate_wallet() -> Tuple[str, str]:
        acct = BNB.w3.eth.account.create()
        return acct.address, acct.key.hex()

    @staticmethod
    def balance(addr: str) -> Decimal:
        addr = Web3.toChecksumAddress(addr)
        bal = BNB.w3.eth.get_balance(addr)
        return Decimal(bal) / Decimal(10**BNB.decimals)

    @staticmethod
    def estimate_fee(pk: str, amount: Decimal, to_addr: str) -> Decimal:
        acct = BNB.w3.eth.account.privateKeyToAccount(pk)
        to_addr = Web3.toChecksumAddress(to_addr)
        nonce = BNB.w3.eth.getTransactionCount(acct.address)
        tx = {
            "to": to_addr,
            "value": int(amount * (10**BNB.decimals)),
            "nonce": nonce,
            "gasPrice": BNB.w3.eth.gas_price,
        }
        gas = BNB.w3.eth.estimateGas(tx)
        gas_price = BNB.w3.eth.gas_price
        return Decimal(gas * gas_price) / Decimal(10**18)

    @staticmethod
    def transfer(pk: str, to_addr: str, amount: Decimal) -> str:
        acct = BNB.w3.eth.account.privateKeyToAccount(pk)
        to_addr = Web3.toChecksumAddress(to_addr)
        nonce = BNB.w3.eth.getTransactionCount(acct.address)
        tx = {
            "to": to_addr,
            "value": int(amount * (10**BNB.decimals)),
            "nonce": nonce,
            "gasPrice": BNB.w3.eth.gas_price,
        }
        gas = BNB.w3.eth.estimateGas(tx)
        tx["gas"] = gas
        signed = acct.signTransaction(tx)
        tx_hash = BNB.w3.eth.sendRawTransaction(signed.rawTransaction)
        return tx_hash.hex()


class TRX(TokenNetwork):
    """
    Класс для работы с нативным токеном Tron (TRX).

    Атрибуты:
        decimals (int): Количество десятичных знаков (6).
        client (Tron): Клиент TronPy.
    """

    decimals = 6
    client = Tron(provider=HTTPProvider(api_key=os.getenv("TRONGRID_API_KEY")))

    @staticmethod
    def generate_wallet() -> Tuple[str, str]:
        acc = TRX.client.generate_address()
        return acc["base58check_address"], acc["private_key"]

    @staticmethod
    def balance(addr: str) -> Decimal:
        try:
            bal = TRX.client.get_account_balance(addr)
            return Decimal(bal) / Decimal(10**TRX.decimals)
        except Exception as e:
            print(f"Error getting TRX balance for {addr}: {e}")
            return Decimal(0)

    @staticmethod
    def estimate_fee(pk: str, amount: Decimal, to_addr: str) -> Decimal:
        # В сети Tron комиссия обычно фиксирована, например 0.001 TRX
        return Decimal("0.001")

    @staticmethod
    def transfer(pk: str, to_addr: str, amount: Decimal) -> str:
        priv = PrivateKey(bytes.fromhex(pk))
        txn = (
            TRX.client.trx.transfer(
                priv.public_key.to_base58check_address(),
                to_addr,
                int(amount * (10**TRX.decimals)),
            )
            .build()
            .sign(priv)
        )
        result = txn.broadcast()
        if not result["result"]:
            raise Exception(f"TRX transfer failed: {result}")
        return result["txid"]


# Пример использования (закомментирован)
# if __name__ == "__main__":
#     erc20 = ERC20()
#     bep20 = BEP20()
#     wallet = erc20.generate_wallet()
#     print("ERC20 Wallet:", wallet)
#     balance = bep20.balance("0x...")
#     print("BEP20 Balance:", balance)
