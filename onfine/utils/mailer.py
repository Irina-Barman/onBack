
import logging
import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from onfine.utils.kafka_producer import _get_producer, send

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = BASE_DIR / "email_templates"

env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "kafka:9092")
KAFKA_TOPIC = os.getenv("EMAIL_TOPIC", "email_topic")

try:
    producer = _get_producer()
except Exception as e:
    logger.error(f"Ошибка инициализации Kafka Producer: {e}")
    producer = None


def generate_html(template_type: str, context: dict) -> str:
    """
    Генерирует HTML-содержимое письма по заданному шаблону и контексту.

    Args:
        template_type (str): Имя шаблона (без расширения), например "welcome", "reset_password".
        context (dict): Словарь с данными для подстановки в шаблон.

    Returns:
        str: Сформированный HTML-код письма.

    Raises:
        jinja2.TemplateNotFound: если шаблон с указанным именем не найден.
        jinja2.TemplateError: при ошибках в шаблоне или рендеринге.
    """
    try:
        template = env.get_template(f"{template_type}.html")
        return template.render(**context)
    except Exception as e:
        logger.error(f"Ошибка генерации шаблона '{template_type}': {e}")
        raise


def send_email(to: str, subject: str, body: str) -> None:
    """
    Логирует письмо (имитация отправки email).

    Args:
        to (str): Email получателя.
        subject (str): Тема письма.
        body (str): HTML-содержимое письма.

    Используется для отладки и тестирования без реальной отправки.
    """
    logger.info(f"[MAIL-LOG] To: {to}  Subj: {subject}\n{body}\n")


def send_email_by_template(to: str, template_type: str, context: dict) -> None:
    subject = context.get("subject", "Ваше письмо")
    try:
        html = generate_html(template_type, context)
    except Exception as e:
        logger.error(
            f"Не удалось сгенерировать HTML для шаблона '{template_type}': {e}"
        )
        return

    msg = {
        "to": to,
        "subject": subject,
        "html": html,
        "template": template_type,
        "context": context,
    }

    success = send(KAFKA_TOPIC, msg, retries=3, backoff=2.0)
    if success:
        logger.info(f"Email message published to Kafka topic '{KAFKA_TOPIC}'")
    else:
        logger.error(f"Ошибка отправки сообщения в Kafka для {to}")

    # Логируем письмо (имитация отправки)
    send_email(to, subject, html)
