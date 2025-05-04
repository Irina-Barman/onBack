import os
from decimal import Decimal
from abc import ABC, abstractmethod
from typing import Tuple

from cryptography.fernet import Fernet
from web3 import Web3
from tronpy import Tron
from tronpy.keys import PrivateKey

FERNET = Fernet(os.getenv("FERNET_KEY").encode())


# ---------------------------------------------------------------------- base
class TokenNetwork(ABC):
    symbol = "USDT"
    decimals = 6

    @staticmethod
    @abstractmethod
    def generate_wallet() -> Tuple[str, str]:
        """return (address, private_key)"""

    @staticmethod
    @abstractmethod
    def balance(addr: str) -> Decimal:
        ...

    @staticmethod
    @abstractmethod
    def estimate_fee(pk: str, amount: Decimal, to_addr: str) -> Decimal:
        ...

    @staticmethod
    @abstractmethod
    def transfer(pk: str, to_addr: str, amount: Decimal) -> str:
        ...


# ------------------------------------------------------------------ ERC-20
class ERC20(TokenNetwork):
    infura_key = os.getenv("INFURA_API_KEY")
    w3 = Web3(Web3.HTTPProvider(f"https://mainnet.infura.io/v3/{infura_key}"))
    contract_addr = Web3.to_checksum_address("0xdAC17F958D2ee523a2206206994597C13D831ec7")

    @staticmethod
    def _contract(abi):
        return ERC20.w3.eth.contract(address=ERC20.contract_addr, abi=abi)

    # ---------- wallet ----------
    @staticmethod
    def generate_wallet() -> Tuple[str, str]:
        acc = ERC20.w3.eth.account.create()
        return acc.address, acc.key.hex()

    # ---------- balance ----------
    @staticmethod
    def balance(addr: str) -> Decimal:
        abi = [{"constant": True,"inputs":[{"name":"_owner","type":"address"}],
                "name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"}]
        bal = ERC20._contract(abi).functions.balanceOf(Web3.to_checksum_address(addr)).call()
        return Decimal(bal) / (10 ** ERC20.decimals)

    # ---------- gas ----------
    @staticmethod
    def estimate_fee(pk: str, amount: Decimal, to_addr: str) -> Decimal:
        from_addr = ERC20.w3.eth.account.privateKeyToAccount(pk).address
        abi = [{"constant":False,"inputs":[{"name":"_to","type":"address"},
                                           {"name":"_value","type":"uint256"}],
                "name":"transfer","outputs":[{"name":"","type":"bool"}],"type":"function"}]
        tx = ERC20._contract(abi).functions.transfer(
                Web3.to_checksum_address(to_addr),
                int(amount * (10**ERC20.decimals))
            ).build_transaction({"from": from_addr})
        gas = ERC20.w3.eth.estimate_gas(tx)
        gas_price = ERC20.w3.eth.gas_price
        return Decimal(gas * gas_price) / (10 ** 18)    # ETH → ETH

    # ---------- transfer ----------
    @staticmethod
    def transfer(pk: str, to_addr: str, amount: Decimal) -> str:
        acct = ERC20.w3.eth.account.privateKeyToAccount(pk)
        nonce = ERC20.w3.eth.get_transaction_count(acct.address)
        abi = [{"constant":False,"inputs":[{"name":"_to","type":"address"},
                                           {"name":"_value","type":"uint256"}],
                "name":"transfer","outputs":[{"name":"","type":"bool"}],"type":"function"}]
        tx = ERC20._contract(abi).functions.transfer(
                Web3.to_checksum_address(to_addr),
                int(amount * (10 ** ERC20.decimals))
            ).build_transaction({
                "from": acct.address,
                "nonce": nonce,
                "gasPrice": ERC20.w3.eth.gas_price
            })
        signed = acct.sign_transaction(tx)
        return ERC20.w3.eth.send_raw_transaction(signed.rawTransaction).hex()


