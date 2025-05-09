import logging

from onfine.database import db
from onfine.models.package import Package
from onfine.models.purchase import Purchase


class PurchaseService:

    @staticmethod
    def create_purchase(user_id, item_id, payment_wallet):
        """Создание записи о покупке"""
        try:
            package = Package.query.get(item_id)
            if not package:
                raise Exception("Package not found")

            # Создаем покупку
            purchase = Purchase(
                user_id=user_id,
                item_id=item_id,
                summ=package.price,
                gas=6.0,  # Заглушка для комиссии сети
            )

            db.session.add(purchase)
            db.session.commit()

            logging.info(f"Purchase created for user {user_id}, package {item_id}")
            return purchase
        except Exception as e:
            logging.error(f"Error creating purchase: {str(e)}")
            raise Exception("Error creating purchase")
