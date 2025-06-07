from flask_restx import Namespace


# Кастомные исключения Auth
class RegistrationError(Exception):
    def __init__(self, message: str) -> None:
        self.message: str = message


class EmailConfirmationError(Exception):
    def __init__(self, message: str) -> None:
        self.message: str = message


class PasswordResetError(Exception):
    def __init__(self, message: str) -> None:
        self.message: str = message


# Wallet


class WalletCreationError(Exception):
    def __init__(self, message: str) -> None:
        self.message: str = message


class WalletRetrievalError(Exception):
    def __init__(self, message: str) -> None:
        self.message: str = message


class TransferFeeRetrievalError(Exception):
    def __init__(self, message: str) -> None:
        self.message: str = message


class WithdrawError(Exception):
    def __init__(self, message: str) -> None:
        self.message: str = message


class BalanceError(Exception):
    def __init__(self, message: str) -> None:
        self.message: str = message


class TransactionError(Exception):
    def __init__(self, message: str) -> None:
        self.message: str = message


class ReferralError(Exception):
    def __init__(self, message: str) -> None:
        self.message: str = message


# Purchase


class PackageNotFoundError(Exception):
    def __init__(self, message: str) -> None:
        self.message: str = message


class NetworkNotFoundError(Exception):
    def __init__(self, message: str) -> None:
        self.message: str = message


class InsufficientBalanceError(Exception):
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
    - WalletCreationError
    - WalletRetrievalError

    Return: JSON-ответ с сообщением об ошибке и HTTP статусом 400.

    :param api_namespace: Пространство имён Flask-RESTx, в котором
    регистрируются обработчики.
    :return: None
    """

    # общий
    @api_namespace.errorhandler(ValueError)
    def handle_value_error(error: ValueError) -> tuple[dict, int]:
        return {"error": "400 Bad Request", "message": str(error)}, 400

    # Auth
    @api_namespace.errorhandler(RegistrationError)
    def handle_registration_error(
        error: RegistrationError,
    ) -> tuple[dict, int]:
        return {"error": "400 Bad Request", "message": error.message}, 400

    @api_namespace.errorhandler(EmailConfirmationError)
    def handle_email_confirmation_error(
        error: EmailConfirmationError,
    ) -> tuple[dict, int]:
        return {"error": "400 Bad Request", "message": error.message}, 400

    @api_namespace.errorhandler(PasswordResetError)
    def handle_password_reset_error(
        error: PasswordResetError,
    ) -> tuple[dict, int]:
        return {"error": "400 Bad Request", "message": error.message}, 400

    # Wallet
    @api_namespace.errorhandler(WalletCreationError)
    def handle_wallet_creation_error(
        error: WalletCreationError,
    ) -> tuple[dict, int]:
        return {"error": "400 Bad Request", "message": error.message}, 400

    @api_namespace.errorhandler(WalletRetrievalError)
    def handle_wallet_retrieval_error(
        error: WalletRetrievalError,
    ) -> tuple[dict, int]:
        return {"error": "404 Not Found", "message": error.message}, 404

    @api_namespace.errorhandler(TransferFeeRetrievalError)
    def handle_transfer_fee_retrieval_error(
        error: TransferFeeRetrievalError,
    ) -> tuple[dict, int]:
        return {
            "error": "500 Internal Server Error",
            "message": error.message,
        }, 500

    @api_namespace.errorhandler(WithdrawError)
    def handle_withdraw_error(error: WithdrawError) -> tuple[dict, int]:
        return {"error": "400 Bad Request", "message": error.message}, 400

    @api_namespace.errorhandler(BalanceError)
    def handle_balance_error(error: BalanceError) -> tuple[dict, int]:
        return {
            "error": "500 Internal Server Error",
            "message": error.message,
        }, 500

    @api_namespace.errorhandler(TransactionError)
    def handle_transaction_error(error: TransactionError) -> tuple[dict, int]:
        return {
            "error": "500 Internal Server Error",
            "message": str(error),
        }, 500

    @api_namespace.errorhandler(ReferralError)
    def handle_referral_error(error: ReferralError) -> tuple[dict, int]:
        return {
            "error": "500 Internal Server Error",
            "message": str(error),
        }, 500

    # Purchase

    @api_namespace.errorhandler(PackageNotFoundError)
    def handle_package_not_found_error(
        error: PackageNotFoundError,
    ) -> tuple[dict, int]:
        return {"error": "404 Not Found", "message": str(error)}, 404

    @api_namespace.errorhandler(NetworkNotFoundError)
    def handle_network_not_found_error(
        error: NetworkNotFoundError,
    ) -> tuple[dict, int]:
        return {"error": "404 Not Found", "message": str(error)}, 404

    @api_namespace.errorhandler(InsufficientBalanceError)
    def handle_insufficient_balance_error(
        error: InsufficientBalanceError,
    ) -> tuple[dict, int]:
        return {"error": "400 Bad Request", "message": str(error)}, 400
