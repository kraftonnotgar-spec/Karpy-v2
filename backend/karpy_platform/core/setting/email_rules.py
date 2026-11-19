from __future__ import annotations

import re
import socket
from dataclasses import dataclass
from email.utils import parseaddr
from typing import Any


class EmailRuleError(ValueError):
    pass


@dataclass(frozen=True)
class EmailRuleResult:
    email: str
    allowed: bool
    reason: str = ""


def validate_email_for_rules(email: str, settings: dict[str, Any]) -> EmailRuleResult:
    normalized = normalize_email(email)
    if not normalized:
        raise EmailRuleError("Invalid email address.")

    exceptions = {normalize_email(item) for item in parse_list(settings.get("email_rule_exception_emails"))}
    if normalized in exceptions:
        return EmailRuleResult(normalized, True)

    if truthy(settings.get("email_global_enabled", "1")) is False:
        raise EmailRuleError("Outgoing email is disabled.")

    if not valid_email(normalized, strict=truthy(settings.get("email_rule_strict_validation"))):
        raise EmailRuleError("Invalid email address.")

    domain = normalized.rsplit("@", 1)[1]
    blacklisted_domains = {normalize_domain(item) for item in parse_list(settings.get("email_rule_blacklisted_domains"))}
    blacklisted_addresses = {normalize_email(item) for item in parse_list(settings.get("email_rule_blacklisted_addresses"))}

    if normalized in blacklisted_addresses:
        raise EmailRuleError("This email address is blacklisted.")
    if domain in blacklisted_domains or any(domain.endswith("." + blocked) for blocked in blacklisted_domains if blocked):
        raise EmailRuleError("This email domain is blacklisted.")

    if truthy(settings.get("email_rule_spoofing_detection")) and looks_spoofed(normalized):
        raise EmailRuleError("This email address looks suspicious.")

    if truthy(settings.get("email_rule_dns_check")) and not domain_accepts_email(domain):
        raise EmailRuleError("This email domain does not appear to accept email.")

    return EmailRuleResult(normalized, True)


def validate_email_rule_settings(values: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}

    for key in ("email_rule_blacklisted_addresses", "email_rule_exception_emails"):
        invalid = [item for item in parse_list(values.get(key)) if not valid_email(normalize_email(item), strict=False)]
        if invalid:
            errors[key] = f"Invalid email address: {invalid[0]}"

    invalid_domains = [item for item in parse_list(values.get("email_rule_blacklisted_domains")) if not valid_domain(normalize_domain(item))]
    if invalid_domains:
        errors["email_rule_blacklisted_domains"] = f"Invalid domain: {invalid_domains[0]}"

    return errors


def parse_list(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = re.split(r"[\n,;]+", str(value or ""))
    return [str(item).strip() for item in raw_items if str(item).strip()]


def normalize_email(value: Any) -> str:
    value = str(value or "").strip()
    _, parsed = parseaddr(value)
    return parsed.lower()


def normalize_domain(value: Any) -> str:
    domain = str(value or "").strip().lower()
    if domain.startswith("@"):
        domain = domain[1:]
    return domain.rstrip(".")


def valid_email(value: str, *, strict: bool) -> bool:
    if not value or len(value) > 254 or "@" not in value:
        return False
    local, domain = value.rsplit("@", 1)
    if not local or not valid_domain(domain):
        return False
    pattern = r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+$" if strict else r"^[^@\s<>]+$"
    return bool(re.match(pattern, local, re.IGNORECASE))


def valid_domain(domain: str) -> bool:
    if not domain or len(domain) > 253 or "." not in domain:
        return False
    try:
        ascii_domain = domain.encode("idna").decode("ascii")
    except UnicodeError:
        return False
    labels = ascii_domain.split(".")
    return all(label and len(label) <= 63 and re.match(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$", label, re.IGNORECASE) for label in labels)


def looks_spoofed(email: str) -> bool:
    if any(char in email for char in "\"'<>(),;:\\[]"):
        return True
    local, domain = email.rsplit("@", 1)
    if any(ord(char) < 32 for char in email):
        return True
    try:
        domain.encode("idna").decode("ascii")
    except UnicodeError:
        return True
    return bool(re.search(r"[\u202a-\u202e\u2066-\u2069]", local))


def domain_accepts_email(domain: str) -> bool:
    try:
        import dns.resolver  # type: ignore

        return bool(dns.resolver.resolve(domain, "MX"))
    except ImportError:
        try:
            socket.getaddrinfo(domain, None)
            return True
        except socket.gaierror:
            return False
    except Exception:
        return False


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}
