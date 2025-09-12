import os
from functools import wraps
from typing import Any, Callable, Dict

from flask import abort, request
from flask_restx import Namespace, Resource, fields

from onfine.services.emcd_service import EMCDService

# Новые переменные окружения для разделения уровней безопасности
# Новый ключ для нашего API (проверка X-API-KEY)
OUR_API_KEY = os.getenv("OUR_API_KEY")
EMCD_API_KEY = os.getenv("EMCD_API_KEY")  # Базовый токен EMCD (по умолчанию)
# Обработка ALLOWED_EMCD_TOKENS: убираем пустые значения и добавляем базовый токен, если он не пустой и не в списке
ALLOWED_EMCD_TOKENS = [token.strip() for token in os.getenv(
    "ALLOWED_EMCD_TOKENS", "").split(",") if token.strip()]
if EMCD_API_KEY and EMCD_API_KEY not in ALLOWED_EMCD_TOKENS:
    ALLOWED_EMCD_TOKENS.append(EMCD_API_KEY)
# Мастер-код для полного доступа (слово или фраза)
MASTER_CODE = os.getenv("MASTER_CODE")


def require_api_key(func: Callable[..., Any]):
    @wraps(func)
    def wrapper(*args, **kwargs) -> Any:
        key = request.headers.get("X-API-KEY")
        if not key or key != OUR_API_KEY:
            abort(401, "Unauthorized: invalid or missing API key")
        return func(*args, **kwargs)

    return wrapper

# Функция для проверки мастер-кода


def is_master_code_provided() -> bool:
    code = request.args.get('master_code')
    return code and code == MASTER_CODE

# Функция для проверки EMCD-токена (только если мастер-код НЕ предоставлен)


def is_valid_emcd_token(token: str) -> bool:
    if not token:
        return False
    return token in ALLOWED_EMCD_TOKENS


ns = Namespace("emcd", description="Информация из EMCD API")

# Удаляем глобальный svc = EMCDService() — теперь создаём локально в каждом endpoint с нужным токеном

# 1) Swagger-модель одного coin_info
coin_info = ns.model(
    "CoinInfo",
    {
        "address": fields.String(
            required=True,
            example="1TqVjEy5nA7tXEDCx4fHgxccxnoYj5RAtt",
        ),
        "coin_id": fields.String(required=True, example="btc"),
        "balance": fields.Float(required=True, example=0.01103015),
        "total_paid": fields.Float(required=True, example=0.85367081),
        "total_reward": fields.Float(required=True, example=303.07695983),
        "min_payout": fields.Float(required=True, example=0.01),
    },
)

account_info = ns.model(
    "AccountInfo",
    {
        "username": fields.String(required=True, example="emcduser"),
        "coins": fields.Raw(
            required=True,
            description="Словарь coin_id → CoinInfo",
            example={
                "btc": {
                    "address": "1TqVjEy5nA7tXEDCx4fHgxccxnoYj5RAtt",
                    "coin_id": "btc",
                    "balance": 0.01103015,
                    "total_paid": 0.85367081,
                    "total_reward": 303.07695983,
                    "min_payout": 0.01,
                },
            },
        ),
    },
)

# 2) Модели для воркеров
total_count = ns.model(
    "TotalCount",
    {
        "all": fields.Integer(required=True, example=3),
        "active": fields.Integer(required=True, example=3),
        "inactive": fields.Integer(required=True, example=0),
        "dead_count": fields.Integer(required=True, example=0),
    },
)
total_hashrate = ns.model(
    "TotalHashrate",
    {
        "hashrate": fields.Integer(required=True, example=295548725546189),
        "hashrate1h": fields.Integer(required=True, example=301647350041587),
        "hashrate24h": fields.Integer(required=True, example=302284252332638),
    },
)
worker_detail = ns.model(
    "WorkerDetail",
    {
        "active": fields.Integer(required=True, example=1),
        "hashrate": fields.Integer(required=True, example=270215977642230),
        "hashrate1h": fields.Integer(required=True, example=275219977228197),
        "hashrate24h": fields.Integer(required=True, example=274618910871679),
        "lastbeat": fields.Integer(required=True, example=1723465200),
        "new_status": fields.String(required=True, example="active"),
        "reject": fields.Float(required=True, example=0.0337),
        "user": fields.String(required=True, example="emcduser"),
        "worker": fields.String(required=True, example="worker20"),
    },
)
workers_info = ns.model(
    "WorkersInfo",
    {
        "total_count": fields.Nested(total_count, required=True),
        "total_hashrate": fields.Nested(total_hashrate, required=True),
        "details": fields.List(fields.Nested(worker_detail), required=True),
    },
)

# 3) Модели для доходов и выплат
income_entry = ns.model(
    "IncomeEntry",
    {
        "code": fields.Integer(required=True, example=1),
        "timestamp": fields.Integer(required=True, example=1569456000),
        "gmt_time": fields.String(
            required=True,
            example="26-09-2019 00:00:00",
        ),
        "income": fields.Float(required=True, example=0.00830608),
        "type": fields.String(required=True, example="mining"),
        "total_hashrate": fields.Integer(
            required=True,
            example=390089214794186,
        ),
    },
)
income_info = ns.model(
    "IncomeInfo",
    {
        "income": fields.List(fields.Nested(income_entry), required=True),
    },
)

