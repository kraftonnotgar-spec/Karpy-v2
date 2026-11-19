from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from zoneinfo import available_timezones

from app.config import settings


@dataclass
class SettingField:
    key: str
    label: str
    type: str = "text"
    default: Any = ""
    description: str = ""
    options: list[dict[str, Any]] = field(default_factory=list)
    required: bool = False
    secret: bool = False
    rules: dict[str, Any] = field(default_factory=dict)
    group: str | None = None
    depends_on: dict[str, Any] | None = None

    def to_dict(self, value: Any = None) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "type": self.type,
            "value": self.default if value is None else value,
            "default": self.default,
            "description": self.description,
            "options": self.options,
            "required": self.required,
            "secret": self.secret,
            "rules": self.rules,
            "group": self.group,
            "dependsOn": self.depends_on,
        }


@dataclass
class SettingSection:
    id: str
    title: str
    description: str = ""
    icon: str = "settings"
    route: str = ""
    priority: int = 100
    permission: str | None = None
    group: str = "settings.common"
    source: str = "core"
    hidden: bool = False
    fields: list[SettingField] = field(default_factory=list)

    def field_keys(self) -> list[str]:
        return [field.key for field in self.fields]

    def to_dict(self, values: dict[str, Any] | None = None) -> dict[str, Any]:
        values = values or {}
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "icon": self.icon,
            "route": self.route or f"/admin/settings/{self.id}",
            "priority": self.priority,
            "permission": self.permission,
            "group": self.group,
            "source": self.source,
            "hidden": self.hidden,
            "fields": [field.to_dict(values.get(field.key)) for field in self.fields],
        }


@dataclass
class SettingPanel:
    id: str
    title: str
    priority: int = 100
    sections: dict[str, SettingSection] = field(default_factory=dict)

    def to_dict(self, values: dict[str, Any] | None = None) -> dict[str, Any]:
        ordered_sections = sorted((section for section in self.sections.values() if not section.hidden), key=lambda section: (section.priority, section.title))
        return {
            "id": self.id,
            "title": self.title,
            "priority": self.priority,
            "sections": [section.to_dict(values) for section in ordered_sections],
        }


