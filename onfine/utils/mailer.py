"""
Модуль email_sender — генерация email-сообщений из шаблонов и публикация их в Kafka.

Функционал:
- Загружает HTML-шаблоны писем из директории с шаблонами (email_templates).
- Генерирует HTML по заданному типу шаблона и контексту.
- Публикует сформированное письмо в Kafka-топик для последующей обработки и отправки.
- Логирует содержание письма (вместо реальной отправки).
- Обрабатывает ошибки при работе с шаблонами и Kafka.

Переменные окружения (с значениями по умолчанию):
- KAFKA_BOOTSTRAP: адрес Kafka bootstrap-сервера (default: "localhost:9092")
- KAFKA_TOPIC: имя Kafka-топика для публикации сообщений (default: "mailer_emails")

Зависимости:
- jinja2 — для шаблонизации email-сообщений
- kafka-python — для публикации сообщений в Kafka
- logging — для логирования событий и ошибок
- pathlib, os — для работы с путями и переменными окружения
"""

import json
import logging
import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from kafka import KafkaProducer

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = BASE_DIR / "email_templates"

env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "kafka:9092")
KAFKA_TOPIC = os.getenv("MAILER_TOPIC", "mailer_emails")

try:
    producer = KafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )
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
    """
    Формирует письмо по шаблону, публикует его в Kafka и логирует.

    Args:
        to (str): Email получателя.
        template_type (str): Имя шаблона письма.
        context (dict): Контекст для шаблона, может содержать ключ 'subject' с темой письма.

    Логика:
    - Генерирует HTML с помощью generate_html.
    - Формирует сообщение с полями: to, subject, html, template, context.
    - Отправляет сообщение в Kafka-топик.
    - Логирует письмо через send_email.
    - При ошибках логирует исключения.

    Используется для интеграции с системой отправки писем через Kafka.
    """
    subject = context.get("subject", "Ваше письмо")
    html = generate_html(template_type, context)

    # Публикуем сообщение в Kafka
    if producer:
        try:
            msg = {
                "to": to,
                "subject": subject,
                "html": html,
                "template": template_type,
                "context": context,
            }
            producer.send(KAFKA_TOPIC, msg)
            producer.flush()
            logger.info(
                f"Email message published to Kafka topic '{KAFKA_TOPIC}'"
            )
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения в Kafka: {e}")

    # Логируем письмо
    send_email(to, subject, html)
