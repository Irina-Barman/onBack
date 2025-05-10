from ..extensions import db


class NetworkGas(db.Model):
    """
    Расценки комиссии сети (в USDT).
    Хранится одна строка на сеть – удобно править из админ-панели.
    """

    __tablename__ = "network_gas"

    network = db.Column(db.String(8), primary_key=True)  # 'bep','erc','trc'
    gas_usdt = db.Column(db.Numeric(18, 2), nullable=False)
