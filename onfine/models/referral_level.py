from ..extensions import db


class ReferralLevel(db.Model):
    __tablename__ = "referral_levels"

    program_type = db.Column(db.Integer, primary_key=True)
    level        = db.Column(db.Integer, primary_key=True)
    percent      = db.Column(db.Numeric(5, 2), nullable=False)
    active       = db.Column(db.Boolean, default=True)
