# Payment

Generated KARPy plugin scaffold.

## Required metadata

- Plugin ID: `krafton/payment`
- Folder: `payment`
- Provider: `karpy_platform.plugins.payment.provider`
- Version: `1.0.0`

## Commands

```bash
python -m karpy_platform plugin:activate payment
python -m karpy_platform crud:create Example --plugin payment
```

## Structure

- `plugin.json` is read by the KARPy plugin manager.
- `provider.py` is the plugin service provider.
- `routes.py` exposes plugin API routes under `/api/plugins/payment` when active.

## Gateway architecture

Payment is the provider-neutral engine: transactions, logs, secure method
settings, checkout dispatch, and signed webhook dispatch. It does not hardcode
or register any gateway.

Gateway plugins (one per payment provider, e.g. `<provider>_gateway`) and
`manual_payment` declare Payment as a dependency. An active gateway registers
its method, checkout callback, and optional signed webhook callback. Deactivating
it immediately removes the method from Payment Methods without deleting its
saved configuration, so reactivation is safe.

Plan checkout is idempotent at the gateway/webhook layer. A plan is assigned
only after a verified completion event (or explicit manual approval), and a
verified cancellation/refund revokes the matching assignment.
- `models/` contains SQLAlchemy models. Activation imports these models and creates missing plugin tables.
- `schemas/`, `services/`, `admin/`, and `database/migrations/` are ready for CRUD work.

## Admin notifications

Payment raises admin notifications for three events — **payment received**, **payment failed**, and
**new order/checkout created** — and delivers them over three channels: in-app, email and SMS.

- **Wiring:** `services/checkout.py::complete_payment` fires received/failed on a settled transition;
  `services/payments.py::create_payment` fires order-created on a new transaction. Both call
  `services/notifications/dispatcher.py::dispatch_payment_event`, which is best-effort and never breaks
  a payment (it does not commit the caller's session; the in-app row is committed with the payment).
- **In-app:** rows in `payment_notifications` (migration `v0003`), with an admin API under
  `/api/plugins/payment/notifications` (`GET /`, `GET /unread-count`, `POST /{id}/read`, `POST /read-all`).
- **Email:** the core mailer renders a per-event template and sends to the admin recipient list
  (`admin_email`, falling back to the sender address).
- **SMS:** a pluggable `SmsProvider` port (`services/notifications/sms.py`). The default `LogSmsProvider`
  makes no network call. A vendor plugin supplies a real provider via the
  `payment.notifications.sms_provider` filter or `sms_provider_registry`; no vendor is hardcoded.

### Settings (setting store, product-neutral)

| Key | Default | Meaning |
|---|---|---|
| `payment.notifications.enabled` | `true` | Master switch. |
| `payment.notifications.channels.in_app` | `true` | In-app feed channel. |
| `payment.notifications.channels.email` | `false` | Email channel (needs SMTP + `admin_email`). |
| `payment.notifications.channels.sms` | `false` | SMS channel (needs a provider + recipients). |
| `payment.notifications.events.{received,failed,order_created}` | `true` | Per-event switch. |
| `payment.notifications.sms.provider` | `log` | Selected SMS provider name. |
| `payment.notifications.sms.recipients` | `` | Comma-separated admin phone numbers. |
| `payment.notifications.templates.<event>.{title,short,subject,body}` | built-in defaults | Optional overrides. |

Email and SMS stay off until configured, so a fresh install never attempts delivery it was not set up for.
