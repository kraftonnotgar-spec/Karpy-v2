from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from karpy_platform.core.js_validation.rules import explode_rules, is_remote_rule, parse_rule


async def validate_remote_field(
    field: str,
    value: Any,
    data: dict[str, Any],
    rules: dict[str, str | list[str]],
    validate_all: bool = False,
    db: AsyncSession | None = None,
) -> bool | list[str]:
    field_rules = explode_rules(rules.get(field, []))
    errors: list[str] = []

    for raw_rule in field_rules:
        rule = parse_rule(raw_rule)
        if not validate_all and not is_remote_rule(rule.name):
            continue
        error = await _validate_rule(field, value, rule.name, rule.parameters, data, db)
        if error:
            errors.append(error)

    return True if not errors else errors


async def _validate_rule(
    field: str,
    value: Any,
    rule: str,
    parameters: list[str],
    data: dict[str, Any],
    db: AsyncSession | None = None,
) -> str | None:
    if rule == "Required" and value in (None, ""):
        return f"The {field} field is required."
    if rule == "Email" and value and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", str(value)):
        return f"The {field} must be a valid email address."
    if rule == "Min" and parameters and value is not None and len(str(value)) < int(parameters[0]):
        return f"The {field} must be at least {parameters[0]}."
    if rule == "Max" and parameters and value is not None and len(str(value)) > int(parameters[0]):
        return f"The {field} may not be greater than {parameters[0]}."
    if rule == "Same" and parameters and value != data.get(parameters[0]):
        return f"The {field} and {parameters[0]} must match."
    if rule == "Unique" and db and parameters:
        table = parameters[0]
        column = parameters[1] if len(parameters) > 1 else field
        except_value = parameters[2] if len(parameters) > 2 else None
        id_column = parameters[3] if len(parameters) > 3 else "id"
        if _safe_identifier(table) and _safe_identifier(column) and _safe_identifier(id_column):
            query = f"SELECT COUNT(*) FROM {table} WHERE {column} = :value"
            params = {"value": value}
            if except_value not in (None, "", "NULL"):
                query += f" AND {id_column} != :except_value"
                params["except_value"] = except_value
            count = await db.scalar(text(query), params)
            if count:
                return f"The {field} has already been taken."
    if rule == "Exists" and db and parameters:
        table = parameters[0]
        column = parameters[1] if len(parameters) > 1 else field
        if _safe_identifier(table) and _safe_identifier(column):
            count = await db.scalar(text(f"SELECT COUNT(*) FROM {table} WHERE {column} = :value"), {"value": value})
            if not count:
                return f"The selected {field} is invalid."
    return None


def _safe_identifier(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", value))
