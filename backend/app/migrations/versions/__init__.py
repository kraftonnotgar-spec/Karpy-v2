from .v0001_current_schema import migration as current_schema
from .v0002_phone_identities import migration as phone_identities

MIGRATIONS = (
    current_schema,
    phone_identities,
)

__all__ = ["MIGRATIONS"]
