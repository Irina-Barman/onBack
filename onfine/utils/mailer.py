import logging
import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

# Настройка логирования с уровнем INFO
logging.basicConfig(level=logging.INFO)
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
    Генерирует HTML содержимое письма на основе шаблона и переданного контекста.

    :param template_type: Имя шаблона без расширения (например, "welcome_email")
    :param context: Словарь с данными для подстановки в шаблон
    :return: Сгенерированный HTML-код письма
    :raises: Исключение при ошибках загрузки или рендеринга шаблона
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
    Отправляет email с помощью SendGrid.

    Если переменная окружения SENDGRID_API_KEY не задана,
    письмо логируется в консоль (удобно для локальной разработки).

    :param to: Email адрес получателя
    :param subject: Тема письма
    :param body: HTML-содержимое письма
    :raises: Исключение при ошибках отправки через SendGrid
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

    В контексте можно передать ключ 'subject' для темы письма,
    если его нет — тема будет по умолчанию "Ваше письмо".

    :param to: Email адрес получателя
    :param template_type: Имя шаблона (без расширения .html)
    :param context: Словарь с данными для шаблона, может содержать ключ 'subject'
    """
    subject = context.get("subject", "Ваше письмо")
    html = generate_html(template_type, context)
    send_email(to, subject, html)
