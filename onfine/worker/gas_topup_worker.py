"""
Воркёр "топап" — переводит нативный газ на кошелёк пользователя
с мастер-аккаунта платформы под конкретную покупку (gasless).

Алгоритм:
 1) Читает событие "gas_topup_request".
 2) Находит Purchase и связанный PlatformGasExpense.
 3) Переводит нативку (provider.send_native()) с мастер-кошелька платформы.
 4) Обновляет статусы: expense -> sent, purchase.step -> gas_sent.
 5) Публикует событие "gas_confirm_request" для воркёра подтверждения.

Идемпотентность:
 - Если расход уже sent/confirmed — отправляем "gas_topup_request" (если есть tx_hash) и выходим.

ENV:
 - KAFKA_BOOTSTRAP (напр. "kafka:9092")
 - GAS_TOPUP_TOPIC (по умолчанию "gas_topup_request")
 - KAFKA_GAS_TOPUP_GROUP_ID (по умолчанию "gas-topup-workers")
 - PLATFORM_WALLET_ERC_PK / _BEP_PK / _TRC_PK — приватные ключи мастер-аккаунтов.
"""

import logging
import os
import signal
from decimal import Decimal
from typing import Optional

from kafka import KafkaConsumer

from onfine.blockchain.providers import ProviderManager
from onfine.extensions import db
from onfine.models.platform_gas_expense import GasExpenseStatus, PlatformGasExpense
from onfine.models.purchase import Purchase, PurchaseStep
from onfine.utils import kafka_producer as kfk_produce

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

KAFKA_BOOTSTRAP: str = os.getenv("KAFKA_BOOTSTRAP", "kafka:9092")
KAFKA_TOPIC_IN: str = os.getenv("GAS_TOPUP_TOPIC", "gas_topup_request")
KAFKA_GROUP_ID: str = os.getenv("KAFKA_GAS_TOPUP_GROUP_ID", "gas-topup-workers")

PLATFORM_PKS = {
    "ERC20": os.getenv("PLATFORM_WALLET_ERC_PK"),
    "BEP20": os.getenv("PLATFORM_WALLET_BEP_PK"),
    "TRC20": os.getenv("PLATFORM_WALLET_TRC_PK"),
}


def _net_upper(network: str) -> str:
    return (network or "").upper()


class GasTopupWorker:
    """
    Консюмер воркера по топапу газа (kafka-python).
    """

    def __init__(self) -> None:
        self.consumer = self._create_consumer(KAFKA_GROUP_ID, KAFKA_TOPIC_IN)
        self._running = True
        signal.signal(signal.SIGTERM, self._stop)
        signal.signal(signal.SIGINT, self._stop)

    @staticmethod
    def _create_consumer(group_id: str, topic: str) -> KafkaConsumer:
        """
        Создаёт и возвращает KafkaConsumer с JSON-десериализацией.
        """
        import json

        consumer = KafkaConsumer(
            topic,
            bootstrap_servers=KAFKA_BOOTSTRAP,
            group_id=group_id,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            consumer_timeout_ms=10000,
        )
        return consumer

    def _stop(self, *_):  # noqa: ANN202
        self._running = False

    # --------------- основной цикл ---------------

    def run(self) -> None:  # noqa: D102
        logger.info("GasTopupWorker started; topic=%s bootstrap=%s", KAFKA_TOPIC_IN, KAFKA_BOOTSTRAP)
        try:
            for msg in self.consumer:
                if not self._running:
                    break
                try:
                    payload = msg.value  # уже dict благодаря value_deserializer
                    self._handle(payload)
                    self.consumer.commit()  # manual commit после успешной обработки
                except Exception as e:
                    logger.exception("Failed to handle message: %s", e)
                    # оффсет не коммитим — сообщение уйдёт в ретрай
        finally:
            try:
                self.consumer.close()
            except Exception:
                pass
            logger.info("GasTopupWorker stopped")

    # --------------- обработка события ---------------

    def _handle(self, payload: dict) -> None:
        """
        Обрабатывает одно событие топапа.

        Ожидаемый payload:
        {
          "purchase_id": int,
          "network": "ERC20" | "BEP20" | "TRC20",
          "wallet_address": "0x.. / T..",
          "amount_native": "0.00123"   # строка либо число
        }
        """
        p_id = int(payload["purchase_id"])
        network = _net_upper(payload.get("network"))
        wallet_address = payload.get("wallet_address")
        amount_native = Decimal(str(payload.get("amount_native")))

        # валидация env ключа для сети
        platform_pk = PLATFORM_PKS.get(network)
        if not platform_pk:
            raise RuntimeError(f"Missing PLATFORM_WALLET_{network}_PK env")

        # достаём покупку и связанный расход
        purchase: Optional[Purchase] = Purchase.query.get(p_id)
        if not purchase:
            logger.warning("Purchase %s not found", p_id)
            return

        expense: Optional[PlatformGasExpense] = None
        if getattr(purchase, "gas_topup_expense_id", None):
            expense = PlatformGasExpense.query.get(purchase.gas_topup_expense_id)
        if not expense:
            logger.warning("PlatformGasExpense not found for purchase %s", p_id)
            return

        # идемпотентность: уже отправлен/подтверждён?
        if expense.status in (GasExpenseStatus.sent, GasExpenseStatus.confirmed):
            logger.info("Expense already %s for purchase %s; skip send", expense.status, p_id)
            # но на всякий случай прогоняем confirm-воркер (если есть tx_hash)
            if expense.platform_tx_hash:
                self._emit_confirm(p_id, network, expense.platform_tx_hash)
            return

        # провайдер сети
        provider = ProviderManager.get(network, contract_addr=purchase.usdt_token_contract)

        # отправляем нативный газ на адрес пользователя
        tx_hash = provider.send_native(platform_pk, wallet_address, amount_native)
        logger.info("[GAS TOPUP] net=%s to=%s amount=%s tx=%s", network, wallet_address, amount_native, tx_hash)

        # обновляем статусы
        expense.status = GasExpenseStatus.sent
        expense.platform_tx_hash = tx_hash
        purchase.step = PurchaseStep.gas_sent
        db.session.commit()

        # публикуем событие подтверждения (пусть отдельный воркер ждёт receipt)
        self._emit_confirm(p_id, network, tx_hash)

    # --------------- вспомогательное ---------------

    @staticmethod
    def _emit_confirm(purchase_id: int, network: str, platform_tx_hash: str) -> None:
        """
        Публикует событие для воркера подтверждения газа/покупки.
        """
        kfk_produce.send(
            topic="gas_confirm_request",
            message_id=str(purchase_id),
            data={
                "purchase_id": purchase_id,
                "network": network,
                "platform_tx_hash": platform_tx_hash,
            },
        )


if __name__ == "__main__":
    GasTopupWorker().run()
