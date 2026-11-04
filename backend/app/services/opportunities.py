"""Lógica de negocio sobre oportunidades y actividades (independiente de HTTP)."""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..deps import Ctx, scoped
from ..models import Activity, Meddpicc, Opportunity, StageHistory
from .seed import stage_info

MEDDPICC_CRITERIA = [
    "Metrics", "Economic buyer", "Decision criteria", "Decision process",
    "Paper process", "Identify pain", "Champion", "Competition",
]
# Cambios "relevantes" que refrescan `ultima_actualizacion`
RELEVANT_FIELDS = {"stage", "monto", "fecha_cierre_est", "prox_accion", "fecha_prox_accion"}


class BusinessError(Exception):
    """Regla de negocio incumplida (HTTP 422)."""


def next_code(db: Session, ctx_ws_id: int) -> str:
    codes = db.scalars(select(Opportunity.code).where(Opportunity.workspace_id == ctx_ws_id)).all()
    nums = [int(c.split("-")[1]) for c in codes if c.startswith("OP-") and c.split("-")[1].isdigit()]
    return f"OP-{(max(nums) + 1 if nums else 1):03d}"


def is_open_stage(db: Session, ws_id: int, stage: str) -> tuple[bool, bool]:
    """(abierta, en_pausa). Una etapa desconocida se considera abierta."""
    info = stage_info(db, ws_id).get(stage)
    if not info:
        return True, False
    return (not info.is_closed), info.is_paused


def record_stage(db: Session, ctx: Ctx, opp: Opportunity, new: str, frm: str | None, today: date) -> None:
    db.add(StageHistory(tenant_id=ctx.tenant.id, workspace_id=ctx.ws.id, owner_id=opp.owner_id,
                        opportunity_id=opp.id, from_stage=frm, to_stage=new, changed_on=today))
    opp.stage_entered_on = today


def create_opportunity(db: Session, ctx: Ctx, data: dict, today: date) -> Opportunity:
    data = dict(data)
    code = data.pop("code", None) or next_code(db, ctx.ws.id)
    opp = Opportunity(tenant_id=ctx.tenant.id, workspace_id=ctx.ws.id, owner_id=data.pop("owner_id", ctx.user.id), code=code, **data)
    opp.ultima_actualizacion = today
    db.add(opp)
    db.flush()
    record_stage(db, ctx, opp, opp.stage, None, today)
    return opp


def update_opportunity(db: Session, ctx: Ctx, opp: Opportunity, changes: dict, today: date) -> Opportunity:
    relevant = False
    for k, v in changes.items():
        old = getattr(opp, k)
        if old == v:
            continue
        if k == "stage":
            record_stage(db, ctx, opp, v, old, today)
        if k in RELEVANT_FIELDS:
            relevant = True
        setattr(opp, k, v)
    # Definir una próxima acción con fecha anula el "sin próximo paso" explícito
    if opp.prox_accion.strip() and opp.fecha_prox_accion:
        opp.sin_proximo_paso_motivo = ""
    if relevant:
        opp.ultima_actualizacion = today
    db.flush()
    return opp


def register_activity(
    db: Session, ctx: Ctx, opp: Opportunity, *, fecha: date, tipo: str, resumen: str, contacto: str = "",
    contact_id: int | None = None, proximo_paso: str = "", fecha_proximo_paso: date | None = None,
    sin_proximo_paso_motivo: str = "", source: str = "app", require_next: bool = True, today: date | None = None,
) -> Activity:
    """Registra una actividad.

    - Refresca `ultima_actualizacion`.
    - Cierra la acción pendiente (si ya era exigible) y obliga a definir la siguiente, o a marcar
      explícitamente "sin próximo paso" con un motivo.
    """
    has_next = bool(proximo_paso.strip() and fecha_proximo_paso)
    if require_next and not has_next and not sin_proximo_paso_motivo.strip():
        raise BusinessError("Define la próxima acción con fecha, o indica el motivo de 'sin próximo paso'.")
    ref = today or fecha
    act = Activity(tenant_id=ctx.tenant.id, workspace_id=ctx.ws.id, owner_id=ctx.user.id, opportunity_id=opp.id,
                   fecha=fecha, tipo=tipo, contacto=contacto, contact_id=contact_id, resumen=resumen,
                   proximo_paso=proximo_paso, fecha_proximo_paso=fecha_proximo_paso, source=source)
    db.add(act)
    # cerrar acción pendiente exigible (vencida o de hoy) o reemplazarla por la nueva
    if has_next:
        opp.prox_accion, opp.fecha_prox_accion, opp.sin_proximo_paso_motivo = proximo_paso, fecha_proximo_paso, ""
    else:
        if opp.fecha_prox_accion and opp.fecha_prox_accion <= ref:
            opp.prox_accion, opp.fecha_prox_accion = "", None
        if sin_proximo_paso_motivo.strip():
            opp.sin_proximo_paso_motivo = sin_proximo_paso_motivo.strip()
    opp.ultima_actualizacion = ref  # registrar una actividad siempre es tocar la oportunidad
    db.flush()
    return act


def set_meddpicc(db: Session, ctx: Ctx, opp: Opportunity, items: list[dict], today: date) -> int:
    existing = {m.criterion: m for m in db.scalars(select(Meddpicc).where(Meddpicc.opportunity_id == opp.id))}
    for it in items:
        crit = it["criterion"]
        if crit not in MEDDPICC_CRITERIA:
            raise BusinessError(f"Criterio MEDDPICC desconocido: {crit}")
        score = int(it["score"])
        if not 0 <= score <= 2:
            raise BusinessError("El puntaje MEDDPICC va de 0 a 2.")
        m = existing.get(crit)
        if m is None:
            m = Meddpicc(tenant_id=ctx.tenant.id, workspace_id=ctx.ws.id, owner_id=opp.owner_id,
                         opportunity_id=opp.id, criterion=crit)
            db.add(m)
            existing[crit] = m
        m.score, m.note = score, it.get("note", "")
    db.flush()
    opp.meddpicc_score = sum(m.score for m in existing.values())
    opp.ultima_actualizacion = today
    return opp.meddpicc_score


def stage_durations(db: Session, ws_id: int, today: date) -> dict[str, list[int]]:
    """Duración (días) de cada permanencia COMPLETADA en una etapa, a partir del historial."""
    rows = db.execute(
        select(StageHistory.opportunity_id, StageHistory.to_stage, StageHistory.changed_on)
        .where(StageHistory.workspace_id == ws_id).order_by(StageHistory.opportunity_id, StageHistory.changed_on, StageHistory.id)
    ).all()
    out: dict[str, list[int]] = {}
    prev = None
    for opp_id, stage, d in rows:
        if prev and prev[0] == opp_id:
            out.setdefault(prev[1], []).append((d - prev[2]).days)
        prev = (opp_id, stage, d)
    return out


def activity_count(db: Session, ctx: Ctx) -> int:
    return db.scalar(select(func.count()).select_from(scoped(Activity, ctx).subquery()))
