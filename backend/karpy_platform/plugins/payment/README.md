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
