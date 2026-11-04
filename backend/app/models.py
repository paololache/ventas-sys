"""Modelo de datos multi-tenant.

Jerarquía:  Tenant (empresa)  →  Workspace (espacio de trabajo)  →  datos comerciales.

Toda entidad comercial lleva `tenant_id` + `workspace_id` + `owner_id`. El acceso siempre se
filtra por workspace (que pertenece a un único tenant) en `app/deps.py::scoped`.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --------------------------------------------------------------------------- plataforma


class Tenant(Base):
    """Empresa. Aislada de las demás: usuarios, bot de Telegram y SMTP propios."""

    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    timezone: Mapped[str] = mapped_column(String(64), default="America/Lima")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # telegram_bot_token, telegram_webhook_secret, smtp_host/port/user/password/from
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    workspaces: Mapped[list[Workspace]] = relationship(back_populates="tenant", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    password_hash: Mapped[str] = mapped_column(String(200))
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Membership(Base):
    """Un usuario puede pertenecer a varias empresas con distinto rol."""

    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "tenant_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="member")  # owner | admin | member

    user: Mapped[User] = relationship()


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (UniqueConstraint("tenant_id", "slug"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80))
    # horario laboral, umbrales de notificación, horas de resumen, estado de envíos
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    tenant: Mapped[Tenant] = relationship(back_populates="workspaces")


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)


# --------------------------------------------------------------------------- base comercial


class Scoped:
    """Mixin de aislamiento: tenant + workspace + propietario."""

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class ListItem(Scoped, Base):
    """Catálogos editables (hoja `Listas`): etapa, tipo, prioridad, sector, marca, tipo_accion."""

    __tablename__ = "list_items"
    __table_args__ = (UniqueConstraint("workspace_id", "kind", "value"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)
    value: Mapped[str] = mapped_column(String(120))
    prob: Mapped[float | None] = mapped_column(Float, nullable=True)  # sólo etapas, 0..1
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)  # Ganada / Perdida
    is_won: Mapped[bool] = mapped_column(Boolean, default=False)
    is_paused: Mapped[bool] = mapped_column(Boolean, default=False)  # En pausa
    sort: Mapped[int] = mapped_column(Integer, default=0)


class Partner(Scoped, Base):
    __tablename__ = "partners"
    __table_args__ = (UniqueConstraint("workspace_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str] = mapped_column(Text, default="")


class Client(Scoped, Base):
    __tablename__ = "clients"
    __table_args__ = (UniqueConstraint("workspace_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    sector: Mapped[str] = mapped_column(String(120), default="")


class Contact(Scoped, Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(10), default="client")  # client | partner
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"), nullable=True)
    partner_id: Mapped[int | None] = mapped_column(ForeignKey("partners.id", ondelete="SET NULL"), nullable=True)
    cargo: Mapped[str] = mapped_column(String(120), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(60), default="")


class Opportunity(Scoped, Base):
    __tablename__ = "opportunities"
    __table_args__ = (UniqueConstraint("workspace_id", "code"), Index("ix_opp_ws_stage", "workspace_id", "stage"))

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20))  # OP-001
    tipo: Mapped[str] = mapped_column(String(20), default="DR")
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"), nullable=True)
    descripcion: Mapped[str] = mapped_column(String(500), default="")
    sector: Mapped[str] = mapped_column(String(120), default="")
    partner_id: Mapped[int | None] = mapped_column(ForeignKey("partners.id", ondelete="SET NULL"), nullable=True)
    distribuidor: Mapped[str] = mapped_column(String(120), default="")
    marca: Mapped[str] = mapped_column(String(120), default="")
    monto: Mapped[float] = mapped_column(Float, default=0)
    stage: Mapped[str] = mapped_column(String(80), default="Prospección")
    prioridad: Mapped[str] = mapped_column(String(20), default="Media")
    fecha_cierre_est: Mapped[date | None] = mapped_column(Date, nullable=True)
    prox_accion: Mapped[str] = mapped_column(String(500), default="")
    fecha_prox_accion: Mapped[date | None] = mapped_column(Date, nullable=True)
    sin_proximo_paso_motivo: Mapped[str] = mapped_column(String(500), default="")
    responsable_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    ultima_actualizacion: Mapped[date | None] = mapped_column(Date, nullable=True)
    stage_entered_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    comentarios: Mapped[str] = mapped_column(Text, default="")
    meddpicc_score: Mapped[int] = mapped_column(Integer, default=0)  # caché 0..16
    # campos específicos del negocio
    dr_vencimiento: Mapped[date | None] = mapped_column(Date, nullable=True)
    contrato_vencimiento: Mapped[date | None] = mapped_column(Date, nullable=True)
    seace_proceso: Mapped[str] = mapped_column(String(80), default="")
    seace_publicacion: Mapped[date | None] = mapped_column(Date, nullable=True)
    seace_buena_pro: Mapped[date | None] = mapped_column(Date, nullable=True)
    seace_propuestas: Mapped[date | None] = mapped_column(Date, nullable=True)
    competidor: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    client: Mapped[Client | None] = relationship()
    partner: Mapped[Partner | None] = relationship()
    responsable: Mapped[Contact | None] = relationship()


class StageHistory(Scoped, Base):
    __tablename__ = "stage_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("opportunities.id", ondelete="CASCADE"), index=True)
    from_stage: Mapped[str | None] = mapped_column(String(80), nullable=True)
    to_stage: Mapped[str] = mapped_column(String(80))
    changed_on: Mapped[date] = mapped_column(Date)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Activity(Scoped, Base):
    """Bitácora."""

    __tablename__ = "activities"
    __table_args__ = (UniqueConstraint("workspace_id", "import_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("opportunities.id", ondelete="CASCADE"), index=True)
    fecha: Mapped[date] = mapped_column(Date)
    tipo: Mapped[str] = mapped_column(String(80), default="Llamada")
    contacto: Mapped[str] = mapped_column(String(200), default="")
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    resumen: Mapped[str] = mapped_column(Text, default="")
    proximo_paso: Mapped[str] = mapped_column(String(500), default="")
    fecha_proximo_paso: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="app")  # app | telegram | import
    import_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Meddpicc(Scoped, Base):
    __tablename__ = "meddpicc"
    __table_args__ = (UniqueConstraint("opportunity_id", "criterion"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("opportunities.id", ondelete="CASCADE"), index=True)
    criterion: Mapped[str] = mapped_column(String(30))
    score: Mapped[int] = mapped_column(Integer, default=0)  # 0..2
    note: Mapped[str] = mapped_column(Text, default="")


# --------------------------------------------------------------------------- alertas


class AlertRule(Scoped, Base):
    """Umbrales y activación de cada regla, por workspace (editables desde la app)."""

    __tablename__ = "alert_rules"
    __table_args__ = (UniqueConstraint("workspace_id", "code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    severity: Mapped[str] = mapped_column(String(10), default="Media")
    params: Mapped[dict] = mapped_column(JSON, default=dict)


class Alert(Scoped, Base):
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alert_ws_status", "workspace_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_code: Mapped[str] = mapped_column(String(10))
    dedupe_key: Mapped[str] = mapped_column(String(120))
    opportunity_id: Mapped[int | None] = mapped_column(ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=True, index=True)
    partner_id: Mapped[int | None] = mapped_column(ForeignKey("partners.id", ondelete="CASCADE"), nullable=True)
    activity_id: Mapped[int | None] = mapped_column(ForeignKey("activities.id", ondelete="CASCADE"), nullable=True)
    base_severity: Mapped[str] = mapped_column(String(10))
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    urgent: Mapped[bool] = mapped_column(Boolean, default=False)  # Alta con fecha de hoy
    title: Mapped[str] = mapped_column(String(300))
    detail: Mapped[str] = mapped_column(Text, default="")
    sort_prioridad: Mapped[int] = mapped_column(Integer, default=1)  # 0 alta, 1 media, 2 baja
    sort_monto: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(10), default="open")  # open | resolved
    resolved_reason: Mapped[str] = mapped_column(String(120), default="")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    snoozed_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    notify_count: Mapped[int] = mapped_column(Integer, default=0)
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    @property
    def severity(self) -> str:
        return "Alta" if self.escalated else self.base_severity


class Holiday(Scoped, Base):
    __tablename__ = "holidays"
    __table_args__ = (UniqueConstraint("workspace_id", "fecha"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    fecha: Mapped[date] = mapped_column(Date)
    nombre: Mapped[str] = mapped_column(String(200), default="")


class TelegramLink(Base):
    """Vincula un chat de Telegram con (usuario, workspace) dentro de un tenant."""

    __tablename__ = "telegram_links"
    __table_args__ = (UniqueConstraint("tenant_id", "chat_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    chat_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    link_code: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    state: Mapped[dict] = mapped_column(JSON, default=dict)  # conversación pendiente
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SchedulerRun(Base):
    __tablename__ = "scheduler_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    ran_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
