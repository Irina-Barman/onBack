"""
Модуль email_service.py

Содержит класс EmailService для отправки email с повторными попытками (retry)
и логированием результатов в базу данных через SQLAlchemy.

Функциональность:
- Отправка email с использованием шаблонов и экспоненциальным бэкоффом при ошибках.
- Запись в лог базы данных информации о каждой попытке отправки.
- Высокоуровневая функция, объединяющая отправку и логирование с обработкой исключений.

Используемые компоненты:
- SQLAlchemy Session для взаимодействия с базой.
- Модель EmailLog для хранения логов отправки.
- Внешняя функция send_email_by_template для отправки email по шаблону.
- Стандартный логгер для записи событий и ошибок.

"""

import logging
import time
from datetime import datetime
from typing import Dict, Optional

from models import EmailLog
from sqlalchemy.orm import Session

from onfine.utils.mailer import send_email_by_template

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


class EmailService:
    """
    Сервис для отправки email с retry и логированием результатов в базу данных.

    Атрибуты:
        db_session (Session): SQLAlchemy сессия для работы с базой данных.

    Методы:
        send_email_with_retry(to, template_type, context) -> dict:
            Отправляет письмо с повторными попытками при ошибках.
            Возвращает словарь с результатом отправки.
        log_email(to, context, success, error_message=None):
            Записывает результат отправки письма в таблицу EmailLog.
        send_and_log(to, template_type, context):
            Высокоуровневая функция: отправляет письмо с retry и логирует результат.
    """

    def __init__(self, db_session: Session):
        """
        Инициализирует EmailService с сессией базы данных.

        Args:
            db_session (Session): активная сессия SQLAlchemy.
        """
        self.db_session = db_session

    def send_email_with_retry(
        self, to: str, template_type: str, context: dict
    ) -> Dict[str, Optional[str]]:
        """
        Отправляет email с использованием шаблона с повторными попытками при ошибках.

        Реализован экспоненциальный бэкофф (2^attempt секунд) между попытками.
        Максимальное количество попыток определяется константой MAX_RETRIES.

        Args:
            to (str): адрес получателя email.
            template_type (str): идентификатор шаблона письма.
            context (dict): словарь с параметрами для шаблона письма.

        Returns:
            dict: результат отправки с ключами:
                - "status": "success" или "error"
                - "error_message": описание ошибки при неудаче или None
        """
        attempt = 0
        while attempt < MAX_RETRIES:
            try:
                send_email_by_template(to, template_type, context)
                return {"status": "success", "error_message": None}
            except Exception as e:
                wait_time = 2**attempt
                logger.error(
                    f"Ошибка отправки письма (attempt {attempt + 1}/{MAX_RETRIES}) "
                    f"для {to}: {e}. Ретрай через {wait_time} сек."
                )
                time.sleep(wait_time)
                attempt += 1

        return {
            "status": "error",
            "error_message": f"Failed to send email after {MAX_RETRIES} retries",
        }

    def log_email(
        self,
        to: str,
        context: dict,
        success: bool,
        error_message: Optional[str] = None,
    ) -> None:
        """
        Записывает результат попытки отправки письма в таблицу EmailLog.

        Args:
            to (str): адрес получателя email.
            context (dict): словарь с данными письма, из которого берутся user_uid и subject.
            success (bool): флаг успешной отправки.
            error_message (Optional[str]): сообщение об ошибке, если отправка не удалась.
        """
        email_log = EmailLog(
            user_uid=context.get("user_uid"),
            email_to=to,
            subject=context.get("subject", ""),
            body="",  # При необходимости можно добавить тело письма
            sent_at=datetime.utcnow(),
            success=success,
            error_message=error_message,
        )
        self.db_session.add(email_log)
        self.db_session.commit()

    def send_and_log(self, to: str, template_type: str, context: dict) -> None:
        """
        Высокоуровневая функция: отправляет письмо с retry и логирует результат.

        Выполняет:
            - вызов send_email_with_retry для отправки письма,
            - логирование результата в базу данных через log_email,
            - логирование событий и ошибок в стандартный логгер.

        Args:
            to (str): адрес получателя email.
            template_type (str): идентификатор шаблона письма.
            context (dict): словарь с параметрами для шаблона письма.

        Исключения:
            Обрабатывает исключения при логировании, чтобы не прервать выполнение.
        """
        result = self.send_email_with_retry(to, template_type, context)
        success = result.get("status") == "success"
        error_message = result.get("error_message") if not success else None

        try:
            self.log_email(to, context, success, error_message)
            if success:
                logger.info(
                    f"Письмо успешно отправлено и сохранено в лог для {to}"
                )
            else:
                logger.error(f"Письмо не отправлено для {to}: {error_message}")
        except Exception as e:
            logger.error(f"Ошибка логирования письма для {to}: {e}")
