"""Administrator TOTP state. Callers lock the user row before changing it."""
import hashlib
import hmac
import json
import re
import secrets
import time

import pyotp
from sqlalchemy import select

from fastapi import HTTPException
from karpy_platform.core.acl.models import UserMeta
from karpy_platform.core.security.secrets import encrypt_secret, decrypt_secret
from app.config import settings

KEY = "admin.mfa.v1"


async def load(db, user_id):
    row = await db.scalar(select(UserMeta).where(UserMeta.user_id == user_id, UserMeta.key == KEY)
                          .execution_options(populate_existing=True))
    return row, json.loads(row.value) if row else {}


async def save(db, user_id, state):
    row, _ = await load(db, user_id)
    if row:
        row.value = json.dumps(state)
    else:
        db.add(UserMeta(user_id=user_id, key=KEY, value=json.dumps(state)))
    await db.flush()


def counter(secret, code, last=-1):
    if not re.fullmatch(r"[0-9]{6}", code):
        return None
    if not secret:
        raise HTTPException(503, "authenticator_unavailable")
    otp = pyotp.TOTP(secret)
    now = int(time.time()) // otp.interval
    for step in (now, now - 1, now + 1):
        if step > last and hmac.compare_digest(otp.at(step * otp.interval), code):
            return step
    return None


async def consume(db, user_id, state, code):
    if not state.get("secret"):
        return False
    step = counter(decrypt_secret(state["secret"]), code, state.get("last", -1))
    if step is not None:
        state["last"] = step
    else:
        digest = hashlib.sha256(code.strip().lower().encode()).hexdigest()
        stored = state.get("recovery", [])
        match = next((value for value in stored if hmac.compare_digest(value, digest)), None)
        if not match:
            return False
        state["recovery"] = [value for value in stored if value != match]
    await save(db, user_id, state)
    return True


def new_recovery_codes():
    codes = [secrets.token_hex(16) for _ in range(8)]
    return codes, [hashlib.sha256(value.encode()).hexdigest() for value in codes]


def pending_state():
    secret = pyotp.random_base32()
    return secret, {"pending": encrypt_secret(secret), "expires": int(time.time()) + 600}


def provisioning(user, secret):
    """Setup key and QR code an authenticator app scans."""
    import base64
    import io

    import qrcode

    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email or user.username, issuer_name=f"{settings.APP_NAME} Admin")
    image = io.BytesIO()
    qrcode.make(uri).save(image, format="PNG")
    return {"secret": secret, "qr": "data:image/png;base64," + base64.b64encode(image.getvalue()).decode()}


# Sign-in setup: a password-verified admin with no authenticator must enrol one before any session exists.
SETUP_TTL = 600
SETUP_MAX_ATTEMPTS = 5


def _digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def start_sign_in_setup(user_id, identity, fingerprint):
    """New pending secret plus a single-use token for this sign-in attempt only."""
    secret, state = pending_state()
    raw = secrets.token_urlsafe(32)
    state.update({"setup_token": _digest(raw), "setup_identity": identity,
                  "setup_fingerprint": fingerprint, "setup_attempts": 0})
    return secret, state, f"{user_id}.{raw}"


def setup_token_user(token):
    user_id, _, raw = (token or "").rpartition(".")
    return user_id if user_id and raw else None


def setup_token_matches(state, token, fingerprint):
    raw = (token or "").rpartition(".")[2]
    return bool(
        not state.get("secret") and state.get("pending") and state.get("setup_token") and raw
        and hmac.compare_digest(state["setup_token"], _digest(raw))
        and hmac.compare_digest(str(state.get("setup_fingerprint", "")), fingerprint)
        and int(state.get("expires", 0)) >= time.time()
        and int(state.get("setup_attempts", 0)) < SETUP_MAX_ATTEMPTS
    )
