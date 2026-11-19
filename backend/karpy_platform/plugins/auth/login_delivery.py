"""Sign-in code delivery evidence. Contains no codes, message bodies or raw provider errors.

The platform records the attempt as auth security events; a notification plugin can keep
its own delivery log through the ``auth.login_code.requested`` / ``auth.login_code.delivered``
actions (see ``extensions.py``).
"""
from __future__ import annotations

from . import extensions


async def begin(db, user, challenge, sms):
    channels = ["email", "sms"] if sms else ["email"]
    records = {channel: {"channel": channel, "status": "processing"} for channel in channels}
    await extensions.action("auth.login_code.requested", db, user, challenge.id, channels)
    # Persist before dispatch: a crash must not erase evidence of an attempt.
    await db.commit()
    records["_user_id"] = user.id
    return records


def _status(channel, result):
    if isinstance(result, BaseException):
        # The provider might have accepted a request before a timeout.
        return "submission_unknown"
    if channel == "email":
        return "provider_accepted" if getattr(result, "sent", False) is True else "not_sent"
    if getattr(result, "test", False):
        return "simulated"
    status = getattr(result, "status", "")
    if status == "delivered":
        return "delivered"
    if status in {"queued", "processing", "pending", "sent", "accepted"}:
        return "provider_accepted"
    return "failed"


async def finish(db, records, results):
    user_id = records.get("_user_id")
    statuses = {channel: _status(channel, results[channel]) for channel in records if channel != "_user_id"}
    for channel, value in statuses.items():
        records[channel]["status"] = value
    await extensions.action("auth.login_code.delivered", db, user_id, statuses)
    await db.commit()
