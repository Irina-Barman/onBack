from flask_restx import Namespace


# Кастомные исключения
class RegistrationError(Exception):
    def __init__(self, message: str) -> None:
        self.message: str = message


class EmailConfirmationError(Exception):
    def __init__(self, message: str) -> None:
        self.message: str = message


class PasswordResetError(Exception):
    def __init__(self, message: str) -> None:
        self.message: str = message


def register_error_handlers(api_namespace: Namespace) -> None:
    """
    Регистрирует обработчики пользовательских исключений в заданном
    пространстве имён API.

    Добавляет обработчики ошибок для следующих исключений:
    - RegistrationError
    - EmailConfirmationError
    - PasswordResetError

    Return: JSON-ответ с сообщением об ошибке и HTTP статусом 400.

    :param api_namespace: Пространство имён Flask-RESTx, в котором
    регистрируются обработчики.
    :return: None
    """

    @api_namespace.errorhandler(RegistrationError)
    def handle_registration_error(
        error: RegistrationError,
    ) -> tuple[dict, int]:
        return {"error": "ValueError", "message": error.message}, 400

    @api_namespace.errorhandler(EmailConfirmationError)
    def handle_email_confirmation_error(
        error: EmailConfirmationError,
    ) -> tuple[dict, int]:
        return {"error": "ValueError", "message": error.message}, 400

    @api_namespace.errorhandler(PasswordResetError)
    def handle_password_reset_error(
        error: PasswordResetError,
    ) -> tuple[dict, int]:
        return {"error": "ValueError", "message": error.message}, 400

    @api_namespace.errorhandler(ValueError)
    def handle_value_error(error: ValueError) -> tuple[dict, int]:
        return {"error": "ValueError", "message": str(error)}, 400
