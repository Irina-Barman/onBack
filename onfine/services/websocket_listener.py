import json
import logging
import os
import threading
import time

from kafka import KafkaProducer
from sqlalchemy.orm import scoped_session
from tronpy import Tron
from tronpy.exceptions import TransactionNotFound
from tronpy.keys import to_base58check_address
from tronpy.providers import HTTPProvider
from web3 import Web3
from web3.middleware import geth_poa_middleware

from onfine.models.wallet import Wallet

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class BlockchainListener:
    def __init__(self, network: str, ws_urls: list[str], contract_addr: str, db_session: scoped_session) -> None:
        self.network = network
        self.ws_urls = ws_urls
        self.contract_addr = Web3.to_checksum_address(contract_addr)
        self.db_session = db_session
        self.topic = "balance_updates"

        self.w3 = None
        self.contract = None
        self.last_block = None

        self.producer = KafkaProducer(
            bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP", "kafka:9092"),
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            retries=3,
            acks="all",
        )

        self.abi = [
            {
                "anonymous": False,
                "inputs": [
                    {"indexed": True, "name": "from", "type": "address"},
                    {"indexed": True, "name": "to", "type": "address"},
                    {"indexed": False, "name": "value", "type": "uint256"},
                ],
                "name": "Transfer",
                "type": "event",
            },
        ]

        self._connect_web3()

    def _connect_web3(self) -> None:
        for url in self.ws_urls:
            try:
                logger.info(f"[{self.network}] Trying node: {url}")
                w3 = Web3(Web3.WebsocketProvider(url))
                if w3.is_connected():
                    logger.info(f"[{self.network}] Connected to node: {url}")
                    if self.network in ("bep20", "polygon"):
                        w3.middleware_onion.inject(geth_poa_middleware, layer=0)
                    self.w3 = w3
                    self.contract = self.w3.eth.contract(address=self.contract_addr, abi=self.abi)
                    self.last_block = self.w3.eth.block_number
                    return
            except Exception as e:
                logger.warning(f"[{self.network}] Node failed: {url} — {e}")
        raise ConnectionError(f"[{self.network}] No available WebSocket nodes could be reached.")

    def start(self):  # noqa ANN202
        threading.Thread(target=self._listen_loop, daemon=True).start()

    def _listen_loop(self):  # noqa ANN202
        logger.info(f"[{self.network}] Polling Transfer events...")
        while True:
            try:
                current_block = self.w3.eth.block_number
                if current_block > self.last_block:
                    logs = self._get_transfer_logs(self.last_block + 1, current_block)
                    for log in logs:
                        self._handle_event(log)
                    self.last_block = current_block
                time.sleep(5)
            except Exception as e:
                logger.error(f"[{self.network}] Polling error: {e}")
                time.sleep(10)
                self._connect_web3()

    def _get_transfer_logs(self, from_block: int, to_block: int):  # noqa ANN202
        signature = "0x" + self.w3.keccak(text="Transfer(address,address,uint256)").hex()
        return self.w3.eth.get_logs(
            {
                "fromBlock": from_block,
                "toBlock": to_block,
                "address": self.contract.address,
                "topics": [signature],
            },
        )

    def _handle_event(self, log):  # noqa ANN001
        try:
            event = self.contract.events.Transfer().process_log(log)
            from_addr = event["args"]["from"]
            to_addr = event["args"]["to"]
            value = event["args"]["value"]

            if self._is_relevant_address(from_addr) or self._is_relevant_address(to_addr):
                data = {
                    "network": self.network,
                    "from": from_addr,
                    "to": to_addr,
                    "value": str(value),
                    "blockNumber": log["blockNumber"],
                    "txHash": log["transactionHash"].hex(),
                }
                self.producer.send(self.topic, value=data)
                logger.info(f"[{self.network}] Kafka event: {data}")
        except Exception as e:
            logger.error(f"[{self.network}] Error processing log: {e}")

    def _is_relevant_address(self, address: str) -> bool:
        # Временно отключено, если база пуста
        return self.db_session.query(Wallet).filter_by(address=address.lower()).first() is not None
        # return True


