"""
Воркёр подтверждения газа и завершения gasless-покупки.

Алгоритм (EVM: ERC20/BEP20):
 1) Ждём receipt по platform_tx_hash (топап).
 2) (Опционально) проверяем баланс нативки пользователя — информативно.
 3) USDT-транзакция уже опубликована на шаге create_purchase_gasless -> ждём её майнинг.
 4) Обновляем Purchase: step -> completed, status -> completed.

Алгоритм (TRON):
 1) Ждём receipt топапа (TRX).
 2) Отправляем USDT transfer от имени пользователя через provider.transfer(user_pk,...).
 3) Ждём подтверждение.
 4) Обновляем Purchase -> completed.

Идемпотентность:
- если шаг уже финальный — выходим. Повторно доставленные сообщения безопасны.

ENV:
- KAFKA_BOOTSTRAP       (например, "kafka:9092")
- GAS_CONFIRM_TOPIC     (по умолчанию "gas_confirm_request")
- KAFKA_GAS_GROUP_ID    (по умолчанию "gas-confirm-workers")

Зависимости:
- kafka-python
- web3, tronpy
"""

import logging
import os
import time
from datetime import datetime
from decimal import Decimal
from typing import Optional

from kafka import KafkaConsumer
from services.locks import extend_wallet_lock, release_wallet_lock
from web3.exceptions import TransactionNotFound

from onfine.blockchain.providers import ProviderManager
from onfine.extensions import db
from onfine.models.platform_gas_expense import GasExpenseStatus, PlatformGasExpense
from onfine.models.purchase import Purchase, PurchaseStatus, PurchaseStep
from onfine.models.wallet import Wallet

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

KAFKA_BOOTSTRAP: str = os.getenv("KAFKA_BOOTSTRAP", "kafka:9092")
KAFKA_TOPIC_IN: str = os.getenv("GAS_CONFIRM_TOPIC", "gas_confirm_request")
KAFKA_GROUP_ID: str = os.getenv("KAFKA_GAS_GROUP_ID", "gas-confirm-workers")


def _net_upper(network: str) -> str:
    return (network or "").upper()


