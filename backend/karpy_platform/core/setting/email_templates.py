from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.config import settings


@dataclass
class EmailTemplateDefinition:
    key: str
    title: str
    description: str
    subject: str = ""
    body: str = ""
    variables: dict[str, str] = field(default_factory=dict)
    can_off: bool = True
    enabled_by_default: bool = True


@dataclass
class EmailTemplateGroup:
    module: str
    name: str
    description: str = ""
    source: str = "core"
    type: str = "core"
    templates: dict[str, EmailTemplateDefinition] = field(default_factory=dict)


class EmailTemplateRegistry:
    """Botble-style email template registry.

    Core, packages, and plugins can register template groups here. The setting
    store keeps per-template status/content so plugin templates appear in the
    Email settings screen without hardcoding them in the UI.
    """

    def __init__(self) -> None:
        self._groups: dict[str, EmailTemplateGroup] = {}

    def register_group(
        self,
        module: str,
        name: str,
        templates: list[EmailTemplateDefinition] | dict[str, dict[str, Any]],
        *,
        description: str = "",
        source: str = "core",
        type: str = "core",
    ) -> None:
        normalized_templates: dict[str, EmailTemplateDefinition] = {}
        if isinstance(templates, dict):
            iterator = templates.items()
            for key, template in iterator:
                normalized_templates[key] = EmailTemplateDefinition(
                    key=key,
                    title=str(template.get("title", key.replace("_", " ").title())),
                    description=str(template.get("description", "")),
                    subject=str(template.get("subject", "")),
                    body=str(template.get("body", "")),
                    variables=dict(template.get("variables") or {}),
                    can_off=bool(template.get("can_off", True)),
                    enabled_by_default=bool(template.get("enabled_by_default", True)),
                )
        else:
            normalized_templates = {template.key: template for template in templates}

        self._groups[self.group_key(type, module)] = EmailTemplateGroup(
            module=module,
            name=name,
            description=description,
            source=source,
            type=type,
            templates=normalized_templates,
        )

    def register_from_manifest(self, plugin_name: str, manifest: dict[str, Any]) -> None:
        data = manifest.get("emailTemplates") or manifest.get("email_templates")
        if not data:
            return

        self.register_group(
            str(data.get("module") or plugin_name),
            str(data.get("name") or manifest.get("title") or manifest.get("name") or plugin_name),
            dict(data.get("templates") or {}),
            description=str(data.get("description") or manifest.get("description") or ""),
            source=f"plugin:{plugin_name}",
            type=str(data.get("type") or "plugins"),
        )

    def groups(self) -> list[EmailTemplateGroup]:
        default_order = {"base": 0, "acl": 10}
        return sorted(self._groups.values(), key=lambda group: (group.type, default_order.get(group.module, 100), group.name))

    def find(self, key: str) -> tuple[EmailTemplateGroup, EmailTemplateDefinition] | None:
        type_name, module, template_key = self.parse_key(key)
        group = self._groups.get(self.group_key(type_name, module))
        if not group:
            return None
        template = group.templates.get(template_key)
        if not template:
            return None
        return group, template

    def status_key(self, type_name: str, module: str, template: str) -> str:
        return f"email_template.status.{type_name}.{module}.{template}"

    def subject_key(self, type_name: str, module: str, template: str) -> str:
        return f"email_template.subject.{type_name}.{module}.{template}"

    def body_key(self, type_name: str, module: str, template: str) -> str:
        return f"email_template.body.{type_name}.{module}.{template}"

    def public_key(self, type_name: str, module: str, template: str) -> str:
        return f"{type_name}.{module}.{template}"

    def parse_key(self, key: str) -> tuple[str, str, str]:
        parts = key.split(".", 2)
        if len(parts) != 3:
            raise ValueError("Template key must use the type.module.template format.")
        return parts[0], parts[1], parts[2]

    def payload(self, values: dict[str, Any]) -> dict[str, Any]:
        groups: list[dict[str, Any]] = []
        test_templates: list[dict[str, str]] = []
        for group in self.groups():
            templates = []
            for template in group.templates.values():
                public_key = self.public_key(group.type, group.module, template.key)
                status_value = values.get(self.status_key(group.type, group.module, template.key))
                enabled = template.enabled_by_default if status_value in {None, ""} else _truthy(status_value)
                item = {
                    "key": public_key,
                    "type": group.type,
                    "module": group.module,
                    "name": template.key,
                    "title": template.title,
                    "description": template.description,
                    "subject": values.get(self.subject_key(group.type, group.module, template.key), template.subject),
                    "enabled": enabled,
                    "canOff": template.can_off,
                    "variables": template.variables,
                }
                templates.append(item)
                test_templates.append({"value": public_key, "label": template.title})
            groups.append(
                {
                    "key": self.group_key(group.type, group.module),
                    "type": group.type,
                    "module": group.module,
                    "name": group.name,
                    "description": group.description,
                    "source": group.source,
                    "templates": templates,
                }
            )
        return {"groups": groups, "testTemplates": test_templates}

    @staticmethod
    def group_key(type_name: str, module: str) -> str:
        return f"{type_name}.{module}"


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def default_template_variables() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "site_title": settings.APP_NAME,
        "site_url": settings.site_url,
        "site_logo": "",
        "site_email": "admin@company.com",
        "site_copyright": f"&copy; {now.year} {settings.APP_NAME}. All rights reserved.",
        "site_social_links": "",
        "css": "",
        "max_height_for_logo": "40",
        "date_time": now.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "date_year": str(now.year),
    }


