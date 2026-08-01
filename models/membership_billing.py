"""Auditable billing records for veterinarian memberships."""

from extensions import db
from time_utils import utcnow


class VeterinarianMembershipSubscription(db.Model):
    __tablename__ = "veterinarian_membership_subscription"

    id = db.Column(db.Integer, primary_key=True)
    membership_id = db.Column(
        db.Integer,
        db.ForeignKey("veterinarian_membership.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider = db.Column(db.String(32), nullable=False, default="mercado_pago")
    provider_preapproval_id = db.Column(db.String(64), unique=True, nullable=True)
    external_reference = db.Column(db.String(255), unique=True, nullable=False)
    plan_code = db.Column(db.String(16), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="BRL")
    status = db.Column(db.String(32), nullable=False, default="creating", index=True)
    provider_status = db.Column(db.String(32), nullable=True)
    init_point = db.Column(db.Text, nullable=True)
    last_error = db.Column(db.String(500), nullable=True)
    authorized_at = db.Column(db.DateTime(timezone=True), nullable=True)
    superseded_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_synced_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    membership = db.relationship(
        "VeterinarianMembership",
        backref=db.backref(
            "billing_subscriptions",
            cascade="all, delete-orphan",
            lazy="dynamic",
        ),
    )


class VeterinarianMembershipCharge(db.Model):
    __tablename__ = "veterinarian_membership_charge"

    id = db.Column(db.Integer, primary_key=True)
    membership_id = db.Column(
        db.Integer,
        db.ForeignKey("veterinarian_membership.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subscription_id = db.Column(
        db.Integer,
        db.ForeignKey("veterinarian_membership_subscription.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider_payment_id = db.Column(db.String(64), unique=True, nullable=False)
    provider_invoice_id = db.Column(db.String(64), unique=True, nullable=True)
    external_reference = db.Column(db.String(255), nullable=True, index=True)
    status = db.Column(db.String(32), nullable=False, index=True)
    amount = db.Column(db.Numeric(10, 2), nullable=True)
    currency = db.Column(db.String(3), nullable=False, default="BRL")
    cycle_days = db.Column(db.Integer, nullable=False, default=30)
    provider_created_at = db.Column(db.DateTime(timezone=True), nullable=True)
    paid_at = db.Column(db.DateTime(timezone=True), nullable=True)
    access_applied_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_error = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    membership = db.relationship(
        "VeterinarianMembership",
        backref=db.backref(
            "billing_charges",
            cascade="all, delete-orphan",
            lazy="dynamic",
        ),
    )
    subscription = db.relationship(
        "VeterinarianMembershipSubscription",
        backref=db.backref("charges", lazy="dynamic"),
    )
