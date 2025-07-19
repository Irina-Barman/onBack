"""
Модуль mailer — утилиты для генерации и отправки email с использованием шаблонов Jinja2 и SendGrid.

Функциональность:
- Загрузка HTML-шаблонов писем из папки email_templates.
- Генерация HTML на основе шаблона и контекста.
- Отправка email через SendGrid API или логирование письма при отсутствии API ключа.

Переменные окружения:
- SENDGRID_API_KEY — API ключ для SendGrid. Если не задан, письма не отправляются, а логируются.
"""

import logging
import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

logger = logging.getLogger(__name__)

# Определяем абсолютный путь к корню проекта и папке с email-шаблонами
BASE_DIR = (
    Path(__file__).resolve().parent.parent
)  # Путь к корню проекта (например, onfine/)
TEMPLATE_DIR = BASE_DIR / "email_templates"  # Папка с HTML-шаблонами писем

# Инициализация Jinja2 Environment для загрузки шаблонов из TEMPLATE_DIR
env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(
        ["html", "xml"]
    ),  # Автоэкранирование для html и xml
)


def generate_html(template_type: str, context: dict) -> str:
    """
    Генерирует HTML-содержимое email на основе шаблона и контекста.

    Args:
        template_type (str): Имя шаблона без расширения (например, "welcome_email").
        context (dict): Словарь с данными для подстановки в шаблон.

    Return:
        str: Сгенерированный HTML код письма.

    Exceptions:
        Любые ошибки загрузки или рендеринга шаблона вызывают исключение.
    """
    try:
        # Загружаем шаблон по имени
        template = env.get_template(f"{template_type}.html")
        # Рендерим шаблон с переданным контекстом
        return template.render(**context)
    except Exception as e:
        logger.error(f"Ошибка генерации шаблона '{template_type}': {e}")
        raise


def send_email(to: str, subject: str, body: str) -> None:
    """
    Отправляет email через SendGrid или логирует письмо если API ключ отсутствует.

    Args:
        to (str): Email адрес получателя.
        subject (str): Тема письма.
        body (str): HTML содержимое письма.

    Поведение:
        - Если переменная окружения SENDGRID_API_KEY не задана, письмо выводится в лог.
        - При наличии ключа отправляет письмо через SendGrid API.

    Exceptions:
        Выбрасывает исключение при ошибках отправки через SendGrid.
    """
    api_key = os.getenv("SENDGRID_API_KEY")
    if not api_key:
        # В режиме без API-ключа просто логируем письмо
        logger.warning(f"[MAIL-LOG] To: {to}  Subj: {subject}\n{body}\n")
        return

    # Создаем объект письма SendGrid
    message = Mail(
        from_email="noreply@example.com",
        to_emails=to,
        subject=subject,
        html_content=body,
    )
    try:
        sg = SendGridAPIClient(api_key)
        response = sg.send(message)
        logger.info(f"Email sent to {to} with status {response.status_code}")
    except Exception as e:
        logger.error(f"SendGrid send error: {e}")
        raise


def send_email_by_template(to: str, template_type: str, context: dict) -> None:
    """
    Генерирует HTML письмо из шаблона с контекстом и отправляет его.

    Args:
        to (str): Email адрес получателя.
        template_type (str): Имя шаблона (без расширения .html).
        context (dict): Словарь с данными для шаблона, может содержать ключ 'subject' для темы.

    Поведение:
        - Тема письма берется из context['subject'], если отсутствует — используется "Ваше письмо".
        - Генерирует HTML с помощью generate_html.
        - Отправляет письмо через send_email.
    """
    subject = context.get("subject", "Ваше письмо")
    html = generate_html(template_type, context)
    send_email(to, subject, html)