class TronPollingListener:
    def __init__(self, db_session: scoped_session, network: str = "trc20") -> None:
        self.network = network
        self.db_session = db_session
        self.provider = HTTPProvider(api_key=os.getenv("TRONGRID_API_KEY"))
        self.client = Tron(provider=self.provider)
        self.contract_addr = os.getenv("USDT_TRC_CONTRACT_ADDR")  # Example: "TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj"
        self.topic = "balance_updates"

        self.producer = KafkaProducer(
            bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP", "kafka:9092"),
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            retries=3,
            acks="all",
        )

    def start(self) -> None:
        """Start Thread"""
        threading.Thread(target=self._poll, daemon=True).start()

    def _poll(self) -> None:
        logger.info(f"[{self.network}] Starting TRC20 polling loop...")
        latest = self.client.get_latest_block_number()

        while True:
            try:
                current = self.client.get_latest_block_number()
                if current > latest:
                    for block_num in range(latest + 1, current + 1):
                        block = self.client.get_block(block_num)
                        for tx in block.get("transactions", []):
                            try:
                                tx_info = self.client.get_transaction(tx["txID"])
                            except TransactionNotFound:
                                continue

                            raw_data = tx_info.get("raw_data", {})
                            contracts = raw_data.get("contract", [])
                            if not contracts:
                                continue

                            contract_info = contracts[0]
                            parameter = contract_info.get("parameter", {}).get("value", {})
                            contract_addr_hex = parameter.get("contract_address")
                            if not contract_addr_hex:
                                continue

                            if self.client.from_hex_address(contract_addr_hex) != self.contract_addr:
                                continue

                            from_addr = to_base58check_address(parameter.get("owner_address"))
                            to_addr = to_base58check_address(parameter.get("to_address"))
                            value = parameter.get("amount", 0)

                            if self._is_relevant_address(from_addr) or self._is_relevant_address(to_addr):
                                data = {
                                    "network": self.network,
                                    "from": from_addr,
                                    "to": to_addr,
                                    "value": str(value),
                                    "blockNumber": block_num,
                                    "txHash": tx["txID"],
                                }
                                self.producer.send(self.topic, value=data)
                                logger.info(f"[{self.network}] Kafka event: {data}")

                    latest = current

                time.sleep(10)
            except Exception as e:
                logger.error(f"[{self.network}] TRC polling error: {e}")
                time.sleep(10)

    def _is_relevant_address(self, address: str) -> bool:
        # Закомментируй при пустой БД
        return self.db_session.query(Wallet).filter_by(address=address.lower()).first() is not None
        # return True


def start_websocket_listeners(db_session: scoped_session) -> None:  # noqa D103
    def run() -> None:
        erc_nodes = list(
            filter(
                None,
                [
                    os.getenv("ERC_WS_INFRA_URL"),
                    os.getenv("ERC_WS_ANKR_URL"),
                    os.getenv("ERC_WS_BLAST_URL"),
                    os.getenv("ERC_WS_PUBLIC_NODE_URL"),
                ],
            ),
        )
        bep_nodes = list(
            filter(
                None,
                [
                    os.getenv("BEP_WS_URL"),
                    os.getenv("BEP_WS_ANKR_URL"),
                    os.getenv("BEP_WS_PUBLIC_NODE_URL"),
                    os.getenv("BEP_WS_ON_FINALITY_URL"),
                ],
            ),
        )

        erc_listener = BlockchainListener(
            network="erc20",
            ws_urls=erc_nodes,
            contract_addr=os.getenv("USDT_ERC_CONTRACT_ADDR"),
            db_session=db_session,
        )

        bep_listener = BlockchainListener(
            network="bep20",
            ws_urls=bep_nodes,
            contract_addr=os.getenv("USDT_BEP_CONTRACT_ADDR"),
            db_session=db_session,
        )

        trc_listener = TronPollingListener(db_session=db_session)

        erc_listener.start()
        bep_listener.start()
        trc_listener.start()

    threading.Thread(target=run, daemon=True).start()
    logger.info("Started all blockchain listeners (ERC, BEP, TRC)")
