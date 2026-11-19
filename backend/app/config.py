"""KARPy backend configuration — typed environment settings, validated at boot."""

import os
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings
from pathlib import Path
from urllib.parse import urlparse


PRODUCTION_ENVS = {"production", "prod", "release"}
DEFAULT_SECRET_VALUES = {
    "",
    "karpy-dev-secret-change-me-in-production",
    "karpy-jwt-secret-change-me",
}


def running_on_vercel() -> bool:
    return os.getenv("VERCEL") == "1"


def default_database_url() -> str:
    if running_on_vercel():
        return "sqlite+aiosqlite:////tmp/karpy.db"
    return "sqlite+aiosqlite:///./karpy.db"


def default_media_dir() -> Path:
    if running_on_vercel():
        return Path("/tmp/karpy/media")
    return Path(__file__).resolve().parent.parent / "media"


def default_theme_public_dir() -> Path:
    if running_on_vercel():
        return Path("/tmp/karpy/themes")
    return Path(__file__).resolve().parent.parent / "public" / "themes"


def default_storage_dir() -> Path:
    if running_on_vercel():
        return Path("/tmp/karpy/storage")
    return Path(__file__).resolve().parent.parent / "storage"


class Settings(BaseSettings):
    # App Settings
    APP_NAME: str = "Karpy"  # brand name; admins can override it with the site_title setting
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True
    APP_ENV: str = "development"
    APP_URL: str = "http://127.0.0.1:9000"
    PUBLIC_SITE_URL: str | None = None
    USER_DASHBOARD_URL: str | None = None
    # Extra dashboard origins accepted while the dashboard moves host (comma-separated, scheme://host only).
    USER_DASHBOARD_ALIASES: str = ""
    ADMIN_DASHBOARD_URL: str | None = None
    ADMIN_BOOTSTRAP_USERNAME: str = "admin"
    ADMIN_BOOTSTRAP_EMAIL: str = "admin@company.com"
    ADMIN_BOOTSTRAP_PASSWORD: str | None = Field(default=None, repr=False)
    INTERNAL_TRUSTED_HOSTS: str = ""
    ADMIN_DIR: str = "admin"
    SECRET_KEY: str = "karpy-dev-secret-change-me-in-production"
    
    # Paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    PLATFORM_DIR: Path = BASE_DIR / "karpy_platform"
    PLUGINS_DIR: Path = PLATFORM_DIR / "plugins"
    THEMES_DIR: Path = PLATFORM_DIR / "themes"
    MEDIA_DIR: Path = default_media_dir()
    THEME_PUBLIC_DIR: Path = default_theme_public_dir()
    STORAGE_DIR: Path = default_storage_dir()
    
    # Database
    DATABASE_URL: str = default_database_url()
    
    # Auth / JWT
    JWT_SECRET: str = "karpy-jwt-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_MINUTES: int = 1440  # 24 hours
    AUTH_ACCESS_TOKEN_MINUTES: int = 15
    AUTH_REFRESH_DAYS: int = 1
    AUTH_REMEMBER_DAYS: int = 30
    AUTH_OTP_TTL_MINUTES: int = 15
    AUTH_OTP_MAX_ATTEMPTS: int = 5
    AUTH_OTP_RESEND_SECONDS: int = 60
    AUTH_MAX_LOGIN_ATTEMPTS: int = 5
    # Failed passwords for one account from all IPs before it needs a remembered device.
    AUTH_MAX_LOGIN_ATTEMPTS_PER_ACCOUNT: int = 25
    AUTH_RESET_CODES_PER_HOUR: int = 3
    AUTH_RESET_CODES_PER_DAY: int = 10
    AUTH_LOGIN_WINDOW_MINUTES: int = 15
    # Sign-up defaults (admins override them with auth.* settings; plugins with the auth.policy filter).
    AUTH_REGISTRATION_OPEN: bool = True
    AUTH_PHONE_REQUIRED: bool = True
    # Comma-separated ISO country codes accepted for phone numbers; empty = every country.
    AUTH_PHONE_COUNTRIES: str = ""
    # Mobile app sign-in for staff/admin accounts (they normally use the web admin).
    AUTH_MOBILE_ALLOW_STAFF: bool = False
    # Shown in GET /user/sessions for app sessions: "<APP_NAME> iOS app".
    AUTH_MOBILE_APP_LABEL: str | None = None
    
    # Security / Cookies
    SESSION_HTTP_ONLY: bool = True
    SESSION_SECURE_COOKIE: bool = False
    SESSION_SAME_SITE: str = "lax"
    ENABLE_HTTP_SECURITY_HEADERS: bool = True
    CORS_ALLOWED_ORIGINS: str = "*"
    
    # Redis / Cache
    REDIS_HOST: str = "127.0.0.1"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str | None = None
    REDIS_URL: str | None = Field(default=None, repr=False)
    CACHE_ENABLED: bool = False

    # RabbitMQ (events between services; see docs/SERVICES.md). Empty = events stay in the outbox.
    RABBITMQ_URL: str | None = Field(default=None, repr=False)
    RABBITMQ_EXCHANGE: str = "karpy.events"

    # Signed calls to services in other languages (services/README.md).
    # SERVICE_KEY_ID / SERVICE_SIGNING_SECRET identify this backend to services.
    SERVICE_KEY_ID: str | None = None
    SERVICE_SIGNING_SECRET: str | None = Field(default=None, repr=False)
    SERVICE_REQUEST_TIMEOUT_SECONDS: float = 10.0

    # Observability (off by default; the optional infrastructure plan in docs/INFRASTRUCTURE.md).
    OTEL_EXPORTER_OTLP_ENDPOINT: str | None = None
    OTEL_SERVICE_NAME: str = "karpy-backend"
    
    # Media
    MAX_UPLOAD_SIZE_MB: int = 10
    MAX_REQUEST_SIZE_MB: int = 16
    ALLOWED_IMAGE_TYPES: str = "jpeg,jpg,png,gif,webp,svg"

    # Marketplace / licensing
    ENVATO_API_TOKEN: str | None = None
    ENVATO_PERSONAL_TOKEN: str | None = None
    ENVATO_ITEM_ID: str | None = None
    
    # Server (Uvicorn config)
    HOST: str = "0.0.0.0"
    PORT: int = 9000

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.strip().lower() in PRODUCTION_ENVS

    @property
    def site_url(self) -> str:
        return (self.PUBLIC_SITE_URL or self.APP_URL).rstrip("/")

    @property
    def user_dashboard_url(self) -> str:
        return (self.USER_DASHBOARD_URL or self.site_url).rstrip("/")

    @property
    def user_dashboard_aliases(self) -> list[str]:
        """Validated transition origins for the dashboard; bare scheme://host, never a wildcard."""
        result: list[str] = []
        schemes = {"https"} if self.is_production else {"https", "http"}
        for value in self.USER_DASHBOARD_ALIASES.split(","):
            parsed = urlparse(value.strip())
            if (
                parsed.scheme in schemes and parsed.hostname and not parsed.username and not parsed.password
                and parsed.path in ("", "/") and not parsed.params and not parsed.query and not parsed.fragment
            ):
                origin = f"{parsed.scheme}://{parsed.netloc}"
                if origin not in result:
                    result.append(origin)
        return result

    @property
    def secure_cookies(self) -> bool:
        """Never permit plaintext auth cookies in a production environment."""
        return self.SESSION_SECURE_COOKIE or self.is_production

    @property
    def cors_allowed_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ALLOWED_ORIGINS.split(",") if origin.strip()] or ["*"]

    @property
    def trusted_host_list(self) -> list[str]:
        hosts = {"127.0.0.1", "localhost", "test", "testserver"}
        for value in (self.APP_URL, self.PUBLIC_SITE_URL, self.USER_DASHBOARD_URL, self.ADMIN_DASHBOARD_URL, *self.user_dashboard_aliases):
            hostname = urlparse(value or "").hostname
            if hostname:
                hosts.add(hostname)
        import re
        for hostname in self.INTERNAL_TRUSTED_HOSTS.split(","):
            hostname = hostname.strip()
            if hostname and re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]{0,251}[a-zA-Z0-9])?", hostname):
                hosts.add(hostname)
        return sorted(hosts)

    @field_validator("MAX_UPLOAD_SIZE_MB")
    @classmethod
    def validate_upload_size(cls, value: int) -> int:
        if value < 1 or value > 128:
            raise ValueError("MAX_UPLOAD_SIZE_MB must be from 1 through 128")
        return value

    @field_validator("MAX_REQUEST_SIZE_MB")
    @classmethod
    def validate_request_size(cls, value: int) -> int:
        if value < 1 or value > 256:
            raise ValueError("MAX_REQUEST_SIZE_MB must be from 1 through 256")
        return value

    @field_validator("JWT_ALGORITHM")
    @classmethod
    def validate_jwt_algorithm(cls, value: str) -> str:
        if value != "HS256":
            raise ValueError("JWT_ALGORITHM must be HS256")
        return value

    def validate_production_security(self) -> None:
        """Fail fast when a production boot would expose unsafe defaults."""
        if not self.is_production:
            return

        failures: list[str] = []
        if self.DEBUG:
            failures.append("DEBUG must be false when APP_ENV is production.")
        if "*" in self.cors_allowed_origin_list:
            failures.append("CORS_ALLOWED_ORIGINS must list trusted domains, not '*'.")
        if self.SECRET_KEY in DEFAULT_SECRET_VALUES or len(self.SECRET_KEY.strip()) < 32:
            failures.append("SECRET_KEY must be rotated to a strong value of at least 32 characters.")
        if self.JWT_SECRET in DEFAULT_SECRET_VALUES or len(self.JWT_SECRET.strip()) < 32:
            failures.append("JWT_SECRET must be rotated to a strong value of at least 32 characters.")
        if self.SECRET_KEY == self.JWT_SECRET:
            failures.append("SECRET_KEY and JWT_SECRET must be different values.")
        if self.SESSION_SAME_SITE.lower() not in {"lax", "strict"}:
            failures.append("SESSION_SAME_SITE must be 'lax' or 'strict' in production.")
        if self.DATABASE_URL.startswith("sqlite"):
            failures.append("DATABASE_URL must use PostgreSQL in production.")

        app_url = urlparse(self.APP_URL)
        if app_url.hostname in {"127.0.0.1", "localhost"}:
            failures.append("APP_URL must be the public HTTPS URL in production.")
        if app_url.scheme != "https":
            failures.append("APP_URL must use HTTPS in production.")

        if failures:
            message = "Unsafe production configuration:\n- " + "\n- ".join(failures)
            raise RuntimeError(message)

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug(cls, value):
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "prod", "production", "false", "0", "no", "off"}:
                return False
            if normalized in {"debug", "dev", "development", "true", "1", "yes", "on"}:
                return True
        return value

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def normalize_database_url(cls, value):
        if not value:
            return value
        text = str(value).strip()
        if text.startswith("postgres://"):
            return "postgresql+asyncpg://" + text.removeprefix("postgres://")
        if text.startswith("postgresql://"):
            return "postgresql+asyncpg://" + text.removeprefix("postgresql://")
        return text

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
settings.validate_production_security()
