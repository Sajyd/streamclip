"""Declarative base, shared column helpers and per-table access metadata.

Every table declares, through `access(...)`, how the tenant-scoped database
role (`streamclip_app`) may touch it. Migrations turn that metadata into
GRANTs and row-level-security policies, and a test asserts the live database
matches it, so a new table cannot silently ship without isolation.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from sqlalchemy import DateTime, ForeignKey, MetaData, Uuid, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedColumn, mapped_column

from app.core.ids import uuid7

APP_ROLE = "streamclip_app"

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

RlsMode = Literal["tenant", "organization_self"]
READ = ("SELECT",)
READ_WRITE = ("SELECT", "INSERT", "UPDATE", "DELETE")


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def access(
    *,
    rls: RlsMode | None,
    app: tuple[str, ...] = (),
    app_update_columns: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Table `info` describing what the tenant-scoped role may do.

    rls="tenant"            rows visible when organization_id = current org
    rls="organization_self" the organizations table itself (id = current org)
    rls=None                no row filter: `app` must then be read-only or empty
    app_update_columns      restrict UPDATE to these columns (column-level grant)
    """
    if rls is None and any(p != "SELECT" for p in app):
        raise ValueError("Tables without RLS may only be readable by the app role")
    # Returned as Table keyword arguments: use it as the trailing dict of __table_args__.
    return {"info": {"rls": rls, "app": app, "app_update_columns": app_update_columns}}


def enum_type(enum_cls: type[StrEnum], name: str) -> SAEnum:
    """VARCHAR + CHECK constraint (named `ck_<table>_<name>`), not a native ENUM."""
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        validate_strings=True,
        values_callable=lambda members: [m.value for m in members],
    )


def json_column(nullable: bool = False, *, as_list: bool = False) -> MappedColumn[Any]:
    if nullable:
        return mapped_column(JSONB, nullable=True)
    if as_list:
        return mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    return mapped_column(JSONB, nullable=False, default=dict, server_default="{}")


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TimestampMixin(CreatedAtMixin):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class TenantMixin:
    """Row owned by exactly one organization (the tenant boundary)."""

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
