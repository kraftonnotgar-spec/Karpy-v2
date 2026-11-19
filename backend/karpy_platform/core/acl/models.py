from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from datetime import datetime, timezone
import uuid


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    first_name: Mapped[str | None] = mapped_column(String(120), default="System")
    last_name: Mapped[str | None] = mapped_column(String(120), default="Admin")
    username: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True, index=True)
    email: Mapped[str] = mapped_column(String(120), unique=True, default="admin@company.com", index=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar: Mapped[str] = mapped_column(String(500), nullable=True)
    avatar_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    permissions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    super_user: Mapped[bool] = mapped_column(Boolean, default=False)
    manage_supers: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    remember_token: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        onupdate=utcnow,
    )

    roles: Mapped[list["Role"]] = relationship(
        "Role",
        secondary="role_users",
        back_populates="users",
        lazy="selectin",
    )
    meta: Mapped[list["UserMeta"]] = relationship("UserMeta", back_populates="user", cascade="all, delete-orphan")

    @property
    def name(self) -> str:
        return f"{self.first_name or ''} {self.last_name or ''}".strip()

    def has_permission(self, permission: str) -> bool:
        if self.super_user:
            return True

        if self.permissions and self.permissions.get(permission) is True:
            return True

        for role in self.roles:
            if role.permissions and role.permissions.get(permission) is True:
                return True

        return False


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    permissions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    description: Mapped[str | None] = mapped_column(String(400), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        onupdate=utcnow,
    )

    users: Mapped[list[User]] = relationship(
        "User",
        secondary="role_users",
        back_populates="roles",
        lazy="selectin",
    )


class RoleUser(Base):
    __tablename__ = "role_users"
    __table_args__ = (UniqueConstraint("user_id", "role_id", name="uq_role_users_user_role"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role_id: Mapped[str] = mapped_column(String(36), ForeignKey("roles.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        onupdate=utcnow,
    )


class Activation(Base):
    __tablename__ = "activations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(120))
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        onupdate=utcnow,
    )


class UserMeta(Base):
    __tablename__ = "user_meta"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        onupdate=utcnow,
    )

    user: Mapped[User] = relationship("User", back_populates="meta")

class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36))
    message: Mapped[str] = mapped_column(String(255))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
