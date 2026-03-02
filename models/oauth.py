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
    scope = db.Column(db.String(255), nullable=False, default="openid profile email")
    is_confidential = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now(), nullable=False)

    def redirect_uri_list(self) -> list[str]:
        return [uri.strip() for uri in (self.redirect_uris or "").splitlines() if uri.strip()]


class OAuthAuthorizationCode(db.Model):
    __tablename__ = "oauth_authorization_code"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(255), unique=True, nullable=False, index=True)
    client_id = db.Column(db.String(120), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    redirect_uri = db.Column(db.String(512), nullable=False)
    scope = db.Column(db.String(255), nullable=False, default="openid")
    nonce = db.Column(db.String(255), nullable=True)
    state = db.Column(db.String(255), nullable=True)
    code_challenge = db.Column(db.String(255), nullable=False)
    code_challenge_method = db.Column(db.String(10), nullable=False, default="S256")
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    used_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now(), nullable=False)

    @classmethod
    def new_expiration(cls):
        return utcnow() + timedelta(minutes=10)


class OAuthToken(db.Model):
    __tablename__ = "oauth_token"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.String(120), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    access_token = db.Column(db.String(255), unique=True, nullable=False, index=True)
    refresh_token = db.Column(db.String(255), unique=True, nullable=True, index=True)
    token_type = db.Column(db.String(40), nullable=False, default="Bearer")
    scope = db.Column(db.String(255), nullable=False, default="")
    id_token = db.Column(db.Text, nullable=True)
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now(), nullable=False)

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and self.expires_at > utcnow()
