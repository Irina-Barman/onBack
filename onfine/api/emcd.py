import os
from functools import wraps
from typing import Any, Callable, Dict

from flask import abort, request
from flask_restx import Namespace, Resource, fields

from onfine.services.emcd_service import (
    DataService,
)

OUR_API_KEY = os.getenv("OUR_API_KEY")  # общий ключ для X-API-KEY
# базовый токен для доступа к сервису (раньше EMCD_API_KEY)
BASE_API_TOKEN = os.getenv("BASE_API_TOKEN")


def require_api_key(func: Callable[..., Any]):
    @wraps(func)
    def wrapper(*args, **kwargs) -> Any:
        key = request.headers.get("X-API-KEY")
        if not key or key != OUR_API_KEY:
            abort(401, "Unauthorized: invalid or missing API key")
        return func(*args, **kwargs)
    return wrapper


ns = Namespace("emcd", description="API для получения информации")

coin_info = ns.model(
    "CoinInfo",
    {
        "address": fields.String(required=True, example="1TqVjEy5nA7tXEDCx4fHgxccxnoYj5RAtt"),
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
        "username": fields.String(required=True, example="user"),
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
        "user": fields.String(required=True, example="user"),
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

income_entry = ns.model(
    "IncomeEntry",
    {
        "code": fields.Integer(required=True, example=1),
        "timestamp": fields.Integer(required=True, example=1569456000),
        "gmt_time": fields.String(required=True, example="26-09-2019 00:00:00"),
        "income": fields.Float(required=True, example=0.00830608),
        "type": fields.String(required=True, example="mining"),
        "total_hashrate": fields.Integer(required=True, example=390089214794186),
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
        "gmt_time": fields.String(required=True, example="25-09-2019 05:30:01"),
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


@ns.route("/info")
class Info(Resource):
    @require_api_key
    @ns.marshal_with(account_info)
    def get(self) -> Dict[str, Any]:
        """Получает информацию об аккаунте.

        Query params:
            access_token (str, optional): Токен доступа к аккаунту. Если не передан, используется базовый токен.

        Returns:
            dict: Информация об аккаунте.

        Пример запроса с базовым токеном:
        curl -X GET "http://127.0.0.1:5500/api/emcd/info" \
            -H "X-API-KEY: <your_api_key>" \
            -H "Accept: application/json"

        Пример запроса с пользовательским токеном:
        curl -X GET "http://127.0.0.1:5500/api/emcd/info?access_token=<user_token>" \
            -H "X-API-KEY: <your_api_key>" \
            -H "Accept: application/json"
        """
        access_token = request.args.get('access_token') or BASE_API_TOKEN
        svc = DataService(access_token)
        return svc.get_account_info()


@ns.route("/workers/<string:coin>")
class Workers(Resource):
    @require_api_key
    @ns.marshal_with(workers_info)
    def get(self, coin: str) -> Dict[str, Any]:
        """Получает информацию о работниках для указанной криптовалюты.

        Query params:
            access_token (str, optional): Токен доступа к аккаунту. Если не передан, используется базовый токен.

        Args:
            coin (str): Идентификатор криптовалюты.

        Returns:
            dict: Информация о работниках.

        Пример запроса с базовым токеном:
        curl -X GET "http://127.0.0.1:5500/api/emcd/workers/<coin>" \
            -H "X-API-KEY: <your_api_key>" \
            -H "Accept: application/json"

        Пример запроса с пользовательским токеном:
        curl -X GET "http://127.0.0.1:5500/api/emcd/workers/<coin>?access_token=<user_token>" \
            -H "X-API-KEY: <your_api_key>" \
            -H "Accept: application/json"
        """
        access_token = request.args.get('access_token') or BASE_API_TOKEN
        svc = DataService(access_token)
        return svc.get_workers(coin)


@ns.route("/income/<string:coin>")
class Income(Resource):
    @require_api_key
    @ns.marshal_with(income_info)
    def get(self, coin: str) -> Dict[str, Any]:
        """Получает информацию о доходах для указанной криптовалюты.

        Query params:
            access_token (str, optional): Токен доступа к аккаунту. Если не передан, используется базовый токен.

        Args:
            coin (str): Идентификатор криптовалюты.

        Returns:
            dict: Информация о доходах.

        Пример запроса с базовым токеном:
        curl -X GET "http://127.0.0.1:5500/api/emcd/income/<coin>" \
            -H "X-API-KEY: <your_api_key>" \
            -H "Accept: application/json"

        Пример запроса с пользовательским токеном:
        curl -X GET "http://127.0.0.1:5500/api/emcd/income/<coin>?access_token=<user_token>" \
            -H "X-API-KEY: <your_api_key>" \
            -H "Accept: application/json"
        """
        access_token = request.args.get('access_token') or BASE_API_TOKEN
        svc = DataService(access_token)
        return svc.get_income(coin)


@ns.route("/payouts/<string:coin>")
class Payouts(Resource):
    @require_api_key
    @ns.marshal_with(payouts_info)
    def get(self, coin: str) -> Dict[str, Any]:
        """Получает информацию о выплатах для указанной криптовалюты.

        Query params:
            access_token (str, optional): Токен доступа к аккаунту. Если не передан, используется базовый токен.

        Args:
            coin (str): Идентификатор криптовалюты.

        Returns:
            dict: Информация о выплатах.

        Пример запроса с базовым токеном:
        curl -X GET "http://127.0.0.1:5500/api/emcd/payouts/<coin>" \
            -H "X-API-KEY: <your_api_key>" \
            -H "Accept: application/json"

        Пример запроса с пользовательским токеном:
        curl -X GET "http://127.0.0.1:5500/api/emcd/payouts/<coin>?access_token=<user_token>" \
            -H "X-API-KEY: <your_api_key>" \
            -H "Accept: application/json"
        """
        access_token = request.args.get('access_token') or BASE_API_TOKEN
        svc = DataService(access_token)
        return svc.get_payouts(coin)
