import json
import logging
import os
import threading
import time
import traceback
from http.client import RemoteDisconnected
from typing import Optional

import requests
from flask import Flask
from kafka import KafkaProducer
from requests.exceptions import ConnectionError, HTTPError
from sqlalchemy.orm import scoped_session
from tronpy import Tron
from tronpy.exceptions import TransactionNotFound
from tronpy.keys import to_base58check_address
from tronpy.providers import HTTPProvider
from web3 import Web3
from web3.middleware import geth_poa_middleware

from onfine.app_factory import create_app
from onfine.models.wallet import Wallet
from onfine.utils.tron_utils import from_hex_address, normalize_tron_address

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class BlockchainListener:
    """
    Класс для прослушивания событий Transfer на Ethereum-подобных блокчейнах (ERC20, BEP20, Polygon).

    Особенности:
    - Подключается к WebSocket нодам с возможностью переключения между несколькими URL.
    - Периодически опрашивает новые блоки и получает логи событий Transfer.
    - Фильтрует события по релевантным адресам из базы данных.
    - Отправляет события в Kafka для дальнейшей обработки.
    - Использует экспоненциальный backoff при ошибках подключения.

    Атрибуты:
        network (str): Название сети (например, "erc20", "bep20", "polygon").
        ws_urls (list[str]): Список WebSocket URL нод для подключения.
        contract_addr (str): Адрес контракта токена в формате checksum.
        app (Flask): Flask приложение для контекста.
        db_session (scoped_session): Сессия базы данных для запросов.
    """

    def __init__(
        self,
        network: str,
        ws_urls: list[str],
        contract_addr: str,
        app: Flask,
        db_session: scoped_session,
    ) -> None:
        self.network = network
        self.ws_urls = ws_urls
        self.contract_addr = Web3.to_checksum_address(contract_addr)
        self.db_session = db_session
        self.app = app
        self.topic = "balance_updates"

        self.w3 = None  # Web3 объект
        self.contract = None  # Контракт токена
        self.last_block = None  # Последний обработанный блок
        self.current_node_index = 0  # Индекс текущей ноды из ws_urls
        self.retry_delay = 1  # Задержка для повторных попыток подключения (секунды)

        # Kafka продюсер для отправки сообщений
        self.producer = KafkaProducer(
            bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP", "kafka:9092"),
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            retries=3,
            acks="all",
        )

        # ABI для события Transfer (стандарт ERC20)
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

        self.transfer_signature = None  # Хэш сигнатуры события Transfer
        self._connect_web3()

    def _disconnect_web3(self):
        """
        Отключает текущее Web3 соединение, если возможно.
        Позволяет корректно закрыть WebSocket соединение.
        """
        if self.w3 and self.w3.provider:
            try:
                if hasattr(self.w3.provider, "disconnect"):
                    self.w3.provider.disconnect()
                    logger.info(f"[{self.network}] WebSocket disconnected")
            except Exception as e:
                logger.warning(
                    f"[{self.network}] Error disconnecting WebSocket: {e}"
                )
        self.w3 = None
        self.contract = None
        self.transfer_signature = None

    def _connect_web3(self) -> None:
        """
        Пытается подключиться к WebSocket нодам по очереди, начиная с текущего индекса.
        При неудаче переключается на следующую ноду с экспоненциальным backoff.
        Устанавливает контракт и сохраняет последний номер блока.
        """
        self._disconnect_web3()
        total_nodes = len(self.ws_urls)
        attempts = 0

        while attempts < total_nodes:
            url = self.ws_urls[self.current_node_index]
            try:
                logger.info(f"[{self.network}] Trying node: {url}")
                w3 = Web3(Web3.WebsocketProvider(url))
                if w3.is_connected():
                    logger.info(f"[{self.network}] Connected to node: {url}")
                    # Для сетей с Proof of Authority (BEP20, Polygon) добавляем middleware
                    if self.network in ("bep20", "polygon"):
                        w3.middleware_onion.inject(geth_poa_middleware, layer=0)
                    self.w3 = w3
                    self.contract = self.w3.eth.contract(address=self.contract_addr, abi=self.abi)
                    self.last_block = self.w3.eth.block_number
                    self.retry_delay = 1
                    self.transfer_signature = Web3.to_hex(self.w3.keccak(text="Transfer(address,address,uint256)"))
                    return
                else:
                    raise ConnectionError("Web3 not connected")
            except Exception as e:
                logger.warning(f"[{self.network}] Node failed: {url} — {e}")
                self.current_node_index = (self.current_node_index + 1) % total_nodes
                attempts += 1
                logger.info(f"[{self.network}] Switching to next node after failure, sleeping {self.retry_delay}s")
                time.sleep(self.retry_delay)
                self.retry_delay = min(self.retry_delay * 2, 60)

        raise ConnectionError(f"[{self.network}] No available WebSocket nodes could be reached.")

    def _get_current_block(self) -> Optional[int]:
        """
        Возвращает текущий номер блока в сети.
        При ошибке возвращает None.
        """
        try:
            return self.w3.eth.block_number
        except Exception as e:
            logger.error(f"[{self.network}] Failed to get block_number: {e}")
            return None

    def start(self):  # noqa ANN202
        """
        Запускает прослушивание в отдельном демоническом потоке.
        """
        threading.Thread(target=self._listen_loop, daemon=True).start()

    def _listen_loop(self):
        """
        Основной цикл прослушивания событий Transfer.
        Периодически опрашивает новые блоки, получает логи и обрабатывает события.
        При потере соединения пытается переподключиться.
        """
        logger.info(f"[{self.network}] Polling Transfer events...")
        while True:
            try:
                if self.w3 is None or not self.w3.is_connected():
                    logger.warning(f"[{self.network}] Lost connection, reconnecting...")
                    self._connect_web3()

                current_block = self._get_current_block()
                if current_block is None:
                    logger.info(f"[{self.network}] Waiting before retrying block_number fetch...")
                    time.sleep(10)
                    self._connect_web3()
                    continue

                if current_block > self.last_block:
                    logs = self._get_transfer_logs(self.last_block + 1, current_block)
                    for log in logs:
                        self._handle_event(log)
                    self.last_block = current_block

                time.sleep(10)  # увеличен интервал для снижения нагрузки
            except Exception as e:
                logger.error(f"[{self.network}] Polling error: {e}\n{traceback.format_exc()}")
                time.sleep(10)
                try:
                    self._connect_web3()
                except Exception as e2:
                    logger.error(f"[{self.network}] Reconnect failed: {e2}")

    def _get_transfer_logs(self, from_block: int, to_block: int):
        """
        Получает логи событий Transfer за диапазон блоков, разбивая запросы на чанки по 100 блоков.
        При ошибках переключается между нодами и пытается переподключиться.
        Если все ноды не отвечают, пропускает проблемный диапазон блоков.
        """
        max_chunk = 100
        all_logs = []
        start = from_block
        total_nodes = len(self.ws_urls)

        while start <= to_block:
            end = min(start + max_chunk - 1, to_block)
            attempts = 0
            success = False

            while attempts < total_nodes and not success:
                try:
                    chunk_logs = self.w3.eth.get_logs(
                        {
                            "fromBlock": start,
                            "toBlock": end,
                            "address": self.contract.address,
                            "topics": [self.transfer_signature],
                        }
                    )
                    all_logs.extend(chunk_logs)
                    success = True
                except Exception as e:
                    logger.warning(f"[{self.network}] get_logs failed for blocks {start}-{end} on node {self.ws_urls[self.current_node_index]}: {e}")
                    self.current_node_index = (self.current_node_index + 1) % total_nodes
                    try:
                        self._connect_web3()
                    except Exception as conn_err:
                        logger.error(f"[{self.network}] Reconnect failed after get_logs error: {conn_err}")
                    time.sleep(5)
                    attempts += 1

            if not success:
                logger.error(f"[{self.network}] Failed to fetch logs for blocks {start}-{end} after retries on all nodes")
                # Пропускаем этот диапазон блоков, чтобы не блокировать цикл
                start = end + 1
                continue

            start = end + 1

        return all_logs

    def _handle_event(self, log):
        """
        Обрабатывает отдельное событие Transfer.
        Проверяет, связаны ли адреса с нашей базой (релевантные адреса).
        Если да, отправляет событие в Kafka.
        """
        with self.app.app_context():
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
                logger.error(f"[{self.network}] Error processing log: {e}\n{traceback.format_exc()}")

    def _is_relevant_address(self, address: str) -> bool:
        """
        Проверяет, есть ли адрес в базе данных Wallet.
        Используется для фильтрации событий, чтобы обрабатывать только релевантные адреса.
        """
        return (
            self.db_session.query(Wallet)
            .filter_by(address=address.lower())
            .first()
            is not None
        )


