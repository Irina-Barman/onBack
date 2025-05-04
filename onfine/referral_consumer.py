import json, os, time
from decimal import Decimal

from kafka import KafkaConsumer
from onfine.app_factory import create_app
from onfine.extensions import db
from onfine.models import User, Transaction, ReferralLevel
from onfine.models.transactions import TxType, TxStatus
from onfine.models.ledger_entry import LedgerEntry, LedgerType
from onfine.services import wallet_service as wsvc

consumer = KafkaConsumer(
        "purchase.completed",
        bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP", "kafka:9092"),
        group_id="ref_consumer",
        auto_offset_reset="earliest",
        enable_auto_commit=True,                   # пусть коммитит сам
        value_deserializer=lambda v: json.loads(v.decode())
)

def _percent(ptype: int, lvl: int) -> Decimal:
    row = ReferralLevel.query.filter_by(
            program_type=ptype, level=lvl, active=True).first()
    return Decimal(row.percent) / 100 if row else Decimal(0)

app = create_app()
with app.app_context():
    for msg in consumer:                          # бесконечный итератор
        d       = msg.value                       # уже dict
        amount  = Decimal(d["amount"])
        ptype   = int(d.get("program_type", 1))
        net     = d["network"]
        u       = User.query.get(d["user_id"])

        lvl = 1
        while u and u.partner_uid:
            parent = User.query.filter_by(uid=u.partner_uid).first()
            if not parent:
                break

            percent = _percent(ptype, lvl)
            if percent > 0:
                reward = (amount * percent).quantize(Decimal("0.01"))

                tx = Transaction(
                    user_id=parent.id,
                    type=TxType.referral,
                    status=TxStatus.confirmed,
                    network=net,
                    amount=reward,
                )
                db.session.add(tx); db.session.flush()

                db.session.add(LedgerEntry(
                    user_id=parent.id,
                    origin_table="transactions",
                    origin_id=tx.id,
                    type=LedgerType.referral,
                    direction="in",
                    network=net,
                    amount=reward,
                ))

                wsvc.ref_credit(parent.id, reward)

            u = parent
            lvl += 1

        db.session.commit()



#docker compose exec api python -m onfine.referral_consumer #планировка на кроне
