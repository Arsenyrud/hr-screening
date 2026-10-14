"""Пароли, сессии и область доступа."""

import hashlib
import hmac
import secrets
import time

from fastapi import HTTPException


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 210000).hex()
    return salt + ':' + digest


def password_ok(password, stored):
    return hmac.compare_digest(password_hash(password, stored.split(':')[0]), stored)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def public_user(user):
    return {k: user[k] for k in ('id', 'username', 'role', 'tenant_id', 'projects')}


def scope(user, item):
    return item.get('tenant_id') == user['tenant_id'] and item.get('project_id') in user['projects']


def require(store, user, roles, item=None):
    if user['role'] not in roles or (item is not None and not scope(user, item)):
        store.audit(user['id'], user['role'], user['tenant_id'], None, 'access.denied', {'resource': item.get('id') if item else None})
        raise HTTPException(403, 'Нет доступа к этой операции или проекту')
