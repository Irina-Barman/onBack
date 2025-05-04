from onfine.models.purchase import Purchase
from onfine.database import db
import logging


class PaymentService:

    @staticmethod
    def confirm_payment(purchase_id, payment_status):
        """Подтверждение оплаты"""
        try:
            # Получаем покупку по ID
            purchase = Purchase.query.get(purchase_id)
            if not purchase:
                logging.error(f"Purchase {purchase_id} not found")
                raise Exception("Purchase not found")

            # Обновляем статус покупки в зависимости от результата платежа
            if payment_status:
                purchase.status = "completed"
                logging.info(f"Purchase {purchase_id} payment confirmed successfully")
            else:
                purchase.status = "canceled"
                logging.info(f"Purchase {purchase_id} payment failed or canceled")

            db.session.commit()
            return purchase
        except Exception as e:
            logging.error(f"Error in confirm_payment: {str(e)}")
            raise Exception("Error confirming payment")
