import logging
import os
from datetime import datetime
from decimal import Decimal
from typing import Optional

from onfine.blockchain.providers import ProviderManager
from onfine.extensions import db
from onfine.models.package import Package
from onfine.models.platform_gas_expense import GasExpenseStatus, PlatformGasExpense
from onfine.models.purchase import Purchase, PurchaseStatus, PurchaseStep
from onfine.models.wallet import Wallet
from onfine.services.locks import WalletLockedError, WalletLockPurpose, lock_wallet

from ..utils import kafka_producer

USDT_CONTRACTS = {
    "ERC20": os.getenv("USDT_ERC_CONTRACT_ADDR"),
    "BEP20": os.getenv("USDT_BEP_CONTRACT_ADDR"),
    "TRC20": os.getenv("USDT_TRC_CONTRACT_ADDR"),
}
PLATFORM_RECIPIENTS = {  # адреса платформы, куда летит USDT
    "ERC20": os.getenv("PLATFORM_USDT_ERC_ADDRESS"),
    "BEP20": os.getenv("PLATFORM_USDT_BEP_ADDRESS"),
    "TRC20": os.getenv("PLATFORM_USDT_TRC_ADDRESS"),
}


class PurchaseService:
    @staticmethod
    def create_purchase(
        user_id: int,
        item_id: int,
        payment_wallet: Optional[str] = None,  # noqa: ARG004
    ) -> Purchase:
        """Создание записи о покупке.

        :param user_id: ID пользователя, совершающего покупку.
        :param item_id: ID пакета, который покупается.
        :param payment_wallet: (необязательный) Кошелек для оплаты.
        :return: Объект Purchase, представляющий созданную покупку.
        :raises ValueError: Если пакет не найден.
        :raises Exception: Если произошла ошибка при создании покупки.
        """
        try:
            package = Package.query.get(item_id)
            if not package:
                logging.error(
                    f"Package with ID {item_id} not found for user {user_id}.",
                )
                raise ValueError("Package not found")

            # Создаем покупку
            purchase = Purchase(
                user_id=user_id,
                item_id=item_id,
                summ=package.price,
                gas=6.0,  # Заглушка для комиссии сети
            )

            db.session.add(purchase)
            db.session.commit()

            logging.info(
                f"Purchase created for user {user_id}, package {item_id}.",
            )
            return purchase
        except ValueError as ve:
            logging.error(f"ValueError: {str(ve)}")
            raise
        except Exception as e:
            logging.error(
                f"Error creating purchase for user {user_id}: {str(e)}",
            )
            db.session.rollback()  # Откат транзакции в случае ошибки
            raise Exception("Error creating purchase")

    @staticmethod
    def create_purchase_gasless(user, package, network: str) -> Purchase:  # noqa: ANN001, D102
        net = network.upper()
        if net not in USDT_CONTRACTS:
            raise ValueError("Unsupported network")

        wallet: Wallet | None = next((w for w in user.wallets if w.network.upper() == net), None)
        if not wallet:
            raise ValueError("Wallet not found for this network")

        amount_usdt = Decimal(package.price_usdt)
        token_addr = USDT_CONTRACTS[net]
        platform_addr = PLATFORM_RECIPIENTS[net]

        provider = ProviderManager.get(net, contract_addr=token_addr)

        # короткий лок: получить nonce, собрать и подписать tx, запомнить и сразу отправить в мемпул
        try:
            with lock_wallet(
                wallet.id,
                WalletLockPurpose.purchase,
                ttl_seconds=90,
                comment=f"purchase init {package.id}",
            ):
                # pending nonce (в т.ч. учёт ещё не замайненных)
                if net in ("ERC20", "BEP20"):
                    nonce = provider.w3.eth.get_transaction_count(wallet.address, "pending")
                    unsigned = provider.build_user_token_transfer(wallet.address, platform_addr, amount_usdt, nonce)
                    user_pk = Wallet.decrypt_pk(wallet.pk_enc)
                    raw_tx, tx_hash = provider.sign_user_tx(unsigned, user_pk)
                    # публикуем прямо сейчас — он повиснет pending до прихода газа
                    provider.publish_raw_tx(raw_tx)
                    est_native = provider.estimate_native_for_tx(unsigned)
                else:
                    # TRON: строим и сразу шлём после топапа; raw можно не хранить
                    unsigned = provider.build_user_token_transfer(
                        wallet.address,
                        platform_addr,
                        amount_usdt,
                        reserved_nonce=None,
                    )
                    user_pk = Wallet.decrypt_pk(wallet.pk_enc)
                    signed_raw, tx_hash = provider.sign_user_tx(unsigned, user_pk)
                    # Для TRON publish после топапа; estimate берём из fee_limit
                    est_native = provider.estimate_native_for_tx(unsigned)

                # создаём запись Purchase
                p = Purchase(
                    user_id=user.id,
                    package_id=package.id,
                    amount_usdt=amount_usdt,
                    gas_usdt=Decimal("0"),
                    network=network,
                    status=PurchaseStatus.pending,
                    step=PurchaseStep.gas_enqueued,
                    wallet_id=wallet.id,
                    reserved_nonce=(nonce if net in ("ERC20", "BEP20") else None),
                    user_raw_tx=(raw_tx if net in ("ERC20", "BEP20") else signed_raw),
                    user_tx_hash=tx_hash,
                    platform_address=platform_addr,
                    usdt_token_contract=token_addr,
                    created_at=datetime.utcnow(),  # noqa: DTZ003
                )
                db.session.add(p)
                db.session.flush()

                # учитываем плановый расход газа
                exp = PlatformGasExpense(
                    user_id=user.id,
                    wallet_id=wallet.id,
                    network=network,
                    amount_native=est_native * Decimal("1.10"),  # +10% буфер
                    amount_usdt_est=Decimal("0"),
                    status=GasExpenseStatus.enqueued,
                )
                db.session.add(exp)
                db.session.flush()

                p.gas_topup_expense_id = exp.id
                db.session.commit()

        except WalletLockedError:
            raise ValueError("Wallet is busy, try again in a minute")

        try:
            kafka_producer.send(
                topic="gas_topup_request",
                message_id=str(p.id),
                data={
                    "purchase_id": p.id,
                    "network": network,
                    "wallet_address": wallet.address,
                    "amount_native": str(exp.amount_native),
                },
            )
            logging.info(f"Отправлено событие Kafka для покупки {p.id}")
        except Exception as e:
            logging.error(f"Ошибка при отправке события Kafka для покупки {p.id}: {e}")
            raise  # Можно выбросить исключение, чтобы обработать его на уровне API
        return p
