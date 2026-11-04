"""Autenticación, gestión de empresas (tenants), espacios de trabajo y miembros."""
from __future__ import annotations

import re
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..channels.telegram import get_client
from ..db import get_db
from ..deps import current_user, require_superadmin, tenant_role
from ..models import Membership, Tenant, User, Workspace, WorkspaceMember
from ..security import create_token, hash_password, verify_password
from ..services.seed import seed_workspace

router = APIRouter(prefix="/api")


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "x"


class Login(BaseModel):
    email: EmailStr
    password: str


@router.post("/auth/login")
def login(body: Login, db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(User.email == body.email.lower()))
    if not u or not u.is_active or not verify_password(body.password, u.password_hash):
        raise HTTPException(401, "Credenciales inválidas")
    return {"access_token": create_token(u.id), "token_type": "bearer"}


def _accessible(db: Session, user: User):
    if user.is_superadmin:
        tenants = db.scalars(select(Tenant).order_by(Tenant.name)).all()
        role_of = {t.id: "superadmin" for t in tenants}
    else:
        ms = db.scalars(select(Membership).where(Membership.user_id == user.id)).all()
        tenants = [db.get(Tenant, m.tenant_id) for m in ms]
        role_of = {m.tenant_id: m.role for m in ms}
    out = []
    for t in tenants:
        wss = db.scalars(select(Workspace).where(Workspace.tenant_id == t.id).order_by(Workspace.name)).all()
        if role_of[t.id] == "member":
            ids = set(db.scalars(select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user.id)))
            wss = [w for w in wss if w.id in ids]
        out.append({"id": t.id, "name": t.name, "slug": t.slug, "timezone": t.timezone, "role": role_of[t.id], "is_active": t.is_active,
                    "workspaces": [{"id": w.id, "name": w.name, "slug": w.slug} for w in wss]})
    return out


