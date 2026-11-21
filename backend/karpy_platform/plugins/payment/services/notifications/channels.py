"""Channel implementations: in-app feed, email, SMS.

Each channel is independent and best-effort. The dispatcher wraps every call so a
channel failure (bad SMTP, missing provider) never breaks the payment flow. The
in-app channel adds its row to the caller's session WITHOUT committing, so the
notification is persisted atomically with the payment the caller is about to save.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from karpy_platform.core.setting.email_recipients import get_admin_emails
from karpy_platform.core.setting.mailer import mailer
from karpy_platform.plugins.payment.models.notification import PaymentNotification

from . import templates
from .events import NotificationContext
from .sms import resolve_sms_provider, sms_recipients

logger = logging.getLogger("karpy.plugins.payment.notifications")


async def deliver_in_app(
    db: AsyncSession, event: str, context: NotificationContext, values: dict[str, Any]
) -> PaymentNotification:
    """Persist an in-app admin notification on the caller's transaction (no commit)."""
    notification = PaymentNotification(
        event=event,
        title=templates.render_title(event, context, values),
        body=templates.render_short(event, context, values),
        payment_id=context.payment_id,
        reference=context.reference,
        amount=context.amount,
        currency=context.currency,
        status=context.status,
        customer_label=context.customer_label,
        data=dict(context.variables),
    )
    db.add(notification)
    return notification


async def deliver_email(
    db: AsyncSession, event: str, context: NotificationContext, values: dict[str, Any]
) -> list[Any]:
    """Email every admin recipient. Returns per-recipient delivery results."""
    recipients = await get_admin_emails(db)
    if not recipients:
        logger.info("payment notification email skipped: no admin recipients configured")
        return []
    subject, body, text = templates.render_email(event, context, values)
    results = []
    for recipient in recipients:
        try:
            results.append(mailer.send(values, to=recipient, subject=subject, html=body, text=text))
        except Exception:  # noqa: BLE001 - one bad recipient must not stop the rest
            logger.exception("payment notification email to a recipient failed")
    return results


async def deliver_sms(
    db: AsyncSession, event: str, context: NotificationContext, values: dict[str, Any]
) -> list[Any]:
    """Send a short SMS to each configured recipient through the resolved provider."""
    recipients = sms_recipients(values)
    if not recipients:
        logger.info("payment notification SMS skipped: no recipients configured")
        return []
    provider = await resolve_sms_provider(db, values)
    message = templates.render_short(event, context, values)
    results = []
    for recipient in recipients:
        try:
            results.append(await provider.send(recipient, message, reference=context.reference))
        except Exception:  # noqa: BLE001 - provider failures are logged, never raised
            logger.exception("payment notification SMS to a recipient failed")
    return results