email_template_registry = EmailTemplateRegistry()

email_template_registry.register_group(
    "base",
    "Base template",
    [
        EmailTemplateDefinition(
            key="header",
            title="Email template header",
            description="Template for header of emails",
            body=(
                "<style>{{ css }}</style>\n"
                "<table class=\"bb-wrapper\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\">\n"
                "    <tr>\n"
                "        <td align=\"center\">\n"
                "            <table class=\"bb-container\" width=\"640\" cellpadding=\"0\" cellspacing=\"0\">\n"
                "                <tr>\n"
                "                    <td class=\"bb-header\">\n"
                "                        <a href=\"{{ site_url }}\">\n"
                "                            <img src=\"{{ site_logo }}\" alt=\"{{ site_title }}\" style=\"max-height: {{ max_height_for_logo }}px;\">\n"
                "                        </a>\n"
                "                    </td>\n"
                "                </tr>\n"
                "            </table>\n"
                "        </td>\n"
                "    </tr>\n"
                "</table>"
            ),
            can_off=False,
        ),
        EmailTemplateDefinition(
            key="footer",
            title="Email template footer",
            description="Template for footer of emails",
            body=(
                "<table class=\"bb-wrapper\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\">\n"
                "    <tr>\n"
                "        <td align=\"center\">\n"
                "            <table class=\"bb-container\" width=\"640\" cellpadding=\"0\" cellspacing=\"0\">\n"
                "                <tr>\n"
                "                    <td class=\"bb-footer\">\n"
                "                        <p>{{ site_copyright }}</p>\n"
                "                        <p><a href=\"mailto:{{ site_email }}\">{{ site_email }}</a></p>\n"
                "                        {{ site_social_links }}\n"
                "                    </td>\n"
                "                </tr>\n"
                "            </table>\n"
                "        </td>\n"
                "    </tr>\n"
                "</table>"
            ),
            can_off=False,
        ),
        EmailTemplateDefinition(
            key="test",
            title="Test email template",
            description="Template used to verify mail configuration",
            subject="KARPy test email",
            body=(
                "{{ header }}\n\n"
                "<div class=\"bb-main-content\">\n"
                "    <table class=\"bb-box\" cellpadding=\"0\" cellspacing=\"0\">\n"
                "        <tr>\n"
                "            <td class=\"bb-content\">\n"
                "                <p>This is a test email. It's sent from {{ site_title }}.</p>\n"
                "                <p>It's not important, just ignore it.</p>\n"
                "            </td>\n"
                "        </tr>\n"
                "    </table>\n"
                "</div>\n\n"
                "{{ footer }}"
            ),
            variables={"site_title": "Site title", "site_url": "Site URL"},
        ),
    ],
    description="Header, footer, and system testing templates.",
    source="core",
    type="core",
)

email_template_registry.register_group(
    "acl",
    "ACL",
    [
        EmailTemplateDefinition(
            key="password-reminder",
            title="Reset password",
            description="Send email to user when requesting reset password",
            subject="Reset password",
            body=(
                "{{ header }}\n\n"
                "<div class=\"bb-main-content\">\n"
                "    <table class=\"bb-box\" cellpadding=\"0\" cellspacing=\"0\">\n"
                "        <tr>\n"
                "            <td class=\"bb-content\">\n"
                "                <h2>Reset password</h2>\n"
                "                <p>You are receiving this email because a password reset request was sent for your account.</p>\n"
                "                <p><a href=\"{{ reset_link }}\">Reset password</a></p>\n"
                "                <p>If you did not request a password reset, no further action is required.</p>\n"
                "            </td>\n"
                "        </tr>\n"
                "    </table>\n"
                "</div>\n\n"
                "{{ footer }}"
            ),
            variables={"reset_link": "Reset password link"},
            can_off=False,
        )
    ],
    description="Authentication email templates.",
    source="core",
    type="core",
)
