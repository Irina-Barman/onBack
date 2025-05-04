from datetime import datetime
from flask import request
from flask_restx import Namespace, Resource, fields
from flask_jwt_extended import jwt_required, get_jwt_identity

from onfine.services.auth_service import AuthService
from onfine.models.user import User

auth_ns = Namespace("auth", description="Регистрация • логин • восстановление пароля")

# ----------- Swagger-модели ----------
err_model = auth_ns.model("Error",   {"error": fields.String})

register_in = auth_ns.model("RegisterIn", {
    "email":       fields.String(required=True, example="user@example.com"),
    "password":    fields.String(required=True, example="secret"),
    "nickname":    fields.String(required=True, example="nick"),
    "partner_uid": fields.String(required=False, example="111e2222-…"),
})
register_out = auth_ns.model("RegisterOut", {
    "message": fields.String,
    "user_id": fields.Integer,
})

confirm_in = auth_ns.model("ConfirmEmailIn", {"token": fields.String(required=True)})
login_in   = auth_ns.model("LoginIn", {"email":  fields.String, "password": fields.String})
login_out  = auth_ns.model("LoginOut", {
    "accessToken":      fields.String,
    "tokenType":        fields.String,
    "expireTimestamp":  fields.Integer,
})
forgot_in  = auth_ns.model("ForgotIn", {"email": fields.String})
reset_in   = auth_ns.model("ResetIn", {
    "token":       fields.String,
    "newPassword": fields.String,
})
msg_out    = auth_ns.model("Message", {"message": fields.String})
user_out   = auth_ns.model("UserOut", {
    "email":            fields.String,
    "nickname":         fields.String,
    "isEmailConfirmed": fields.Boolean,
    "user_uid":         fields.String,
})

# ----------- /register ----------
@auth_ns.route("/register")
class Register(Resource):
    @auth_ns.expect(register_in)
    @auth_ns.marshal_with(register_out, code=200)
    @auth_ns.response(400, "Validation error", err_model)
    def post(self):
        data = request.json or {}
        partner_uid = data.get("partner_uid") or request.args.get("partner_uid")
        try:
            user = AuthService.register_user(
                email=data["email"],
                password=data["password"],
                partner_uid=partner_uid
            )
            return {
                "message": "Registration successful. Please confirm your e-mail.",
                "user_id": user.id,
            }, 200
        except ValueError as e:
            return {"error": str(e)}, 400

# ----------- /confirm-email ----------
@auth_ns.route("/confirm-email")
class ConfirmEmail(Resource):
    @auth_ns.expect(confirm_in)
    @auth_ns.marshal_with(msg_out)
    @auth_ns.response(400, "Bad token", err_model)
    def post(self):
        data = request.json
        try:
            AuthService.confirm_email(data["token"])
            return {"message": "Email confirmed."}
        except ValueError as e:
            return {"error": str(e)}, 400

# ----------- /login ----------
@auth_ns.route("/login")
class Login(Resource):
    @auth_ns.expect(login_in)
    @auth_ns.marshal_with(login_out)
    @auth_ns.response(400, "Invalid creds / email not confirmed", err_model)
    def post(self):
        data = request.json
        try:
            return AuthService.login_user(data["email"], data["password"])
        except ValueError as e:
            return {"error": str(e)}, 400

# ----------- /forgot-password ----------
@auth_ns.route("/forgot-password")
class ForgotPassword(Resource):
    @auth_ns.expect(forgot_in)
    @auth_ns.marshal_with(msg_out)
    @auth_ns.response(400, "Email not found", err_model)
    def post(self):
        data = request.json
        try:
            AuthService.forgot_password(data["email"])
            return {"message": "Reset e-mail sent."}
        except ValueError as e:
            return {"error": str(e)}, 400

# ----------- /reset-password ----------
@auth_ns.route("/reset-password")
class ResetPassword(Resource):
    @auth_ns.expect(reset_in)
    @auth_ns.marshal_with(msg_out)
    @auth_ns.response(400, "Bad token", err_model)
    def post(self):
        data = request.json
        try:
            return AuthService.reset_password(data["token"], data["newPassword"])
        except ValueError as e:
            return {"error": str(e)}, 400

# ----------- /logout ----------
@auth_ns.route("/logout")
class Logout(Resource):
    @auth_ns.marshal_with(msg_out)
    def post(self):
        if not request.headers.get("Authorization"):
            return {"error": "Token is missing."}, 400
        return {"message": "Successfully logged out."}

# ----------- /user ----------
@auth_ns.route("/user")
class UserMe(Resource):
    @jwt_required()
    @auth_ns.marshal_with(user_out)
    def get(self):
        user = User.query.get(get_jwt_identity())
        return {
            "email":            user.email,
            "nickname":         user.nickname,
            "isEmailConfirmed": user.email_confirmed,
            "user_uid":         user.uid,
        }
