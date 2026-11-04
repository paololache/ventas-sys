"""Dependencias FastAPI: autenticación y contexto de tenant/workspace.

Regla de oro del aislamiento: *toda* consulta de datos comerciales pasa por `scoped()` / `get_owned()`,
que filtran por `tenant_id` y `workspace_id` del contexto autenticado.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import Membership, Tenant, User, Workspace, WorkspaceMember
from .security import decode_token


def current_user(authorization: str = Header(default=""), db: Session = Depends(get_db)) -> User:
    token = authorization.removeprefix("Bearer ").strip()
    uid = decode_token(token) if token else None
    user = db.get(User, uid) if uid else None
    if not user or not user.is_active:
        raise HTTPException(401, "No autenticado")
    return user


def require_superadmin(user: User = Depends(current_user)) -> User:
    if not user.is_superadmin:
        raise HTTPException(403, "Requiere superadministrador de la plataforma")
    return user


@dataclass
class Ctx:
    user: User
    tenant: Tenant
    ws: Workspace
    role: str  # superadmin | owner | admin | member

    @property
    def is_admin(self) -> bool:
        return self.role in ("superadmin", "owner", "admin")


def tenant_role(db: Session, user: User, tenant_id: int) -> str | None:
    if user.is_superadmin:
        return "superadmin"
    m = db.scalar(select(Membership).where(Membership.user_id == user.id, Membership.tenant_id == tenant_id))
    return m.role if m else None


def ws_ctx(workspace_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Ctx:
    ws = db.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(404, "Espacio de trabajo no encontrado")
    role = tenant_role(db, user, ws.tenant_id)
    if role is None:
        raise HTTPException(404, "Espacio de trabajo no encontrado")  # no revelar existencia
    if role == "member":
        ok = db.scalar(select(WorkspaceMember).where(WorkspaceMember.workspace_id == ws.id, WorkspaceMember.user_id == user.id))
        if not ok:
            raise HTTPException(404, "Espacio de trabajo no encontrado")
    tenant = db.get(Tenant, ws.tenant_id)
    if not tenant.is_active:
        raise HTTPException(403, "Empresa desactivada")
    return Ctx(user, tenant, ws, role)


def admin_ctx(ctx: Ctx = Depends(ws_ctx)) -> Ctx:
    if not ctx.is_admin:
        raise HTTPException(403, "Requiere rol administrador")
    return ctx


def scoped(model, ctx: Ctx):
    return select(model).where(model.tenant_id == ctx.tenant.id, model.workspace_id == ctx.ws.id)


def get_owned(db: Session, model, obj_id: int, ctx: Ctx):
    obj = db.scalar(scoped(model, ctx).where(model.id == obj_id))
    if not obj:
        raise HTTPException(404, f"{model.__name__} no encontrado")
    return obj


def new_scoped(model, ctx: Ctx, **kw):
    return model(tenant_id=ctx.tenant.id, workspace_id=ctx.ws.id, owner_id=kw.pop("owner_id", ctx.user.id), **kw)