@router.get("/auth/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"id": user.id, "email": user.email, "name": user.name, "is_superadmin": user.is_superadmin, "tenants": _accessible(db, user)}


class TenantIn(BaseModel):
    name: str
    slug: str | None = None
    timezone: str = "America/Lima"
    owner_email: EmailStr
    owner_name: str = ""
    owner_password: str
    workspace_name: str = "Principal"


@router.post("/tenants", status_code=201)
def create_tenant(body: TenantIn, db: Session = Depends(get_db), _: User = Depends(require_superadmin)):
    """Crea una empresa nueva (aislada), su propietario y un primer espacio de trabajo sembrado."""
    slug = body.slug or slugify(body.name)
    if db.scalar(select(Tenant).where(Tenant.slug == slug)):
        raise HTTPException(409, "Ya existe una empresa con ese identificador")
    t = Tenant(name=body.name, slug=slug, timezone=body.timezone, settings={"telegram_webhook_secret": secrets.token_urlsafe(24)})
    db.add(t)
    owner = db.scalar(select(User).where(User.email == body.owner_email.lower()))
    if not owner:
        owner = User(email=body.owner_email.lower(), name=body.owner_name, password_hash=hash_password(body.owner_password))
        db.add(owner)
    db.flush()
    db.add(Membership(user_id=owner.id, tenant_id=t.id, role="owner"))
    ws = Workspace(tenant_id=t.id, name=body.workspace_name, slug=slugify(body.workspace_name), settings={})
    db.add(ws)
    db.flush()
    seed_workspace(db, t, ws, owner.id)
    db.commit()
    return {"id": t.id, "slug": t.slug, "workspace_id": ws.id, "owner_id": owner.id}


def _tenant_admin(db: Session, user: User, tenant_id: int) -> Tenant:
    t = db.get(Tenant, tenant_id)
    role = tenant_role(db, user, tenant_id) if t else None
    if not t or role is None:
        raise HTTPException(404, "Empresa no encontrada")
    if role not in ("superadmin", "owner", "admin"):
        raise HTTPException(403, "Requiere rol administrador")
    return t


class TenantPatch(BaseModel):
    name: str | None = None
    timezone: str | None = None
    is_active: bool | None = None
    telegram_bot_token: str | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None


@router.get("/tenants/{tenant_id}")
def get_tenant(tenant_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    t = _tenant_admin(db, user, tenant_id)
    s = t.settings or {}
    return {"id": t.id, "name": t.name, "slug": t.slug, "timezone": t.timezone, "is_active": t.is_active,
            "telegram_configured": bool(s.get("telegram_bot_token")), "smtp_host": s.get("smtp_host", ""), "smtp_port": s.get("smtp_port", 587),
            "smtp_user": s.get("smtp_user", ""), "smtp_from": s.get("smtp_from", ""), "smtp_password_set": bool(s.get("smtp_password"))}


@router.patch("/tenants/{tenant_id}")
def patch_tenant(tenant_id: int, body: TenantPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    t = _tenant_admin(db, user, tenant_id)
    data = body.model_dump(exclude_unset=True)
    if "is_active" in data and not user.is_superadmin:
        raise HTTPException(403, "Sólo el superadministrador activa/desactiva empresas")
    for k in ("name", "timezone", "is_active"):
        if k in data:
            setattr(t, k, data.pop(k))
    t.settings = {**(t.settings or {}), **{k: v for k, v in data.items() if v is not None}}
    db.commit()
    return {"ok": True}


@router.post("/tenants/{tenant_id}/telegram/webhook")
def setup_telegram_webhook(tenant_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Registra en Telegram el webhook de esta empresa (cada empresa tiene su propio bot)."""
    t = _tenant_admin(db, user, tenant_id)
    client = get_client(t)
    if not client:
        raise HTTPException(422, "Primero guarda el token del bot (BotFather) en la empresa")
    secret = (t.settings or {}).get("telegram_webhook_secret")
    url = f"{get_settings().api_public_url.rstrip('/')}/api/telegram/webhook/{t.slug}/{secret}"
    client.set_webhook(url, secret)
    return {"webhook": url.replace(secret, "***")}


@router.get("/tenants/{tenant_id}/workspaces")
def list_workspaces(tenant_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _tenant_admin(db, user, tenant_id)
    return [{"id": w.id, "name": w.name, "slug": w.slug} for w in db.scalars(select(Workspace).where(Workspace.tenant_id == tenant_id))]


class WorkspaceIn(BaseModel):
    name: str


@router.post("/tenants/{tenant_id}/workspaces", status_code=201)
def create_workspace(tenant_id: int, body: WorkspaceIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    t = _tenant_admin(db, user, tenant_id)
    slug = slugify(body.name)
    if db.scalar(select(Workspace).where(Workspace.tenant_id == t.id, Workspace.slug == slug)):
        raise HTTPException(409, "Ya existe un espacio con ese nombre")
    ws = Workspace(tenant_id=t.id, name=body.name, slug=slug, settings={})
    db.add(ws)
    db.flush()
    seed_workspace(db, t, ws, user.id)
    db.commit()
    return {"id": ws.id, "name": ws.name, "slug": ws.slug}


class MemberIn(BaseModel):
    email: EmailStr
    name: str = ""
    password: str | None = None
    role: str = "member"  # owner | admin | member
    workspace_ids: list[int] = []


@router.get("/tenants/{tenant_id}/members")
def list_members(tenant_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _tenant_admin(db, user, tenant_id)
    out = []
    for m in db.scalars(select(Membership).where(Membership.tenant_id == tenant_id)):
        u = db.get(User, m.user_id)
        wids = [w.workspace_id for w in db.scalars(select(WorkspaceMember).where(WorkspaceMember.user_id == u.id))
                if db.get(Workspace, w.workspace_id).tenant_id == tenant_id]
        out.append({"user_id": u.id, "email": u.email, "name": u.name, "role": m.role, "workspace_ids": wids})
    return out


@router.post("/tenants/{tenant_id}/members", status_code=201)
def add_member(tenant_id: int, body: MemberIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    t = _tenant_admin(db, user, tenant_id)
    if body.role not in ("owner", "admin", "member"):
        raise HTTPException(422, "Rol inválido")
    u = db.scalar(select(User).where(User.email == body.email.lower()))
    if not u:
        if not body.password:
            raise HTTPException(422, "Falta contraseña para el usuario nuevo")
        u = User(email=body.email.lower(), name=body.name, password_hash=hash_password(body.password))
        db.add(u)
        db.flush()
    m = db.scalar(select(Membership).where(Membership.user_id == u.id, Membership.tenant_id == t.id))
    if m:
        m.role = body.role
    else:
        db.add(Membership(user_id=u.id, tenant_id=t.id, role=body.role))
    valid = {w.id for w in db.scalars(select(Workspace).where(Workspace.tenant_id == t.id))}
    for wid in body.workspace_ids:
        if wid not in valid:
            raise HTTPException(422, f"Espacio {wid} no pertenece a la empresa")
        if not db.scalar(select(WorkspaceMember).where(WorkspaceMember.workspace_id == wid, WorkspaceMember.user_id == u.id)):
            db.add(WorkspaceMember(workspace_id=wid, user_id=u.id))
    db.commit()
    return {"user_id": u.id}
