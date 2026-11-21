from .v0001_current_schema import migration as current_schema
from .v0002_phone_identities import migration as phone_identities
from .v0003_payment_notifications import migration as payment_notifications

MIGRATIONS = (
    current_schema,
    phone_identities,
    payment_notifications,
)

__all__ = ["MIGRATIONS"]