# ------------------------------------------------------------------ BEP-20
class BEP20(TokenNetwork):
    w3 = Web3(Web3.HTTPProvider("https://bsc-dataseed.binance.org"))
    contract_addr = Web3.to_checksum_address("0x55d398326f99059fF775485246999027B3197955")

    @staticmethod
    def _contract(abi):
        return BEP20.w3.eth.contract(address=BEP20.contract_addr, abi=abi)

    @staticmethod
    def generate_wallet():
        acc = BEP20.w3.eth.account.create()
        return acc.address, acc.key.hex()

    @staticmethod
    def balance(addr: str) -> Decimal:
        abi = [{"constant": True,"inputs":[{"name":"_owner","type":"address"}],
                "name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"}]
        bal = BEP20._contract(abi).functions.balanceOf(Web3.to_checksum_address(addr)).call()
        return Decimal(bal) / (10 ** BEP20.decimals)

    @staticmethod
    def estimate_fee(pk, amount, to_addr):
        from_addr = BEP20.w3.eth.account.privateKeyToAccount(pk).address
        abi = [{"constant":False,"inputs":[{"name":"_to","type":"address"},
                                           {"name":"_value","type":"uint256"}],
                "name":"transfer","outputs":[{"name":"","type":"bool"}],"type":"function"}]
        tx = BEP20._contract(abi).functions.transfer(
                Web3.to_checksum_address(to_addr),
                int(amount * (10**BEP20.decimals))
            ).build_transaction({"from": from_addr})
        gas = BEP20.w3.eth.estimate_gas(tx)
        gas_price = BEP20.w3.eth.gas_price
        return Decimal(gas * gas_price) / (10 ** 18)     # BNB → BNB

    @staticmethod
    def transfer(pk, to_addr, amount):
        acct = BEP20.w3.eth.account.privateKeyToAccount(pk)
        nonce = BEP20.w3.eth.get_transaction_count(acct.address)
        abi = [{"constant":False,"inputs":[{"name":"_to","type":"address"},
                                           {"name":"_value","type":"uint256"}],
                "name":"transfer","outputs":[{"name":"","type":"bool"}],"type":"function"}]
        tx = BEP20._contract(abi).functions.transfer(
            Web3.to_checksum_address(to_addr),
            int(amount * (10 ** BEP20.decimals))
        ).build_transaction({
            "from": acct.address,
            "nonce": nonce,
            "gasPrice": BEP20.w3.eth.gas_price
        })
        signed = acct.sign_transaction(tx)
        return BEP20.w3.eth.send_raw_transaction(signed.rawTransaction).hex()


# ------------------------------------------------------------------ TRC-20
class TRC20(TokenNetwork):
    client = Tron()
    contract_addr = "TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf"

    @staticmethod
    def generate_wallet():
        acc = TRC20.client.generate_address()
        return acc["base58check_address"], acc["private_key"]

    @staticmethod
    def balance(addr: str) -> Decimal:
        contract = TRC20.client.get_contract(TRC20.contract_addr)
        bal = contract.functions.balanceOf(addr)
        return Decimal(bal) / (10 ** TRC20.decimals)

    @staticmethod
    def estimate_fee(pk, amount, to_addr):
        priv = PrivateKey(bytes.fromhex(pk))
        txn = (
            TRC20.client.trx.transfer(priv.public_key.to_base58check_address(),
                                      to_addr,
                                      int(amount * (10**TRC20.decimals)))
            .build()
            .inspect()
        )
        return Decimal(txn.fee) / (10 ** 6)

    @staticmethod
    def transfer(pk, to_addr, amount):
        priv = PrivateKey(bytes.fromhex(pk))
        tx = (
            TRC20.client.trx.transfer(priv.public_key.to_base58check_address(),
                                      to_addr,
                                      int(amount * (10 ** TRC20.decimals)))
            .build()
            .sign(priv)
            .broadcast()
        )
        return tx["txid"]