class TronPollingListener:
    """
    Слушатель TRC20-токенов в сети Tron через HTTP polling с использованием tronpy и TronGrid API.

    Особенности:
    - Периодически опрашивает блоки Tron начиная с последнего обработанного.
    - Обрабатывает транзакции внутри блоков, фильтруя по заданному TRC20 контракту.
    - Отправляет события с релевантными адресами в Kafka.
    - Сохраняет последний обработанный блок в файл для восстановления после перезапуска.
    - Обрабатывает ошибки сети и ограничения API (403, 429) с экспоненциальным backoff.

    Атрибуты:
        STATE_FILE (str): Имя файла для хранения последнего обработанного блока.
    """

    STATE_FILE = "last_tron_block.json"

    def __init__(
        self, app: Flask, db_session: scoped_session, network: str = "trc20"
    ) -> None:
        self.network = network
        self.app = app
        self.db_session = db_session
        self.provider = HTTPProvider(api_key=os.getenv("TRONGRID_API_KEY"))
        self.client = Tron(provider=self.provider)
        self.contract_addr = os.getenv("USDT_TRC_CONTRACT_ADDR")  # Base58 адрес контракта TRC20 (например, "T...")
        self.topic = "balance_updates"

        # Kafka продюсер
        self.producer = KafkaProducer(
            bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP", "kafka:9092"),
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            retries=3,
            acks="all",
        )

        self.latest = 0  # Последний обработанный блок
        self._load_last_processed_block()

    def _load_last_processed_block(self) -> None:
        """
        Загружает последний обработанный блок из файла.
        Если файл отсутствует или повреждён, устанавливает latest в 0.
        """
        if os.path.exists(self.STATE_FILE):
            try:
                with open(self.STATE_FILE, "r") as f:
                    data = json.load(f)
                    self.latest = data.get(self.network, 0)
                logger.info(f"[{self.network}] Loaded last processed block: {self.latest}")
            except Exception as e:
                logger.error(f"[{self.network}] Failed to load last block: {e}")
                self.latest = 0
        else:
            self.latest = 0

    def _save_last_processed_block(self) -> None:
        """
        Сохраняет последний обработанный блок в файл.
        Поддерживает сохранение данных по нескольким сетям в одном JSON.
        """
        data = {}
        if os.path.exists(self.STATE_FILE):
            try:
                with open(self.STATE_FILE, "r") as f:
                    data = json.load(f)
            except Exception:
                data = {}

        data[self.network] = self.latest
        try:
            with open(self.STATE_FILE, "w") as f:
                json.dump(data, f)
            logger.info(f"[{self.network}] Saved last processed block: {self.latest}")
        except Exception as e:
            logger.error(f"[{self.network}] Failed to save last block: {e}")

    def start(self) -> None:
        """
        Запускает цикл опроса Tron блоков в отдельном демоническом потоке.
        """
        threading.Thread(target=self._poll, daemon=True).start()

    def _poll(self) -> None:
        """
        Основной цикл опроса блоков Tron.
        Обрабатывает транзакции в новых блоках, фильтрует по TRC20 контракту.
        При ошибках сети и API применяет экспоненциальный backoff.
        """
        logger.info(f"[{self.network}] Starting TRC20 polling loop...")
        backoff = 1

        # Если последний обработанный блок неизвестен, берем текущий блок сети
        if self.latest == 0:
            try:
                self.latest = self.client.get_latest_block_number()
            except Exception as e:
                logger.error(f"[{self.network}] Error getting latest block number on start: {e}")
                self.latest = 0

        while True:
            try:
                current = self.client.get_latest_block_number()
                if current > self.latest:
                    # Обрабатываем все новые блоки по одному
                    for block_num in range(self.latest + 1, current + 1):
                        block = self.client.get_block(block_num)
                        if not block:
                            logger.warning(f"[{self.network}] Empty block data for block {block_num}")
                            continue

                        for tx in block.get("transactions", []):
                            retry_attempts = 0
                            while retry_attempts < 5:
                                try:
                                    tx_info = self.client.get_transaction(tx["txID"])
                                    break
                                except TransactionNotFound:
                                    logger.warning(f"[{self.network}] Transaction not found: {tx['txID']}")
                                    break
                                except HTTPError as http_err:
                                    status = http_err.response.status_code
                                    if status == 429:
                                        logger.warning(f"[{self.network}] Rate limit hit (429), sleeping 120s")
                                        time.sleep(120)
                                    elif status == 403:
                                        logger.error(f"[{self.network}] Forbidden (403) — check API key or permissions")
                                        time.sleep(60)
                                    else:
                                        logger.error(f"[{self.network}] HTTP error {status}: {http_err}")
                                        time.sleep(10)
                                    retry_attempts += 1
                                except (
                                    ConnectionError,
                                    RemoteDisconnected,
                                    requests.exceptions.ChunkedEncodingError,
                                ) as conn_err:
                                    logger.warning(f"[{self.network}] Connection error: {conn_err}, retrying in {backoff}s")
                                    time.sleep(backoff)
                                    backoff = min(backoff * 2, 60)
                                    retry_attempts += 1
                                except Exception as e:
                                    logger.error(f"[{self.network}] Unexpected error: {e}")
                                    time.sleep(10)
                                    retry_attempts += 1
                            else:
                                logger.error(f"[{self.network}] Failed to get transaction {tx['txID']} after retries")
                                continue

                            raw_data = tx_info.get("raw_data", {})
                            contracts = raw_data.get("contract", [])
                            if not contracts:
                                continue

                            contract_info = contracts[0]
                            parameter = contract_info.get("parameter", {}).get("value", {})
                            contract_addr_raw = parameter.get("contract_address")
                            if not contract_addr_raw:
                                continue

                            try:
                                decoded_addr = normalize_tron_address(contract_addr_raw)
                            except ValueError as e:
                                logger.warning(f"[{self.network}] Invalid contract_address '{contract_addr_raw}': {e}")
                                continue

                            if decoded_addr != self.contract_addr:
                                # Не наш контракт — пропускаем
                                continue

                            owner_hex = parameter.get("owner_address")
                            to_hex = parameter.get("to_address")

                            try:
                                from_addr = to_base58check_address(owner_hex) if owner_hex else None
                                to_addr = to_base58check_address(to_hex) if to_hex else None
                            except Exception as e:
                                logger.warning(f"[{self.network}] Failed to decode owner/to addresses: {e}")
                                continue

                            value = parameter.get("amount", 0)

                            with self.app.app_context():
                                if (from_addr and self._is_relevant_address(from_addr)) or (to_addr and self._is_relevant_address(to_addr)):
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

                            time.sleep(0.2)  # Небольшая задержка между транзакциями

                        time.sleep(0.5)  # Задержка между блоками

                        self.latest = block_num
                        self._save_last_processed_block()

                    backoff = 1  # Сброс backoff после успешной обработки

                else:
                    logger.debug(f"[{self.network}] No new blocks. Latest: {self.latest}, Current: {current}")

                time.sleep(30)  # Интервал между опросами

            except HTTPError as http_err:
                status = http_err.response.status_code
                logger.error(f"[{self.network}] HTTP error {status}: {http_err}")
                if status == 429:
                    logger.warning(f"[{self.network}] Rate limited, sleeping 120s")
                    time.sleep(120)
                elif status == 403:
                    logger.error(f"[{self.network}] Forbidden access, check API key")
                    time.sleep(60)
                else:
                    time.sleep(10)

            except (
                ConnectionError,
                RemoteDisconnected,
                requests.exceptions.ChunkedEncodingError,
            ) as conn_err:
                logger.warning(f"[{self.network}] Connection error in main loop: {conn_err}, sleeping 10s")
                time.sleep(10)

            except Exception as e:
                logger.error(f"[{self.network}] TRC polling error: {e}\n{traceback.format_exc()}")
                time.sleep(10)

    def _is_relevant_address(self, address: str) -> bool:
        """
        Проверяет, есть ли адрес в базе данных Wallet.
        Используется для фильтрации событий, чтобы обрабатывать только релевантные адреса.
        """
        return (
            self.db_session.query(Wallet)
            .filter_by(address=address.lower())
            .first()
            is not None
        )


def start_websocket_listeners(app: Flask, db_session: scoped_session) -> None:
    """
    Запускает слушателей для разных сетей (ERC20, BEP20, TRC20) в отдельных потоках.

    Получает URL нод из переменных окружения, создает экземпляры слушателей и запускает их.

    Args:
        app (Flask): Flask приложение.
        db_session (scoped_session): Сессия базы данных.
    """
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
            app=app,
        )

        bep_listener = BlockchainListener(
            network="bep20",
            ws_urls=bep_nodes,
            contract_addr=os.getenv("USDT_BEP_CONTRACT_ADDR"),
            db_session=db_session,
            app=app,
        )

        trc_listener = TronPollingListener(db_session=db_session, app=app)

        erc_listener.start()
        bep_listener.start()
        trc_listener.start()

    threading.Thread(target=run, daemon=True).start()
    logger.info("Started all blockchain listeners (ERC, BEP, TRC)")