"""Personal home reminder preferences using the existing notification ledger."""
import hashlib
import json
from flask import current_app
from itsdangerous import URLSafeSerializer
from extensions import db
from models import Notification

KIND = 'home_alert_dismissed'


def serializer():
    return URLSafeSerializer(current_app.secret_key, salt='home-alert-dismissal-v1')


def prepare_alerts(user_id, actions):
    dismissed = {row.message for row in Notification.query.filter_by(
        user_id=user_id, channel='in_app', kind=KIND).all()}
    for action in actions:
        # Changed details create a fresh reminder; dismissal never resolves its source.
        identity = json.dumps([action['url'], action['label'], action['detail']], ensure_ascii=False)
        key = hashlib.sha256(identity.encode()).hexdigest()
        action['dismissed'] = key in dismissed
        action['dismiss_token'] = serializer().dumps({'user_id': user_id, 'key': key})
    return actions


def dismiss_alert(user_id, token):
    payload = serializer().loads(token)
    if payload.get('user_id') != user_id:
        raise ValueError('Wrong recipient')
    key = payload['key']
    if not Notification.query.filter_by(user_id=user_id, channel='in_app', kind=KIND, message=key).first():
        db.session.add(Notification(user_id=user_id, channel='in_app', kind=KIND, message=key))
        db.session.commit()
