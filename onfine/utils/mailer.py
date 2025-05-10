import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str) -> None:
    """
    Отправляет электронное письмо на указанный адрес.

    Пока просто выводим письмо в консоль для тестирования.
    Замените на Flask-Mail или любой SMTP-клиент.

    :param to: Адрес электронной почты получателя.
    :param subject: Тема письма.
    :param body: Текст письма.
    """
    logger.info(f"[MAIL] To: {to}  Subj: {subject}\n{body}\n")
