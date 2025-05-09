import os
from datetime import datetime

from cryptography.fernet import Fernet

from ..extensions import db

# --------------------------------------------------------- ключ шифрования
# • хранится в .env  (FERNET_KEY=<base64-строка длиной 44>)
# • если переменной нет, генерируем — НО выводим в лог, чтобы владелец
#   сохранил ключ; иначе при перезапуске расшифровать будет нельзя.
_key_b64 = os.getenv("FERNET_KEY")
if not _key_b64:
    _key_b64 = Fernet.generate_key().decode()
    print(
        f"[WARN] FERNET_KEY not set; generated temporary key:\n{_key_b64}\n"
        "Add it to your .env to persist encrypted private keys!",
    )

FERNET = Fernet(_key_b64.encode())


# --------------------------------------------------------- модель Wallet
class Wallet(db.Model):
    __tablename__ = "wallets"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=False)
    network = db.Column(db.String(8), nullable=False)  # bep | erc | trc
    address = db.Column(db.String(128), nullable=False, unique=True)
    pk_enc = db.Column(db.LargeBinary, nullable=False)  # зашифрованный privkey
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint("user_id", "network", name="uq_user_network"),)

    # helpers ----------------------------------------------------
    @staticmethod
    def encrypt_pk(pk: str) -> bytes:
        return FERNET.encrypt(pk.encode())

    @staticmethod
    def decrypt_pk(pk_enc: bytes) -> str:
        return FERNET.decrypt(pk_enc).decode()
