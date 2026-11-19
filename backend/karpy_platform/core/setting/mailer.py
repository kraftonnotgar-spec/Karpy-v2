from __future__ import annotations

import base64
import html
import json
import re
import smtplib
import ssl
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path
from typing import Any

from app.config import settings as app_settings
from karpy_platform.core.support.copyright import with_current_year
from karpy_platform.core.setting.email_rules import EmailRuleError, validate_email_for_rules
from karpy_platform.core.setting.email_templates import default_template_variables, email_template_registry


@dataclass
class MailDeliveryResult:
    sent: bool
    driver: str
    to: str
    subject: str
    message: str


class MailDeliveryError(RuntimeError):
    pass


class Mailer:
    def render_template(self, template_key: str, values: dict[str, Any], variables: dict[str, Any] | None = None, *, parts: bool = True) -> tuple[str, str]:
        """``parts=False`` renders the body without the legacy header and footer partials."""
        found = email_template_registry.find(template_key)
        if not found:
            raise MailDeliveryError("Email template was not found.")

        group, template = found
        if not self.template_enabled(group.type, group.module, template.key, values):
            raise MailDeliveryError("This email template is disabled.")

        variables = {
            **default_template_variables(),
            "site_title": values.get("site_title") or app_settings.APP_NAME,
            "site_url": app_settings.site_url,
            "site_logo": values.get("email_template_logo") or values.get("admin_logo") or "",
            "site_email": values.get("email_template_email_contact") or values.get("email_from_address") or "admin@company.com",
            "site_copyright": with_current_year(values.get("email_template_copyright_text") or f"&copy; {{year}} {values.get('site_title') or app_settings.APP_NAME}. All rights reserved."),
            "site_social_links": self._render_social_links(values.get("email_template_social_links")),
            "css": values.get("email_template_custom_css") or "",
            "max_height_for_logo": values.get("email_template_max_height_for_logo") or "40",
            **(variables or {}),
        }
        variables["header"] = self.render_template_body("core.base.header", values, variables, include_parts=False) if parts else ""
        variables["footer"] = self.render_template_body("core.base.footer", values, variables, include_parts=False) if parts else ""

        subject = str(values.get(email_template_registry.subject_key(group.type, group.module, template.key)) or template.subject or "KARPy email")
        body = self.render_template_body(template_key, values, variables)
        return self._replace_variables(subject, variables), body

    def render_template_body(
        self,
        template_key: str,
        values: dict[str, Any],
        variables: dict[str, Any] | None = None,
        *,
        include_parts: bool = True,
    ) -> str:
        found = email_template_registry.find(template_key)
        if not found:
            raise MailDeliveryError("Email template was not found.")

        group, template = found
        body = str(values.get(email_template_registry.body_key(group.type, group.module, template.key)) or template.body)
        if self._is_base_partial(group.module, template.key) and self._contains_partial_placeholder(body):
            body = template.body
        variables = variables or default_template_variables()
        if not include_parts:
            variables = {key: value for key, value in variables.items() if key not in {"header", "footer"}}
        return self._replace_variables(body, variables)

    def template_enabled(self, type_name: str, module: str, template: str, values: dict[str, Any]) -> bool:
        status_key = email_template_registry.status_key(type_name, module, template)
        status_value = values.get(status_key)
        if status_value in {None, ""}:
            found = email_template_registry.find(email_template_registry.public_key(type_name, module, template))
            return bool(found[1].enabled_by_default) if found else True
        return str(status_value).strip().lower() in {"1", "true", "yes", "on", "enabled"}

    def send(
        self,
        values: dict[str, Any],
        *,
        to: str,
        subject: str,
        html: str,
        text: str | None = None,
        sender_name: str | None = None,
        reply_to: str | None = None,
    ) -> MailDeliveryResult:
        driver = str(values.get("email_driver") or "log").strip().lower()
        try:
            validated = validate_email_for_rules(to, values)
            to = validated.email
        except EmailRuleError as exception:
            raise MailDeliveryError(str(exception)) from exception
        # Callers may present a merchant's business as the display name, but the
        # authenticated sender address always remains the configured platform one.
        sender_name = self._header_text(sender_name) or str(values.get("email_from_name") or app_settings.APP_NAME)
        sender_email = str(values.get("email_from_address") or "admin@company.com")
        message = self._message(sender_name, sender_email, to, subject, html, text)
        reply_to = self._header_text(reply_to)
        # A single plain address only; anything else is dropped, never "repaired".
        if reply_to and re.fullmatch(r"[^\s@<>,;:\"]+@[^\s@<>,;:\"]+\.[^\s@<>,;:\"]+", reply_to):
            try:
                message["Reply-To"] = validate_email_for_rules(reply_to, {}).email
            except EmailRuleError:
                pass

        dispatchers = {
            "smtp": self._send_smtp,
            "log": self._send_log,
            "array": self._send_array,
            "sendmail": self._send_sendmail,
            "mailgun": self._send_mailgun,
            "postmark": self._send_postmark,
            "resend": self._send_resend,
            "ses": self._send_ses,
        }
        dispatcher = dispatchers.get(driver)
        if not dispatcher:
            raise MailDeliveryError(f"Unsupported mailer: {driver}")

        dispatcher(values, message, html=html)
        result_message = "Email stored in the local mail outbox." if driver == "array" else "Email written to the mail log." if driver == "log" else "Email sent successfully."
        return MailDeliveryResult(sent=driver not in {"log", "array"}, driver=driver, to=to, subject=subject, message=result_message)

    def _message(self, sender_name: str, sender_email: str, to: str, subject: str, html: str, text: str | None) -> EmailMessage:
        message = EmailMessage()
        message["From"] = formataddr((sender_name, sender_email))
        message["To"] = to
        message["Subject"] = subject
        message.set_content(text or self._plain_text(html))
        message.add_alternative(html, subtype="html")
        return message

    def _send_smtp(self, values: dict[str, Any], message: EmailMessage, **_: Any) -> None:
        from karpy_platform.core.security.secrets import decrypt_secret
        host = str(values.get("email_host") or "").strip()
        port = int(values.get("email_port") or 587)
        username = str(values.get("email_username") or "").strip()
        password = decrypt_secret(values.get("email_password"))
        encryption = str(values.get("email_encryption") or "").strip().lower()
        local_hostname = str(values.get("email_local_domain") or "").strip() or None
        if not host:
            raise MailDeliveryError("SMTP host is required.")

        try:
            if encryption == "ssl":
                with smtplib.SMTP_SSL(host, port, local_hostname=local_hostname, context=ssl.create_default_context(), timeout=20) as smtp:
                    self._smtp_login(smtp, username, password)
                    smtp.send_message(message)
                return

            with smtplib.SMTP(host, port, local_hostname=local_hostname, timeout=20) as smtp:
                if encryption == "tls":
                    smtp.starttls(context=ssl.create_default_context())
                self._smtp_login(smtp, username, password)
                smtp.send_message(message)
        except smtplib.SMTPAuthenticationError as exception:
            response = self._smtp_error_text(exception.smtp_error)
            raise MailDeliveryError(
                f'Failed to authenticate on SMTP server with username "{username or "(empty)"}". '
                f'Server response: {exception.smtp_code} {response}'
            ) from exception
        except (OSError, smtplib.SMTPException) as exception:
            raise MailDeliveryError(f"SMTP delivery failed: {exception}") from exception

    def _send_log(self, values: dict[str, Any], message: EmailMessage, **_: Any) -> None:
        channel = str(values.get("email_log_channel") or "single")
        path = app_settings.STORAGE_DIR / "logs" / f"mail-{channel}.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n[{datetime.now(timezone.utc).isoformat()}] {message.as_string()}\n")

    def _send_array(self, values: dict[str, Any], message: EmailMessage, **_: Any) -> None:
        path = app_settings.STORAGE_DIR / "email" / "outbox.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "from": message["From"],
            "to": message["To"],
            "subject": message["Subject"],
            "message": message.as_string(),
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _send_sendmail(self, values: dict[str, Any], message: EmailMessage, **_: Any) -> None:
        command = str(values.get("email_sendmail_path") or "").strip()
        if not command:
            raise MailDeliveryError("Sendmail path is required.")
        executable = command.split()[0]
        if not Path(executable).exists() and "\\" not in executable and "/" not in executable:
            raise MailDeliveryError("Sendmail executable was not found on this server.")
        try:
            subprocess.run(command.split(), input=message.as_bytes(), check=True, timeout=20)
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exception:
            raise MailDeliveryError(f"Sendmail delivery failed: {exception}") from exception

    def _send_mailgun(self, values: dict[str, Any], message: EmailMessage, **_: Any) -> None:
        domain = str(values.get("email_mail_gun_domain") or "").strip()
        secret = str(values.get("email_mail_gun_secret") or "").strip()
        endpoint = str(values.get("email_mail_gun_endpoint") or "api.mailgun.net").strip().removeprefix("https://")
        if not domain or not secret:
            raise MailDeliveryError("Mailgun domain and secret are required.")
        data = urllib.parse.urlencode(
            {
                "from": message["From"],
                "to": message["To"],
                "subject": message["Subject"],
                "html": message.get_body(preferencelist=("html",)).get_content(),
                **({"h:Reply-To": message["Reply-To"]} if message["Reply-To"] else {}),
            }
        ).encode()
        request = urllib.request.Request(f"https://{endpoint}/v3/{domain}/messages", data=data)
        token = base64.b64encode(f"api:{secret}".encode()).decode()
        request.add_header("Authorization", f"Basic {token}")
        self._urlopen(request, "Mailgun")

    def _send_postmark(self, values: dict[str, Any], message: EmailMessage, **_: Any) -> None:
        token = str(values.get("email_postmark_token") or "").strip()
        if not token:
            raise MailDeliveryError("Postmark token is required.")
        payload = {
            "From": self._address_only(message["From"]),
            "To": message["To"],
            "Subject": message["Subject"],
            "HtmlBody": message.get_body(preferencelist=("html",)).get_content(),
            "TextBody": message.get_body(preferencelist=("plain",)).get_content(),
            **({"ReplyTo": message["Reply-To"]} if message["Reply-To"] else {}),
        }
        request = urllib.request.Request("https://api.postmarkapp.com/email", data=json.dumps(payload).encode())
        request.add_header("Accept", "application/json")
        request.add_header("Content-Type", "application/json")
        request.add_header("X-Postmark-Server-Token", token)
        self._urlopen(request, "Postmark")

    def _send_resend(self, values: dict[str, Any], message: EmailMessage, **_: Any) -> None:
        key = str(values.get("email_resend_key") or "").strip()
        if not key:
            raise MailDeliveryError("Resend API key is required.")
        payload = {
            "from": message["From"],
            "to": [message["To"]],
            "subject": message["Subject"],
            "html": message.get_body(preferencelist=("html",)).get_content(),
            **({"reply_to": message["Reply-To"]} if message["Reply-To"] else {}),
        }
        request = urllib.request.Request("https://api.resend.com/emails", data=json.dumps(payload).encode())
        request.add_header("Authorization", f"Bearer {key}")
        request.add_header("Content-Type", "application/json")
        self._urlopen(request, "Resend")

    def _send_ses(self, values: dict[str, Any], message: EmailMessage, **_: Any) -> None:
        try:
            import boto3  # type: ignore
        except ImportError as exception:
            raise MailDeliveryError("Amazon SES requires boto3. Install boto3 in production before using this mailer.") from exception

        key = str(values.get("email_ses_key") or "").strip()
        secret = str(values.get("email_ses_secret") or "").strip()
        region = str(values.get("email_ses_region") or "us-east-1").strip()
        if not key or not secret or not region:
            raise MailDeliveryError("SES key, secret, and region are required.")
        client = boto3.client("ses", aws_access_key_id=key, aws_secret_access_key=secret, region_name=region)
        try:
            client.send_raw_email(Source=self._address_only(message["From"]), Destinations=[message["To"]], RawMessage={"Data": message.as_bytes()})
        except Exception as exception:
            raise MailDeliveryError(f"SES delivery failed: {exception}") from exception

    def _urlopen(self, request: urllib.request.Request, provider: str) -> None:
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                if response.status >= 400:
                    raise MailDeliveryError(f"{provider} delivery failed with status {response.status}.")
        except urllib.error.HTTPError as exception:
            detail = exception.read().decode(errors="ignore")
            raise MailDeliveryError(f"{provider} delivery failed: {detail or exception}") from exception
        except urllib.error.URLError as exception:
            raise MailDeliveryError(f"{provider} delivery failed: {exception.reason}") from exception

    @staticmethod
    def _header_text(value: str | None) -> str:
        if not isinstance(value, str):
            return ""
        return " ".join("".join(" " if ord(c) < 32 or ord(c) == 127 else c for c in value).split())[:200]

    @staticmethod
    def _smtp_login(smtp: smtplib.SMTP, username: str, password: str) -> None:
        if username:
            smtp.login(username, password)

    @staticmethod
    def _smtp_error_text(value: bytes | str) -> str:
        if isinstance(value, bytes):
            return value.decode(errors="replace")
        return str(value)

    @staticmethod
    def _replace_variables(content: str, variables: dict[str, Any]) -> str:
        rendered = content
        for key, value in variables.items():
            rendered = rendered.replace("{{ " + key + " }}", str(value)).replace("{{" + key + "}}", str(value))
        return rendered

    @staticmethod
    def _is_base_partial(module: str, template: str) -> bool:
        return module == "base" and template in {"header", "footer"}

    @staticmethod
    def _contains_partial_placeholder(body: str) -> bool:
        lowered = body.lower()
        return "{{ header }}" in lowered or "{{header}}" in lowered or "{{ footer }}" in lowered or "{{footer}}" in lowered

    @staticmethod
    def _plain_text(html: str) -> str:
        import re

        return re.sub(r"<[^>]+>", "", html).replace("&copy;", "(c)").strip() or "KARPy email"

    @staticmethod
    def _address_only(value: str) -> str:
        if "<" in value and ">" in value:
            return value.split("<", 1)[1].split(">", 1)[0]
        return value

    @staticmethod
    def _render_social_links(value: Any) -> str:
        if not isinstance(value, list):
            return ""
        links = []
        for item in value:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            url = str(item.get("url") or "").strip()
            image = str(item.get("image") or "").strip()
            # Only plain https links go into emails, and every value is escaped.
            if not url.lower().startswith("https://"):
                continue
            if image and not image.lower().startswith("https://"):
                image = ""
            label = html.escape(name or url, quote=True)
            href = html.escape(url, quote=True)
            if image:
                links.append(f'<a href="{href}"><img src="{html.escape(image, quote=True)}" alt="{label}" width="24" height="24"></a>')
            else:
                links.append(f'<a href="{href}">{label}</a>')
        return " ".join(links)


mailer = Mailer()
