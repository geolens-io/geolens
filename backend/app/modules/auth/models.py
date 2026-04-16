import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'pending', 'suspended', 'deactivated')",
            name="chk_users_status",
        ),
        CheckConstraint(
            "auth_provider IN ('local', 'oidc', 'oauth')",
            name="chk_users_auth_provider",
        ),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    username: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), server_default="active", nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    auth_provider: Mapped[str] = mapped_column(
        String(20), server_default="local", nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    roles: Mapped[list["Role"]] = relationship(
        secondary="catalog.user_roles", back_populates="users", lazy="selectin"
    )


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = {"schema": "catalog"}

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    users: Mapped[list["User"]] = relationship(
        secondary="catalog.user_roles", back_populates="roles", lazy="selectin"
    )


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = {"schema": "catalog"}

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.roles.id", ondelete="CASCADE"), primary_key=True
    )


class ApiKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = {"schema": "catalog"}

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["User"] = relationship("User", lazy="selectin")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = {"schema": "catalog"}

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    revoked: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )

    user: Mapped["User"] = relationship("User", lazy="selectin")