class GasConfirmWorker:
    """
    Консюмер-воркёр: подтверждает топап газа и завершает покупку.
    """

    # тайминги/пределы ожидания
    GAS_RECEIPT_TIMEOUT_SEC = 300  # до 5 мин на подтверждение топапа
    USER_TX_TIMEOUT_SEC = 600  # до 10 мин на подтверждение USDT-транзакции
    POLL_INTERVAL_SEC = 5

    def __init__(self) -> None:
        self.consumer = self._create_consumer(KAFKA_GROUP_ID, KAFKA_TOPIC_IN)
        self._running = True

    @staticmethod
    def _create_consumer(group_id: str, topic: str) -> KafkaConsumer:
        """
        Создаёт KafkaConsumer (kafka-python) и подписывает на один топик.
        Возвращает готовый consumer (manual commit).
        """
        consumer = KafkaConsumer(
            topic,
            bootstrap_servers=KAFKA_BOOTSTRAP,
            group_id=group_id,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            value_deserializer=lambda m: __import__("json").loads(m.decode("utf-8")),
            consumer_timeout_ms=10000,
        )
        return consumer

    # ---------------- utils: ожидание receipt ----------------

    @classmethod
    def _wait_evm_receipt(cls, w3, tx_hash: str, timeout_sec: int, on_tick=None) -> bool:  # noqa: ANN001, ANN001
        start = time.time()
        tick = 0
        while time.time() - start < timeout_sec:
            try:
                r = w3.eth.get_transaction_receipt(tx_hash)
                if r is not None:
                    status = getattr(r, "status", None)
                    if status == 1:
                        return True
                    if status == 0:
                        return False
            except TransactionNotFound:
                pass
            except Exception as e:
                logger.debug("evm receipt waiting error: %s", e)

            tick += 1
            if on_tick and tick % 6 == 0:  # раз в ~30 сек (6 * POLL_INTERVAL_SEC(=5))
                try:
                    on_tick()
                except Exception as _e:
                    logger.debug("on_tick error: %s", _e)

            time.sleep(cls.POLL_INTERVAL_SEC)
        return False

    @classmethod
    def _wait_tron_confirm(cls, tron_client, txid: str, timeout_sec: int, on_tick: bool = None) -> bool:  # noqa: ANN001
        start = time.time()
        tick = 0
        while time.time() - start < timeout_sec:
            try:
                info = tron_client.get_transaction_info(txid)
                if info and (info.get("blockNumber") or info.get("receipt")):
                    return True
            except Exception as e:
                logger.debug("tron receipt waiting error: %s", e)

            tick += 1
            if on_tick and tick % 6 == 0:  # раз в ~30 сек
                try:
                    on_tick()
                except Exception as _e:
                    logger.debug("on_tick error: %s", _e)

            time.sleep(cls.POLL_INTERVAL_SEC)
        return False

    # ---------------- основной обработчик ----------------

    def _handle_payload(self, payload: dict) -> None:  # noqa: PLR0911
        """
        Обрабатывает одно сообщение {purchase_id, network, platform_tx_hash?}.
        """
        p_id = int(payload["purchase_id"])
        net_raw = payload.get("network")
        net = _net_upper(net_raw)

        purchase: Optional[Purchase] = Purchase.query.get(p_id)
        if not purchase:
            logger.warning("Purchase %s not found", p_id)
            return

        if purchase.step in (PurchaseStep.completed, PurchaseStep.failed):
            logger.info("Purchase %s already finished (step=%s), skip", p_id, purchase.step)
            return

        exp: Optional[PlatformGasExpense] = None
        if getattr(purchase, "gas_topup_expense_id", None):
            exp = PlatformGasExpense.query.get(purchase.gas_topup_expense_id)
        if not exp or not exp.platform_tx_hash:
            logger.warning("No gas expense or platform tx for purchase %s", p_id)
            return

        provider = ProviderManager.get(net, contract_addr=purchase.usdt_token_contract)

        # --- 1) подтверждаем топап газа ---
        logger.info("[CONFIRM] waiting gas topup receipt p=%s net=%s tx=%s", p_id, net, exp.platform_tx_hash)
        if net in ("ERC20", "BEP20"):
            gas_ok = self._wait_evm_receipt(
                provider.w3,
                exp.platform_tx_hash,
                self.GAS_RECEIPT_TIMEOUT_SEC,
                on_tick=lambda: self._try_refresh_lock(purchase, 900),
            )
        else:
            gas_ok = self._wait_tron_confirm(
                provider.client,
                exp.platform_tx_hash,
                self.GAS_RECEIPT_TIMEOUT_SEC,
                on_tick=lambda: self._try_refresh_lock(purchase, 600),
            )

        if not gas_ok:
            logger.error("Gas topup not confirmed in time; purchase=%s", p_id)
            return  # оставим воркер/поллер перезапросить позже

        exp.status = GasExpenseStatus.confirmed
        exp.confirmed_at = datetime.utcnow()  # noqa: DTZ003
        db.session.commit()

        # --- 2) EVM: ждём уже опубликованный USDT-тx; TRON: публикуем сейчас ---
        wallet: Optional[Wallet] = Wallet.query.get(purchase.wallet_id)
        if not wallet:
            logger.error("Wallet %s for purchase %s not found", purchase.wallet_id, p_id)
            return

        if net in ("ERC20", "BEP20"):
            # На этапе create_purchase_gasless мы уже публиковали пользовательский raw_tx,
            # его хэш должен лежать в purchase.user_tx_hash.
            if not purchase.user_tx_hash:
                logger.error("Missing user_tx_hash on EVM purchase %s", p_id)
                return

            logger.info("[CONFIRM] waiting user USDT tx p=%s tx=%s", p_id, purchase.user_tx_hash)
            ok = self._wait_evm_receipt(
                provider.w3,
                purchase.user_tx_hash,
                self.USER_TX_TIMEOUT_SEC,
                on_tick=lambda: self._try_refresh_lock(purchase, 900),
            )
            if not ok:
                logger.error("USDT tx not confirmed in time; p=%s tx=%s", p_id, purchase.user_tx_hash)
                return

            purchase.step = PurchaseStep.completed
            purchase.status = PurchaseStatus.completed
            purchase.confirmed_at = datetime.utcnow()  # noqa: DTZ003
            db.session.commit()
            self._try_release_lock(purchase)
            logger.info("[PURCHASE COMPLETED] p=%s net=%s tx=%s", p_id, net, purchase.user_tx_hash)
            return

        # ---- TRON ----
        # Здесь мы отправляем сам USDT transfer от имени пользователя (после подтверждённого топапа)
        user_pk = Wallet.decrypt_pk(wallet.pk_enc)
        try:
            txid = provider.transfer(user_pk, purchase.platform_address, Decimal(purchase.amount_usdt))
            logger.info("[TRON USDT SENT] p=%s tx=%s", p_id, txid)
        except Exception as e:
            logger.error("TRON transfer error p=%s: %s", p_id, e)
            return

        ok = self._wait_tron_confirm(
            provider.client,
            txid,
            self.USER_TX_TIMEOUT_SEC,
            on_tick=lambda: self._try_refresh_lock(purchase, 600),
        )
        if not ok:
            logger.error("TRON USDT tx not confirmed in time p=%s tx=%s", p_id, txid)
            return

        purchase.user_tx_hash = txid
        purchase.step = PurchaseStep.completed
        purchase.status = PurchaseStatus.completed
        purchase.confirmed_at = datetime.utcnow()  # noqa: DTZ003
        db.session.commit()
        self._try_release_lock(purchase)
        logger.info("[PURCHASE COMPLETED] p=%s net=%s tx=%s", p_id, net, txid)

    @classmethod
    def _try_refresh_lock(purchase: Purchase, extend_sec: int = 900) -> None:
        """
        Пытается продлить TTL долгого лока, если он привязан к покупке.
        Не бросает исключения — только логирует.
        """
        lock_id = getattr(purchase, "wallet_lock_id", None)
        lock_token = getattr(purchase, "wallet_lock_token", None)
        if not lock_id or not lock_token:
            logger.debug("No wallet lock bound to purchase %s; skip refresh", purchase.id)
            return
        try:
            extend_wallet_lock(lock_id, lock_token, extend_sec)
            db.session.commit()
            logger.debug("Lock refreshed for purchase %s (+%ss)", purchase.id, extend_sec)
        except Exception as e:
            logger.warning("Failed to refresh lock for purchase %s: %s", purchase.id, e)

    @classmethod
    def _try_release_lock(purchase: Purchase) -> None:
        """
        Пытается снять долгий лок, если он привязан к покупке.
        Не бросает исключения — только логирует.
        """
        lock_id = getattr(purchase, "wallet_lock_id", None)
        lock_token = getattr(purchase, "wallet_lock_token", None)
        if not lock_id or not lock_token:
            return
        try:
            release_wallet_lock(lock_id, lock_token, comment=f"purchase {purchase.id} finished")
            db.session.commit()
            logger.info("Lock released for purchase %s", purchase.id)
        except Exception as e:
            logger.error("Failed to release lock for purchase %s: %s", purchase.id, e)

    # ---------------- цикл консюмера ----------------

    def run(self) -> None:  # noqa: D102
        logger.info("GasConfirmWorker started; topic=%s", KAFKA_TOPIC_IN)
        try:
            for msg in self.consumer:
                try:
                    payload = msg.value  # уже dict, см. value_deserializer
                    self._handle_payload(payload)
                    self.consumer.commit()
                except Exception as e:
                    logger.exception("Failed to handle message: %s", e)
                    # не коммитим — сообщение переедет в ретрай
        finally:
            try:
                self.consumer.close()
            except Exception:
                pass


if __name__ == "__main__":
    GasConfirmWorker().run()