class SettingPanelRegistry:
    def __init__(self) -> None:
        self._panels: dict[str, SettingPanel] = {}
        self._booted = False

    def ensure_defaults(self) -> None:
        if self._booted:
            return
        self.register_panel("settings.common", "Common", priority=10)
        self.register_panel("settings.localization", "Localization", priority=20)
        self.register_panel("settings.others", "Others", priority=99998)
        for section in default_sections():
            self.register_section(section)
        self._booted = True

    def register_panel(self, panel_id: str, title: str, priority: int | None = None) -> SettingPanel:
        panel = self._panels.get(panel_id)
        if not panel:
            panel = SettingPanel(id=panel_id, title=title, priority=100 if priority is None else priority)
            self._panels[panel_id] = panel
        else:
            panel.title = title
            if priority is not None:
                panel.priority = priority
        return panel

    def register_section(self, section: SettingSection) -> None:
        self.register_panel(section.group, self.panel_title(section.group))
        self._panels[section.group].sections[section.id] = section

    def register_plugin_settings(self, plugin_name: str, manifest: dict[str, Any]) -> None:
        from karpy_platform.core.setting.email_templates import email_template_registry

        email_template_registry.register_from_manifest(plugin_name, manifest)
        plugin_settings = manifest.get("settings")
        if not plugin_settings:
            return

        fields = [
            SettingField(
                key=field["key"],
                label=field.get("label", field["key"].replace("_", " ").title()),
                type=field.get("type", "text"),
                default=field.get("default", ""),
                description=field.get("description", ""),
                options=field.get("options", []),
                required=field.get("required", False),
                secret=field.get("secret", False),
                rules=field.get("rules", {}),
                group=field.get("group"),
                depends_on=field.get("dependsOn") or field.get("depends_on"),
            )
            for field in plugin_settings.get("fields", [])
            if field.get("key")
        ]
        if not fields:
            return

        self.register_section(
            SettingSection(
                id=plugin_settings.get("id", f"plugin.{plugin_name}"),
                title=plugin_settings.get("title", manifest.get("name", plugin_name)),
                description=plugin_settings.get("description", manifest.get("description", "")),
                icon=plugin_settings.get("icon", manifest.get("icon", "plug")),
                route=plugin_settings.get("route", f"/admin/settings/plugins/{plugin_name}"),
                priority=plugin_settings.get("priority", 500),
                permission=plugin_settings.get("permission"),
                group=plugin_settings.get("group", "settings.others"),
                source=f"plugin:{plugin_name}",
                fields=fields,
            )
        )

    def panels(self, values: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        self.ensure_defaults()
        return [
            panel.to_dict(values)
            for panel in sorted(self._panels.values(), key=lambda item: (item.priority, item.title))
        ]

    def sections(self) -> list[SettingSection]:
        self.ensure_defaults()
        sections: list[SettingSection] = []
        for panel in self._panels.values():
            sections.extend(panel.sections.values())
        return sorted(sections, key=lambda section: (section.group, section.priority, section.title))

    def get_section(self, section_id: str) -> SettingSection | None:
        self.ensure_defaults()
        for panel in self._panels.values():
            if section_id in panel.sections:
                return panel.sections[section_id]
        return None

    def fields(self) -> dict[str, SettingField]:
        result = {}
        for section in self.sections():
            for field in section.fields:
                result[field.key] = field
        return result

    def panel_title(self, panel_id: str) -> str:
        labels = {
            "settings.common": "Common",
            "settings.localization": "Localization",
            "settings.others": "Others",
        }
        return labels.get(panel_id, panel_id.removeprefix("settings.").replace(".", " ").title())


def options(values: list[str] | dict[str, str]) -> list[dict[str, str]]:
    if isinstance(values, dict):
        return [{"value": key, "label": label} for key, label in values.items()]
    return [{"value": value, "label": value} for value in values]


def default_sections() -> list[SettingSection]:
    timezone_choices = options(sorted(available_timezones()))
    cleanup_periods = options(
        {
            "0": "Never",
            "1": "1 Day",
            "3": "3 Days",
            "7": "1 Week",
            "30": "1 Month",
            "90": "3 Months",
            "180": "6 Months",
            "365": "1 Year",
        }
    )
    return [
        SettingSection(
            id="general",
            title="General",
            description="View and update your general settings and activate license.",
            icon="settings",
            priority=-9999,
            fields=[
                SettingField("site_title", "Site title", default=settings.APP_NAME, required=True),
                SettingField("admin_email", "Admin Email", type="tags", default=["admin@company.com"], rules={"max_items": 4}),
                SettingField("time_zone", "Timezone", type="select", default="UTC", options=timezone_choices),
                SettingField("site_language_direction", "Front site language direction", type="select", default="ltr", options=options({"ltr": "Left to Right", "rtl": "Right to Left"})),
                SettingField("site_language", "Site language", type="select", default="en", options=options({"en": "English - en"})),
                SettingField("enable_send_error_reporting_via_email", "Send error reporting via email", type="switch", default="0"),
                SettingField("redirect_404_to_homepage", "Redirect all Not Found requests to homepage", type="switch", default="0"),
                SettingField("clear_request_logs_after", "Clear old Request Logs", type="select", default="30", options=cleanup_periods),
                SettingField("clear_audit_logs_after", "Clear old Audit Logs", type="select", default="30", options=cleanup_periods),
                SettingField("license_file_content", "License file content", type="textarea", default="", secret=True),
                SettingField("licensed_to", "Licensed to", default="", secret=True),
                SettingField("license_envato_username", "Envato username", default="", secret=True),
                SettingField("license_purchase_code", "Purchase code", default="", secret=True),
                SettingField("license_status", "License status", default="", secret=True),
                SettingField("license_activated_at", "License activated at", default="", secret=True),
            ],
        ),
        SettingSection(
            id="email",
            title="Email",
            description="View and update your email settings and email templates.",
            icon="mail",
            priority=-9990,
            permission="settings.email",
            fields=[
                SettingField(
                    "email_driver",
                    "Mailer",
                    type="select",
                    default="log",
                    options=options(
                        {
                            "smtp": "SMTP",
                            "mailgun": "Mailgun",
                            "ses": "SES",
                            "postmark": "Postmark",
                            "resend": "Resend",
                            "log": "Log (for testing only, will not send email)",
                            "array": "Array (for testing only, will not send email)",
                            "sendmail": "Sendmail",
                        }
                    ),
                    required=True,
                ),
                SettingField("email_port", "Port", type="number", default="587", description="The port used by your mail server (common ports: 25, 465, 587)", group="smtp", depends_on={"email_driver": "smtp"}),
                SettingField("email_host", "Host", description="SMTP host address", group="smtp", depends_on={"email_driver": "smtp"}),
                SettingField("email_username", "Username", description="Your mail server login username", group="smtp", depends_on={"email_driver": "smtp"}),
                SettingField("email_password", "Password", type="password", secret=True, description="Your mail server login password", group="smtp", depends_on={"email_driver": "smtp"}),
                SettingField("email_local_domain", "Local domain", default="", description="The domain that will be used to identify this server with remote SMTP servers", group="smtp", depends_on={"email_driver": "smtp"}),
                SettingField("email_encryption", "Encryption", type="select", default="tls", options=options({"": "None", "tls": "TLS", "ssl": "SSL"}), description="Choose the encryption method for secure email transmission", group="smtp", depends_on={"email_driver": "smtp"}),
                SettingField("email_mail_gun_domain", "Mailgun domain", description="The verified Mailgun sending domain", group="mailgun", depends_on={"email_driver": "mailgun"}),
                SettingField("email_mail_gun_secret", "Mailgun secret", type="password", secret=True, description="Your Mailgun private API key", group="mailgun", depends_on={"email_driver": "mailgun"}),
                SettingField("email_mail_gun_endpoint", "Mailgun endpoint", default="api.mailgun.net", description="Use api.eu.mailgun.net for EU accounts", group="mailgun", depends_on={"email_driver": "mailgun"}),
                SettingField("email_ses_key", "SES key", description="AWS access key ID", group="ses", depends_on={"email_driver": "ses"}),
                SettingField("email_ses_secret", "SES secret", type="password", secret=True, description="AWS secret access key", group="ses", depends_on={"email_driver": "ses"}),
                SettingField("email_ses_region", "SES region", default="us-east-1", description="AWS SES region", group="ses", depends_on={"email_driver": "ses"}),
                SettingField("email_postmark_token", "Postmark token", type="password", secret=True, description="Postmark server API token", group="postmark", depends_on={"email_driver": "postmark"}),
                SettingField("email_resend_key", "Resend key", type="password", secret=True, description="Resend API key", group="resend", depends_on={"email_driver": "resend"}),
                SettingField("email_sendmail_path", "Sendmail path", default="/usr/sbin/sendmail -bs", description="Default: /usr/sbin/sendmail -bs", group="sendmail", depends_on={"email_driver": "sendmail"}),
                SettingField("email_log_channel", "Log channel", type="select", default="single", options=options(["single", "daily"]), description="Select which logging channel to use for email logs", group="log", depends_on={"email_driver": "log"}),
                SettingField("email_from_name", "Sender name", default=settings.APP_NAME, description="The name that will appear in the From field of emails sent by the system", required=True),
                SettingField("email_from_address", "Sender email", default="admin@company.com", type="email", description="The email address that will be used as the sender for all emails sent by the system", required=True),
                SettingField("email_default_language", "Default email language", type="select", default="auto", options=options({"auto": "Auto (use default site language)", "en": "English - en"}), description="Select the default language for customer emails."),
            ],
        ),
        SettingSection(
            id="email_templates",
            title="Email templates",
            description="Base header/footer templates and plugin email templates.",
            icon="mail-code",
            route="/admin/settings/email-templates",
            priority=-9980,
            permission="settings.email",
            fields=[
                SettingField("email_template_logo", "Logo", type="media", default="", description="If not set, it will use the admin logo from Admin -> Settings -> Admin appearance -> Logo. Supports png, jpg, jpeg, and gif formats."),
                SettingField("email_template_email_contact", "Contact email address", type="email", default="", description="If not set, it will get from sender email in Admin -> Settings -> Email."),
                SettingField("email_template_copyright_text", "Copyright", default="©2026 Your Company. All rights reserved.", description="If not set, it will get from theme options copyright."),
                SettingField("email_template_max_height_for_logo", "Logo height (px)", type="number", default="40", description="Set the height of the logo in pixels. The default value is 40px.", rules={"min": 1, "max": 150}),
                SettingField("email_template_custom_css", "Email template custom CSS", type="code", default="", secret=True, rules={"max_length": 100000}),
                SettingField("email_template_social_links", "Social Links", type="json", default=[]),
            ],
        ),
        SettingSection(
            id="email_rules",
            title="Email rules",
            description="Configure email rules for validation",
            icon="mail-check",
            priority=-9970,
            permission="settings.email",
            fields=[
                SettingField("email_global_enabled", "Enable outgoing email", type="switch", default="1"),
                SettingField("email_rule_blacklisted_domains", "Blacklisted Email Domains", default="", description="Enter a list of email domains to be blacklisted. E.g. gmail.com, yahoo.com."),
                SettingField("email_rule_blacklisted_addresses", "Blacklisted Email Addresses", default="", description="Enter a list of specific email addresses to be blacklisted. E.g. mail@example.com."),
                SettingField("email_rule_exception_emails", "Exception Emails", default="", description="These emails will be excluded from the validation rules."),
                SettingField("email_rule_strict_validation", "Strict Email Validation", type="switch", default="0", description="Perform RFC-like email validation with strict rules."),
                SettingField("email_rule_dns_check", "DNS Check Validation", type="switch", default="0", description="Check if there are DNS records indicating the server accepts emails."),
                SettingField("email_rule_spoofing_detection", "Spoofing Detection", type="switch", default="0", description="Detect potential email spoofing attempts."),
            ],
        ),
        SettingSection(
            id="phone_number",
            title="Phone Number",
            description="Configure phone number field settings",
            icon="phone",
            route="/admin/settings/phone-number",
            priority=-9960,
            fields=[
                SettingField("phone_country_code_enabled", "Enable Country Code Selection", type="switch", default="1", description="When enabled, phone number fields will display a country code selector with automatic country detection."),
                SettingField("phone_available_countries_all", "All", type="switch", default="1", description="Select all countries to be available in the phone country code selector."),
                SettingField("phone_available_countries", "Available Countries", type="json", default=[]),
                SettingField("phone_default_country", "Default country", type="select", default="TZ"),
                SettingField("phone_min_length", "Minimum Length", type="number", default="9", description="Minimum number of characters required for phone numbers.", rules={"min": 1, "max": 30}),
                SettingField("phone_max_length", "Maximum Length", type="number", default="15", description="Maximum number of characters allowed for phone numbers.", rules={"min": 1, "max": 30}),
            ],
        ),
        SettingSection(
            id="media",
            title="Media",
            description="Settings for media",
            icon="folder",
            priority=10,
            fields=[
                SettingField("media_driver", "Driver", type="select", default="local", options=options({"local": "Local disk", "s3": "Amazon S3", "r2": "Cloudflare R2", "do_spaces": "DigitalOcean Spaces", "wasabi": "Wasabi", "bunnycdn": "BunnyCDN", "backblaze": "Backblaze B2"}), required=True),
                SettingField("media_aws_access_key_id", "AWS access key ID", depends_on={"media_driver": "s3"}),
                SettingField("media_aws_secret_key", "AWS secret key", type="password", secret=True, depends_on={"media_driver": "s3"}),
                SettingField("media_aws_default_region", "AWS default region", depends_on={"media_driver": "s3"}),
                SettingField("media_aws_bucket", "AWS bucket", depends_on={"media_driver": "s3"}),
                SettingField("media_aws_url", "AWS URL", depends_on={"media_driver": "s3"}),
                SettingField("media_aws_endpoint", "AWS endpoint", depends_on={"media_driver": "s3"}),
                SettingField("media_s3_path", "S3 path", depends_on={"media_driver": "s3"}),
                SettingField("media_aws_use_path_style_endpoint", "Use path style endpoint", type="select", default="0", options=options({"0": "No", "1": "Yes"}), depends_on={"media_driver": "s3"}),
                SettingField("media_r2_access_key_id", "R2 access key ID", depends_on={"media_driver": "r2"}),
                SettingField("media_r2_secret_key", "R2 secret key", type="password", secret=True, depends_on={"media_driver": "r2"}),
                SettingField("media_r2_bucket", "R2 bucket", depends_on={"media_driver": "r2"}),
                SettingField("media_r2_url", "R2 public URL", depends_on={"media_driver": "r2"}),
                SettingField("media_r2_endpoint", "R2 endpoint", depends_on={"media_driver": "r2"}),
                SettingField("media_r2_use_path_style_endpoint", "Use path style endpoint", type="select", default="1", options=options({"0": "No", "1": "Yes"}), depends_on={"media_driver": "r2"}),
                SettingField("media_do_spaces_access_key_id", "Spaces access key ID", depends_on={"media_driver": "do_spaces"}),
                SettingField("media_do_spaces_secret_key", "Spaces secret key", type="password", secret=True, depends_on={"media_driver": "do_spaces"}),
                SettingField("media_do_spaces_default_region", "Spaces region", depends_on={"media_driver": "do_spaces"}),
                SettingField("media_do_spaces_bucket", "Spaces bucket", depends_on={"media_driver": "do_spaces"}),
                SettingField("media_do_spaces_endpoint", "Spaces endpoint", depends_on={"media_driver": "do_spaces"}),
                SettingField("media_do_spaces_cdn_enabled", "Enable Spaces CDN", type="switch", default="0", depends_on={"media_driver": "do_spaces"}),
                SettingField("media_do_spaces_cdn_custom_domain", "Spaces CDN custom domain", depends_on={"media_driver": "do_spaces"}),
                SettingField("media_do_spaces_use_path_style_endpoint", "Use path style endpoint", type="select", default="0", options=options({"0": "No", "1": "Yes"}), depends_on={"media_driver": "do_spaces"}),
                SettingField("media_wasabi_access_key_id", "Wasabi access key ID", depends_on={"media_driver": "wasabi"}),
                SettingField("media_wasabi_secret_key", "Wasabi secret key", type="password", secret=True, depends_on={"media_driver": "wasabi"}),
                SettingField("media_wasabi_default_region", "Wasabi region", depends_on={"media_driver": "wasabi"}),
                SettingField("media_wasabi_bucket", "Wasabi bucket", depends_on={"media_driver": "wasabi"}),
                SettingField("media_wasabi_root", "Wasabi root", depends_on={"media_driver": "wasabi"}),
                SettingField("media_bunnycdn_zone", "BunnyCDN storage zone", depends_on={"media_driver": "bunnycdn"}),
                SettingField("media_bunnycdn_hostname", "BunnyCDN hostname", depends_on={"media_driver": "bunnycdn"}),
                SettingField("media_bunnycdn_key", "BunnyCDN key", type="password", secret=True, depends_on={"media_driver": "bunnycdn"}),
                SettingField("media_bunnycdn_region", "BunnyCDN region", type="select", default="de", options=options({"de": "Falkenstein", "ny": "New York", "la": "Los Angeles", "sg": "Singapore", "syd": "Sydney", "uk": "United Kingdom"}), depends_on={"media_driver": "bunnycdn"}),
                SettingField("media_backblaze_access_key_id", "Backblaze access key ID", depends_on={"media_driver": "backblaze"}),
                SettingField("media_backblaze_secret_key", "Backblaze secret key", type="password", secret=True, depends_on={"media_driver": "backblaze"}),
                SettingField("media_backblaze_default_region", "Backblaze region", depends_on={"media_driver": "backblaze"}),
                SettingField("media_backblaze_bucket", "Backblaze bucket", depends_on={"media_driver": "backblaze"}),
                SettingField("media_backblaze_endpoint", "Backblaze endpoint", depends_on={"media_driver": "backblaze"}),
                SettingField("media_backblaze_url", "Backblaze public URL", depends_on={"media_driver": "backblaze"}),
                SettingField("media_backblaze_use_path_style_endpoint", "Use path style endpoint", type="select", default="1", options=options({"0": "No", "1": "Yes"}), depends_on={"media_driver": "backblaze"}),
                SettingField("media_backblaze_cdn_enabled", "Enable Backblaze CDN", type="switch", default="0", depends_on={"media_driver": "backblaze"}),
                SettingField("media_backblaze_cdn_custom_domain", "Backblaze CDN custom domain", depends_on={"media_driver": "backblaze"}),
                SettingField("media_use_original_name_for_file_path", "Use original name for file path", type="switch", default="0", description="When enabled, uploaded files will keep their original names. When disabled, file names will be converted to URL-friendly slugs."),
                SettingField("media_convert_file_name_to_uuid", "Convert file name to UUID", type="switch", default="0", description="Useful to prevent duplicate file names and improve security."),
                SettingField("media_keep_original_file_size_and_quality", "Keep original file size and quality", type="switch", default="0", description="When enabled, uploaded images are not resized or optimized."),
                SettingField("media_image_quality", "Image quality", type="number", default="75", description="Set the quality for image encoding (70-100). Lower values produce smaller files.", rules={"min": 1, "max": 100}),
                SettingField("media_turn_off_automatic_url_translation_into_latin", "Turn off automatic URL translation into Latin", type="switch", default="0"),
                SettingField("user_can_only_view_own_media", "Users can only view their own media", type="switch", default="0"),
                SettingField("media_convert_image_to_webp", "Convert JPG, JPEG, PNG image to WebP", type="switch", default="0", description="Applied to JPG/JPEG/PNG images when uploading."),
                SettingField("media_default_placeholder_image", "Default placeholder image", type="media", default=""),
                SettingField("max_upload_filesize", "Max upload filesize (MB)", type="number", default=settings.MAX_UPLOAD_SIZE_MB, rules={"min": 0}),
                SettingField("media_reduce_large_image_size", "Reduce large image size when uploading", type="switch", default="0"),
                SettingField("media_image_max_width", "Image max width", type="number", default="", depends_on={"media_reduce_large_image_size": "1"}, rules={"min": 200}),
                SettingField("media_image_max_height", "Image max height", type="number", default="", depends_on={"media_reduce_large_image_size": "1"}, rules={"min": 200}),
                SettingField("media_customize_upload_path", "Customize upload path", type="switch", default="0", description="By default, KARPy uploads files under the media directory."),
                SettingField("media_upload_path", "Upload path", default="storage", depends_on={"media_customize_upload_path": "1"}),
                SettingField("media_chunk_enabled", "Enable chunk upload", type="switch", default="1"),
                SettingField("media_chunk_size", "Chunk size (MB)", type="number", default="2"),
                SettingField("media_max_file_size", "Chunk max file size (MB)", type="number", default="512"),
                SettingField("media_watermark_enabled", "Enable watermark", type="switch", default="0"),
                SettingField("media_watermark_source", "Watermark image", type="media", default="", depends_on={"media_watermark_enabled": "1"}),
                SettingField("media_watermark_size", "Watermark size", type="number", default="10", depends_on={"media_watermark_enabled": "1"}),
                SettingField("media_watermark_opacity", "Watermark opacity", type="number", default="70", depends_on={"media_watermark_enabled": "1"}, rules={"min": 0, "max": 100}),
                SettingField("media_watermark_position", "Watermark position", type="select", default="bottom-right", options=options(["top-left", "top-right", "bottom-left", "bottom-right", "center"]), depends_on={"media_watermark_enabled": "1"}),
                SettingField("media_watermark_position_x", "Watermark position X", type="number", default="10", depends_on={"media_watermark_enabled": "1"}),
                SettingField("media_watermark_position_y", "Watermark position Y", type="number", default="10", depends_on={"media_watermark_enabled": "1"}),
                SettingField("media_image_processing_library", "Image processing library", type="select", default="pillow", options=options({"pillow": "Pillow (Python)", "imagemagick": "ImageMagick"})),
                SettingField("media_enable_thumbnail_sizes", "Enable thumbnail sizes", type="switch", default="1"),
                SettingField("media_sizes_thumb_width", "Thumb width", type="number", default="150"),
                SettingField("media_sizes_thumb_height", "Thumb height", type="number", default="150"),
                SettingField("media_sizes_featured_width", "Featured width", type="number", default="565"),
                SettingField("media_sizes_featured_height", "Featured height", type="number", default="375"),
                SettingField("media_sizes_medium_width", "Medium width", type="number", default="540"),
                SettingField("media_sizes_medium_height", "Medium height", type="number", default="360"),
                SettingField("media_sizes_small_width", "Small width", type="number", default="375"),
                SettingField("media_sizes_small_height", "Small height", type="number", default="250"),
                SettingField("media_sizes_size_270x180_width", "270X180 width", type="number", default="270"),
                SettingField("media_sizes_size_270x180_height", "270X180 height", type="number", default="180"),
                SettingField("media_thumbnail_crop_position", "Thumbnail crop position", type="select", default="center", options=options(["left", "right", "top", "bottom", "center"])),
            ],
        ),
        SettingSection(
            id="tracking",
            title="Website Tracking",
            description="Choose your preferred analytics and tracking method. Only one option can be active at a time.",
            icon="globe",
            priority=100,
            route="/admin/settings/website-tracking",
            fields=[
                SettingField("tracking_method", "Tracking method", type="select", default="none", options=options({"none": "Disabled", "karpy": "KARPy Analytics", "google_analytics": "Google Analytics only", "google_tag_manager": "Google Tag Manager", "custom": "Custom tracking code"})),
                SettingField("google_analytics_measurement_id", "Google Analytics Measurement ID", default="", depends_on={"tracking_method": "google_analytics"}),
                SettingField("google_tag_manager_id", "Google Tag Manager ID", default="", depends_on={"tracking_method": "google_tag_manager"}),
                SettingField("custom_tracking_code", "Custom tracking code", type="code", default="", secret=True, depends_on={"tracking_method": "custom"}),
                SettingField("tracking_dashboard_enabled", "Show website analytics on dashboard", type="switch", default="1", description="When enabled, users with Dashboard Analytics permission can view first-party traffic analytics on the dashboard."),
            ],
        ),
        SettingSection(
            id="api",
            title="API Settings",
            description="Configure your API access and security settings.",
            icon="key",
            route="/admin/settings/api",
            priority=95,
            fields=[
                SettingField("api_enabled", "Enable API", type="switch", default="1", description="Enable or disable the REST API for your website. When disabled, public API endpoints will be inaccessible."),
                SettingField("api_key", "API Key", default="", description="Optional security key for API access. When set, all public API requests must include this key in the X-API-KEY header.", rules={"max_length": 255}),
                SettingField("api_push_enabled", "Enable Push Notifications", type="switch", default="0", description="Enable or disable push notifications for mobile apps. When disabled, no notifications will be sent to devices."),
                SettingField("api_firebase_project_id", "Firebase Project ID", default="", description="Your Firebase project ID. You can find this in your Firebase project settings.", rules={"max_length": 120}),
                SettingField("api_firebase_service_account_path", "Service Account JSON File", default="", description="Upload your Firebase service account JSON file. It is stored under storage/app/firebase.", rules={"max_length": 255}),
                SettingField("api_push_device_tokens", "Device tokens", type="textarea", default="", description="Optional comma or newline separated device tokens for direct notification testing."),
            ],
        ),
        SettingSection(
            id="admin_appearance",
            title="Admin appearance",
            description="Admin logo, favicon, color, and custom admin assets.",
            icon="palette",
            priority=110,
            fields=[
                SettingField("admin_logo", "Admin logo", type="media"),
                SettingField("admin_favicon", "Admin favicon", type="media"),
                SettingField("admin_title", "Admin title", default=settings.APP_NAME),
                SettingField("admin_primary_color", "Primary color", type="color", default="#206bc4"),
                SettingField("admin_appearance_custom_css", "Custom CSS", type="code", secret=True),
                SettingField("admin_appearance_custom_header_js", "Header JavaScript", type="code", secret=True),
                SettingField("admin_appearance_custom_body_js", "Body JavaScript", type="code", secret=True),
                SettingField("admin_appearance_custom_footer_js", "Footer JavaScript", type="code", secret=True),
            ],
        ),
        SettingSection(
            id="cache",
            title="Cache",
            description="Configure caching for optimized speed.",
            icon="box",
            route="/admin/settings/cache",
            priority=120,
            fields=[
                SettingField("cache_admin_menu_enabled", "Cache admin menu", type="switch", default="1", description="Cache admin menu for optimized speed. Disable this while developing or customizing the admin menu."),
                SettingField("cache_front_menu_enabled", "Cache front menu", type="switch", default="1", description="Cache front menu for optimized speed."),
                SettingField("cache_user_avatar_enabled", "Cache user avatar", type="switch", default="1", description="Cache generated username avatars so they are not regenerated on every request."),
                SettingField("shortcode_cache_enabled", "Cache shortcodes (UI Blocks)", type="switch", default="1", description="Enable caching for shortcodes to reduce rendering time."),
                SettingField("shortcode_cache_ttl", "Cache duration (seconds)", type="number", default="1800", description="The duration to cache all shortcodes. Default is 1800 seconds (30 minutes)."),
                SettingField("widget_cache_enabled", "Cache widgets", type="switch", default="1", description="Enable caching for widgets to reduce rendering time."),
                SettingField("widget_cache_ttl", "Cache duration (seconds)", type="number", default="1800", description="The duration to cache all widgets. Default is 1800 seconds (30 minutes)."),
                SettingField("cache_installed_plugins_enabled", "Cache installed plugins", type="switch", default="1", description="Cache the list of installed plugins to reduce file system scans."),
                SettingField("cache_size_warning_threshold_mb", "Cache size warning threshold (MB)", type="number", default="50", description="Show a warning on the Cache Management page when cache exceeds this size."),
                SettingField("cache_auto_clear_when_size_exceeds_threshold", "Auto-clear cache when size exceeds threshold", type="switch", default="0", description="Automatically clear framework cache when it exceeds the configured threshold. Requires the scheduler."),
                SettingField("sitemap_use_cache", "Cache sitemap", type="switch", default="1", description="Cache sitemap output for large websites."),
                SettingField("cache_sitemap_timeout_minutes", "Sitemap cache timeout (in minutes)", type="number", default="60", description="The duration to cache sitemap responses."),
                SettingField("cache_personal_data_ttl", "Personal data cache TTL seconds", type="number", default="300", description="Short TTL for user-specific cache entries so private data never lingers too long."),
                SettingField("cache_key_prefix", "Cache key prefix", default="karpy", description="Namespace cache keys for this installation."),
            ],
        ),
        SettingSection(
            id="datatables",
            title="Datatables",
            description="Settings for datatables.",
            icon="table-options",
            route="/admin/settings/datatables",
            priority=130,
            fields=[
                SettingField(
                    "datatables_pagination_type",
                    "Pagination type",
                    type="select",
                    default="default",
                    options=options({"default": "Default", "dropdown": "Dropdown"}),
                    description="Choose how pagination controls are displayed: Default shows page numbers, Dropdown shows a compact dropdown selector.",
                ),
                SettingField(
                    "datatables_default_show_column_visibility",
                    "Show column visibility by default",
                    type="switch",
                    default="0",
                    description="Enable the column visibility toggle button in data tables to allow users to show/hide columns.",
                ),
                SettingField(
                    "datatables_default_show_export_button",
                    "Show export button by default",
                    type="switch",
                    default="0",
                    description="Display export options (CSV, Excel, PDF) in data tables for downloading table data.",
                ),
                SettingField(
                    "datatables_default_enable_responsive",
                    "Enable table responsive",
                    type="switch",
                    default="1",
                    description="Automatically adjust table columns to fit different screen sizes for better mobile experience.",
                ),
            ],
        ),
    ]


setting_panel_registry = SettingPanelRegistry()
