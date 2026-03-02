from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy.sql import func

from extensions import db
from time_utils import utcnow


class OAuthClient(db.Model):
    __tablename__ = "oauth_client"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.String(120), unique=True, nullable=False, index=True)
    client_secret = db.Column(db.String(255), nullable=True)
    name = db.Column(db.String(120), nullable=False)
    redirect_uris = db.Column(db.Text, nullable=False, default="")
    grant_types = db.Column(db.String(255), nullable=False, default="authorization_code")
    scopes = db.Column(db.String(255), nullable=False, default="openid profile email")
    auth_method = db.Column(db.String(80), nullable=False, default="none")
    is_confidential = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now(), nullable=False)

    @property
    def scope(self):
        return self.scopes

    def redirect_uri_list(self) -> list[str]:
        return [uri.strip() for uri in (self.redirect_uris or "").splitlines() if uri.strip()]


class OAuthAuthorizationCode(db.Model):
    __tablename__ = "oauth_authorization_code"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(255), unique=True, nullable=False, index=True)
    client_id = db.Column(db.String(120), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    redirect_uri = db.Column(db.String(512), nullable=False)
    scope = db.Column(db.String(255), nullable=False, default="openid")
    nonce = db.Column(db.String(255), nullable=True)
    state = db.Column(db.String(255), nullable=True)
    code_challenge = db.Column(db.String(255), nullable=False)
    code_challenge_method = db.Column(db.String(10), nullable=False, default="S256")
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    used_at = db.Column(db.DateTime(timezone=True), nullable=True)
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now(), nullable=False)

    @classmethod
    def new_expiration(cls):
        return utcnow() + timedelta(minutes=10)

    @property
    def is_active(self) -> bool:
        now = utcnow()
        return self.revoked_at is None and self.used_at is None and self.expires_at > now


class OAuthAccessToken(db.Model):
    __tablename__ = "oauth_access_token"

    id = db.Column(db.Integer, primary_key=True)
    jti = db.Column(db.String(64), unique=True, nullable=False, index=True, default=lambda: secrets.token_hex(16))
    client_id = db.Column(db.String(120), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    access_token = db.Column(db.String(255), unique=True, nullable=False, index=True)
    token_type = db.Column(db.String(40), nullable=False, default="Bearer")
    scope = db.Column(db.String(255), nullable=False, default="")
    id_token = db.Column(db.Text, nullable=True)
    refresh_token_id = db.Column(db.Integer, db.ForeignKey("oauth_refresh_token.id", ondelete="SET NULL"), nullable=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now(), nullable=False)

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and self.expires_at > utcnow()

    def revoke(self):
        self.revoked_at = utcnow()


class OAuthRefreshToken(db.Model):
    __tablename__ = "oauth_refresh_token"

    id = db.Column(db.Integer, primary_key=True)
    jti = db.Column(db.String(64), unique=True, nullable=False, index=True, default=lambda: secrets.token_hex(16))
    client_id = db.Column(db.String(120), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    refresh_token = db.Column(db.String(255), unique=True, nullable=False, index=True)
    scope = db.Column(db.String(255), nullable=False, default="")
    replaced_by_jti = db.Column(db.String(64), nullable=True, index=True)
    family_id = db.Column(db.String(64), nullable=False, index=True, default=lambda: secrets.token_hex(16))
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now(), nullable=False)

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and self.expires_at > utcnow()


class OAuthConsent(db.Model):
    __tablename__ = "oauth_consent"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = db.Column(db.String(120), nullable=False, index=True)
    scopes = db.Column(db.String(255), nullable=False, default="")
    granted_at = db.Column(db.DateTime(timezone=True), server_default=func.now(), nullable=False)
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)

    __table_args__ = (
        db.UniqueConstraint("user_id", "client_id", name="uq_oauth_consent_user_client"),
    )


class OAuthJwkKey(db.Model):
    __tablename__ = "oauth_jwk_key"

    id = db.Column(db.Integer, primary_key=True)
    kid = db.Column(db.String(64), nullable=False, unique=True, index=True)
    kty = db.Column(db.String(16), nullable=False, default="RSA")
    private_pem = db.Column(db.Text, nullable=False)
    public_pem = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(16), nullable=False, default="active", index=True)
    valid_from = db.Column(db.DateTime(timezone=True), nullable=False, server_default=func.now())
    valid_until = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    grace_until = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    rotated_from_kid = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now(), nullable=False)

    @classmethod
    def build_kid(cls, public_pem: bytes) -> str:
        return hashlib.sha256(public_pem).hexdigest()[:16]

    @classmethod
    def active_key(cls) -> "OAuthJwkKey | None":
        now = utcnow()
        return cls.query.filter(
            cls.status == "active",
            cls.valid_from <= now,
            db.or_(cls.valid_until.is_(None), cls.valid_until > now),
        ).order_by(cls.created_at.desc()).first()

    @classmethod
    def public_key_set(cls) -> list["OAuthJwkKey"]:
        now = utcnow()
        return cls.query.filter(
            db.or_(
                cls.status == "active",
                db.and_(cls.status == "retired", cls.grace_until.isnot(None), cls.grace_until > now),
            )
        ).order_by(cls.created_at.desc()).all()


OAuthToken = OAuthAccessToken
