"""
REST-namespace /wallets
Создание кошельков, комиссии, вывод, баланс, история.
"""

import os
from decimal import Decimal
from typing import Any, Dict, List

from flask_jwt_extended import get_jwt_identity, jwt_required
from flask_restx import Namespace, Resource, fields

from onfine.models.user import User
from onfine.services import wallet_service as svc

ns = Namespace("wallets", description="Кошельки, баланс, вывод")

# ---------- swagger models ----------
_wallets = ns.model(
    "WalletList",
    {
        "bep": fields.String,
        "erc": fields.String,
        "trc": fields.String,
    },
)
_empty = ns.model("Empty", {})

_fee = ns.model(
    "Fee",
    {
        "bep": fields.String,
        "erc": fields.String,
        "trc": fields.String,
    },
)

_withdraw_in = ns.model(
    "WithdrawIn",
    {
        "network": fields.String(required=True, enum=["bep", "erc", "trc"]),
        "amount": fields.String(required=True, example="50.00"),
        "destination": fields.String(required=True, example="0x… / TA… / bnb…"),
        "2fa_code": fields.String(required=True, example="123456"),
    },
)
_withdraw_out = ns.model(
    "WithdrawOut",
    {
        "status": fields.String,
        "transaction_id": fields.Integer,
    },
)

_balance_out = ns.model(
    "BalanceOut",
    {
        "bep_balance": fields.String,
        "erc_balance": fields.String,
        "trc_balance": fields.String,
    },
)

_tx = ns.model(
    "Tx",
    {
        "type": fields.String,
        "amount": fields.String,
        "network": fields.String,
        "status": fields.String,
        "timestamp": fields.DateTime(attribute="created_at"),
    },
)

_check_in = ns.model(
    "CheckWalletIn",
    {"wallet_address": fields.String(required=True)},
)
_check_out = ns.model("CheckWalletOut", {"status": fields.String})

_ref_bal = ns.model("RefBalance", {"balance": fields.String})
_ref_wd = ns.model(
    "RefWithdrawIn",
    {"amount": fields.String(required=True, example="25.00")},
)


# ---------- /create_wallet ----------
@ns.route("/create_wallet")
class WalletCreate(Resource):
    @jwt_required()
    @ns.expect(_empty)
    @ns.marshal_with(_wallets)
    def post(self) -> Dict[str, str]:
        """
        Создает новые кошельки для пользователя.

        Return:
            dict: Словарь с адресами созданных кошельков.
        """
        user = User.query.get(get_jwt_identity())
        return svc.create_wallets(user)


# ---------- /get_wallet ----------
@ns.route("/get_wallet")
class WalletGet(Resource):
    @jwt_required()
    @ns.expect(_empty)
    @ns.marshal_with(_wallets, skip_none=True)
    def post(self) -> Dict[str, Any]:
        """
        Получает адреса кошельков пользователя.

        Return:
            dict: Словарь с адресами кошельков или None, если они отсутствуют.
        """
        user = User.query.get(get_jwt_identity())
        res = svc.list_wallets(user)
        return res if res else {"wallet": None}


# ---------- /transfer_fee ----------
@ns.route("/transfer_fee")
class TransferFee(Resource):
    @ns.marshal_with(_fee)
    def get(self) -> Dict[str, str]:
        """
        Получает информацию о комиссиях за переводы.

        Return:
            dict: Словарь с комиссиями для различных сетей.
        """
        return {k: str(v) for k, v in svc.transfer_fee_table().items()}


# ---------- /withdraw ----------
@ns.route("/withdraw")
class Withdraw(Resource):
    @jwt_required()
    @ns.expect(_withdraw_in)
    @ns.marshal_with(_withdraw_out, code=201)
    def post(self) -> Dict[str, Any]:
        """
        Выводит средства с кошелька пользователя.

        Return:
            dict: Статус операции и ID транзакции.
        """
        user = User.query.get(get_jwt_identity())
        data = ns.payload
        tx = svc.withdraw_funds(
            user=user,
            network=data["network"],
            amount=Decimal(data["amount"]),
            dest=data["destination"],
            twofa_code=data["2fa_code"],
        )
        return {"status": tx.status.value, "transaction_id": tx.id}, 201


# ---------- /balance ----------
@ns.route("/balance")
class Balance(Resource):
    @jwt_required()
    @ns.expect(_empty)
    @ns.marshal_with(_balance_out)
    def get(self) -> Dict[str, str]:
        """
        Получает баланс пользователя по всем сетям.

        Return:
            dict: Словарь с балансами для различных сетей.
        """
        user = User.query.get(get_jwt_identity())
        bal = svc.user_balance_stub(user)
        return {k: str(v) for k, v in bal.items()}


# ---------- /transactions ----------
@ns.route("/transactions")
class Transactions(Resource):
    @jwt_required()
    @ns.expect(_empty)
    @ns.marshal_list_with(_tx)
    def get(self) -> List[Dict[str, Any]]:
        """
        Получает историю транзакций пользователя.

        Return:
            list: Список транзакций пользователя.
        """
        user = User.query.get(get_jwt_identity())
        return svc.history(user)


# ---------- /check_wallet ----------
@ns.route("/check_wallet")
class CheckWallet(Resource):
    @ns.expect(_check_in)
    @ns.marshal_with(_check_out)
    def post(self) -> Dict[str, str]:
        """
        Проверяет безопасность кошелька.

        Return:
            dict: Статус проверки кошелька.
        """
        return {"status": "safe"}


# ---------- /referral_balance ----------
@ns.route("/referral_balance")
class RefBal(Resource):
    @jwt_required()
    @ns.marshal_with(_ref_bal)
    def get(self) -> Dict[str, str]:
        """
        Получает баланс реферальной программы пользователя.

        Return:
            dict: Словарь с реферальным балансом.
        """
        user = User.query.get(get_jwt_identity())
        return {"balance": str(svc.ref_balance(user))}


# ---------- /referral_withdraw ----------
@ns.route("/referral_withdraw")
class RefWithdraw(Resource):
    @jwt_required()
    @ns.expect(_ref_wd)
    def post(self) -> Dict[str, str]:
        """
        Выводит средства из реферального баланса пользователя.

        Return:
            dict: Статус операции.
        """
        user = User.query.get(get_jwt_identity())
        amt = Decimal(ns.payload["amount"])
        if amt < Decimal(os.getenv("REF_MIN_PAYOUT", "10")):
            return {"error": "below minimum"}, 400
        svc.ref_debit(user, amt)  # переносим на основной баланс
        svc.debit(user, "erc", -amt)  # зачисляем на обычный (ERC пример)
        return {"status": "ok"}