payout_entry = ns.model(
    "PayoutEntry",
    {
        "timestamp": fields.Integer(required=True, example=1569389401),
        "gmt_time": fields.String(
            required=True,
            example="25-09-2019 05:30:01",
        ),
        "amount": fields.Float(required=True, example=0.0166448),
        "txid": fields.String(required=True, example="13849427081db061..."),
    },
)
payouts_info = ns.model(
    "PayoutsInfo",
    {
        "payouts": fields.List(fields.Nested(payout_entry), required=True),
    },
)


# Endpoints
@ns.route("/info")
class Info(Resource):
    @require_api_key
    @ns.marshal_with(account_info)
    def get(self) -> Dict[str, Any]:
        """Получает информацию об аккаунте.

        Returns:
            dict: Информация об аккаунте пользователя.

        Example request:
        curl -X GET "http://127.0.0.1:5500/api/emcd/info?emcd_token=<optional_emcd_token>&master_code=<optional_master_code>" \
            -H "X-API-KEY: <your_our_api_key_from_env>" \
            -H "Accept: application/json"

        """
        # Получение EMCD-токена (опциональный параметр emcd_token в query)
        emcd_token = request.args.get('emcd_token') or EMCD_API_KEY

        # Проверка мастер-кода: если он правильный, пропускаем проверку токена
        if not is_master_code_provided():
            if not is_valid_emcd_token(emcd_token):
                abort(403, "Invalid or unauthorized EMCD token")

        # Создание сервиса с выбранным токеном
        svc = EMCDService(emcd_token)
        return svc.get_account_info()


@ns.route("/workers/<string:coin>")
class Workers(Resource):
    @require_api_key
    @ns.marshal_with(workers_info)
    def get(self, coin: str) -> Dict[str, Any]:
        """Получает информацию о работниках для указанной крипты.

        Args:
            coin (str): Идентификатор крипты.

        Returns:
            dict: Информация о работниках для указанной крипты.

        Example request:
        curl -X GET "http://127.0.0.1:5500/api/emcd/workers/<coin>?emcd_token=<optional_emcd_token>&master_code=<optional_master_code>" \
            -H "X-API-KEY: <your_our_api_key_from_env>" \
            -H "Accept: application/json"

        Замените <coin> на идентификатор крипты (например, "btc").
        """
        # Получение EMCD-токена (опциональный параметр emcd_token в query)
        emcd_token = request.args.get('emcd_token') or EMCD_API_KEY

        # Проверка мастер-кода: если он правильный, пропускаем проверку токена
        if not is_master_code_provided():
            if not is_valid_emcd_token(emcd_token):
                abort(403, "Invalid or unauthorized EMCD token")

        # Создание сервиса с выбранным токеном
        svc = EMCDService(emcd_token)
        return svc.get_workers(coin)


@ns.route("/income/<string:coin>")
class Income(Resource):
    @require_api_key
    @ns.marshal_with(income_info)
    def get(self, coin: str) -> Dict[str, Any]:
        """Получает информацию о доходах для указанной крипты.

        Args:
            coin (str): Идентификатор крипты.

        Returns:
            dict: Информация о доходах для указанной крипты.

        Example request:
        curl -X GET "http://127.0.0.1:5500/api/emcd/income/<coin>?emcd_token=<optional_emcd_token>&master_code=<optional_master_code>" \
            -H "X-API-KEY: <your_our_api_key_from_env>" \
            -H "Accept: application/json"

        Замените <coin> на идентификатор крипты (например, "btc").
        """
        # Получение EMCD-токена (опциональный параметр emcd_token в query)
        emcd_token = request.args.get('emcd_token') or EMCD_API_KEY

        # Проверка мастер-кода: если он правильный, пропускаем проверку токена
        if not is_master_code_provided():
            if not is_valid_emcd_token(emcd_token):
                abort(403, "Invalid or unauthorized EMCD token")

        # Создание сервиса с выбранным токеном
        svc = EMCDService(emcd_token)
        return svc.get_income(coin)


@ns.route("/payouts/<string:coin>")
class Payouts(Resource):
    @require_api_key
    @ns.marshal_with(payouts_info)
    def get(self, coin: str) -> Dict[str, Any]:
        """Получает информацию о выплатах для указанной крипты.

        Args:
            coin (str): Идентификатор крипты.

        Returns:
            dict: Информация о выплатах для указанной крипты.

        Example request:
        curl -X GET "http://127.0.0.1:5500/api/emcd/payouts/<coin>?emcd_token=<optional_emcd_token>&master_code=<optional_master_code>" \
            -H "X-API-KEY: <your_our_api_key_from_env>" \
            -H "Accept: application/json"

        Замените <coin> на идентификатор крипты (например, "btc").
        """
        # Получение EMCD-токена (опциональный параметр emcd_token в query)
        emcd_token = request.args.get('emcd_token') or EMCD_API_KEY

        # Проверка мастер-кода: если он правильный, пропускаем проверку токена
        if not is_master_code_provided():
            if not is_valid_emcd_token(emcd_token):
                abort(403, "Invalid or unauthorized EMCD token")

        # Создание сервиса с выбранным токеном
        svc = EMCDService(emcd_token)
        return svc.get_payouts(coin)
