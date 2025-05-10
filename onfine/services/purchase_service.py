import logging
from typing import Optional

from onfine.database import db
from onfine.models.package import Package
from onfine.models.purchase import Purchase


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
