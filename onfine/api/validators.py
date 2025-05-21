import re
from typing import NoReturn

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def validate_email(email: str) -> NoReturn:
    """
    Проверяет корректность формата электронной почты.

    :param email: Строка, представляющая адрес электронной почты.
    :raises ValueError: Если формат электронной почты некорректен.
    """
    if not EMAIL_REGEX.match(email):
        raise ValueError("Invalid email format.")


def validate_password(password: str) -> NoReturn:
    """
    Проверяет корректность пароля по нескольким критериям.

    :param password: Строка, представляющая пароль.
    :raises ValueError: Если пароль не соответствует критериям:
        - Должен содержать не менее 8 символов.
        - Должен содержать хотя бы одну заглавную букву.
        - Должен содержать хотя бы одну строчную букву.
        - Должен содержать хотя бы одну цифру.
        - Должен содержать хотя бы один специальный символ.
    """
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long.")
    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must contain at least one uppercase letter.")
    if not re.search(r"[a-z]", password):
        raise ValueError("Password must contain at least one lowercase letter.")
    if not re.search(r"[0-9]", password):
        raise ValueError("Password must contain at least one digit.")
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        raise ValueError("Password must contain at least one special character.")
