"""API de un espacio de trabajo: /api/w/{workspace_id}/...  Todo pasa por `scoped()` (aislamiento por tenant+workspace)."""
from __future__ import annotations

import secrets
from datetime import date, timedelta
from io import BytesIO

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..alerts.engine import evaluate_workspace, open_alerts_sorted, ws_settings
from ..alerts.rules import DEFAULT_RULES
from ..clock import Clock, get_clock
from ..dates_es import extract_dates
from ..db import get_db
from ..deps import Ctx, admin_ctx, get_owned, new_scoped, scoped, ws_ctx
from ..models import (Activity, Alert, AlertRule, Client, Contact, Holiday, ListItem, Meddpicc, Opportunity, Partner,
                      StageHistory, TelegramLink)
from ..services import excel as xl
from ..services import reports
from ..services.opportunities import (MEDDPICC_CRITERIA, BusinessError, create_opportunity, register_activity, set_meddpicc,
                                      update_opportunity)

router = APIRouter(prefix="/api/w/{workspace_id}")


def today_of(ctx: Ctx, clock: Clock) -> date:
    return clock.today(ctx.tenant.timezone)


def refresh(db: Session, ctx: Ctx, clock: Clock) -> None:
    """Re-evalúa alertas tras un cambio: las que ya no aplican se cierran solas."""
    evaluate_workspace(db, ctx.ws, today_of(ctx, clock), clock.now_utc())


# ------------------------------------------------------------------ serialización


def opp_dict(db: Session, o: Opportunity, info: dict, today: date) -> dict:
    st = info.get(o.stage)
    prob = st.prob if st and st.prob is not None else 0.0
    closed = bool(st and st.is_closed)
    dias = (o.fecha_prox_accion - today).days if o.fecha_prox_accion else None
    if closed:
        alerta = "Cerrada"
    elif not o.fecha_prox_accion or not o.prox_accion:
        alerta = "Sin acción" if not o.sin_proximo_paso_motivo else "Sin próximo paso (justificado)"
    else:
        alerta = "Vencida" if dias < 0 else "Esta semana" if dias <= 3 else "En tiempo"
    return {
        "id": o.id, "code": o.code, "tipo": o.tipo, "client_id": o.client_id, "client": o.client.name if o.client else "",
        "descripcion": o.descripcion, "sector": o.sector, "partner_id": o.partner_id, "partner": o.partner.name if o.partner else "",
        "distribuidor": o.distribuidor, "marca": o.marca, "monto": o.monto, "meddpicc_score": o.meddpicc_score, "stage": o.stage,
        "prob": prob, "monto_ponderado": (o.monto or 0) * prob, "prioridad": o.prioridad, "fecha_cierre_est": o.fecha_cierre_est,
        "prox_accion": o.prox_accion, "fecha_prox_accion": o.fecha_prox_accion, "sin_proximo_paso_motivo": o.sin_proximo_paso_motivo,
        "dias_para_accion": dias, "alerta": alerta, "responsable_id": o.responsable_id,
        "responsable": o.responsable.name if o.responsable else "", "ultima_actualizacion": o.ultima_actualizacion,
        "stage_entered_on": o.stage_entered_on, "comentarios": o.comentarios, "dr_vencimiento": o.dr_vencimiento,
        "contrato_vencimiento": o.contrato_vencimiento, "seace_proceso": o.seace_proceso, "seace_publicacion": o.seace_publicacion,
        "seace_buena_pro": o.seace_buena_pro, "seace_propuestas": o.seace_propuestas, "competidor": o.competidor,
        "is_closed": closed, "is_paused": bool(st and st.is_paused),
    }


def alert_dict(a: Alert) -> dict:
    return {"id": a.id, "rule": a.rule_code, "severity": a.severity, "title": a.title, "detail": a.detail, "opportunity_id": a.opportunity_id,
            "partner_id": a.partner_id, "snoozed_until": a.snoozed_until, "notify_count": a.notify_count, "escalated": a.escalated,
            "first_seen": a.first_seen, "read": a.read_at is not None, "status": a.status}


# ------------------------------------------------------------------ oportunidades


class OppIn(BaseModel):
    tipo: str = "DR"
    client_id: int | None = None
    descripcion: str = ""
    sector: str = ""
    partner_id: int | None = None
    distribuidor: str = ""
    marca: str = ""
    monto: float = 0
    stage: str = "Prospección"
    prioridad: str = "Media"
    fecha_cierre_est: date | None = None
    prox_accion: str = ""
    fecha_prox_accion: date | None = None
    sin_proximo_paso_motivo: str = ""
    responsable_id: int | None = None
    comentarios: str = ""
    dr_vencimiento: date | None = None
    contrato_vencimiento: date | None = None
    seace_proceso: str = ""
    seace_publicacion: date | None = None
    seace_buena_pro: date | None = None
    seace_propuestas: date | None = None
    competidor: str = ""


class OppPatch(OppIn):
    tipo: str | None = None  # type: ignore[assignment]
    monto: float | None = None  # type: ignore[assignment]
    stage: str | None = None  # type: ignore[assignment]
    prioridad: str | None = None  # type: ignore[assignment]


def _check_refs(db: Session, ctx: Ctx, data: dict) -> None:
    """Las referencias (cliente, partner, contacto) deben pertenecer al MISMO workspace."""
    for key, model in (("client_id", Client), ("partner_id", Partner), ("responsable_id", Contact)):
        if data.get(key) is not None:
            get_owned(db, model, data[key], ctx)


@router.get("/opportunities")
def list_opps(
    stage: str | None = None, partner_id: int | None = None, marca: str | None = None, sector: str | None = None,
    prioridad: str | None = None, alerta: str | None = None, q: str | None = None,
    ctx: Ctx = Depends(ws_ctx), db: Session = Depends(get_db), clock: Clock = Depends(get_clock),
):
    from ..services.seed import stage_info

    info, today = stage_info(db, ctx.ws.id), today_of(ctx, clock)
    qry = scoped(Opportunity, ctx).order_by(Opportunity.code)
    for col, val in ((Opportunity.stage, stage), (Opportunity.partner_id, partner_id), (Opportunity.marca, marca),
                     (Opportunity.sector, sector), (Opportunity.prioridad, prioridad)):
        if val is not None:
            qry = qry.where(col == val)
    rows = [opp_dict(db, o, info, today) for o in db.scalars(qry)]
    if alerta:
        rows = [r for r in rows if r["alerta"] == alerta]
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in f"{r['code']} {r['client']} {r['descripcion']} {r['partner']}".lower()]
    return rows


@router.post("/opportunities", status_code=201)
def create_opp(body: OppIn, ctx: Ctx = Depends(ws_ctx), db: Session = Depends(get_db), clock: Clock = Depends(get_clock)):
    from ..services.seed import stage_info

    data = body.model_dump()
    _check_refs(db, ctx, data)
    today = today_of(ctx, clock)
    o = create_opportunity(db, ctx, data, today)
    refresh(db, ctx, clock)
    db.commit()
    return opp_dict(db, o, stage_info(db, ctx.ws.id), today)


@router.get("/opportunities/{opp_id}")
def get_opp(opp_id: int, ctx: Ctx = Depends(ws_ctx), db: Session = Depends(get_db), clock: Clock = Depends(get_clock)):
    from ..services.seed import stage_info

    o = get_owned(db, Opportunity, opp_id, ctx)
    d = opp_dict(db, o, stage_info(db, ctx.ws.id), today_of(ctx, clock))
    d["activities"] = [activity_dict(a) for a in db.scalars(scoped(Activity, ctx).where(Activity.opportunity_id == o.id).order_by(Activity.fecha.desc(), Activity.id.desc()))]
    d["stage_history"] = [{"from": h.from_stage, "to": h.to_stage, "on": h.changed_on} for h in
                          db.scalars(scoped(StageHistory, ctx).where(StageHistory.opportunity_id == o.id).order_by(StageHistory.changed_on, StageHistory.id))]
    d["meddpicc"] = meddpicc_dict(db, ctx, o)
    d["alerts"] = [alert_dict(a) for a in db.scalars(scoped(Alert, ctx).where(Alert.opportunity_id == o.id, Alert.status == "open"))]
    return d


@router.patch("/opportunities/{opp_id}")
def patch_opp(opp_id: int, body: OppPatch, ctx: Ctx = Depends(ws_ctx), db: Session = Depends(get_db), clock: Clock = Depends(get_clock)):
    from ..services.seed import stage_info

    o = get_owned(db, Opportunity, opp_id, ctx)
    data = body.model_dump(exclude_unset=True)
    _check_refs(db, ctx, data)
    today = today_of(ctx, clock)
    update_opportunity(db, ctx, o, data, today)
    refresh(db, ctx, clock)
    db.commit()
    return opp_dict(db, o, stage_info(db, ctx.ws.id), today)


@router.delete("/opportunities/{opp_id}", status_code=204)
def delete_opp(opp_id: int, ctx: Ctx = Depends(admin_ctx), db: Session = Depends(get_db), clock: Clock = Depends(get_clock)):
    db.delete(get_owned(db, Opportunity, opp_id, ctx))
    db.flush()
    refresh(db, ctx, clock)
    db.commit()


# ------------------------------------------------------------------ MEDDPICC


def meddpicc_dict(db: Session, ctx: Ctx, o: Opportunity) -> dict:
    rows = {m.criterion: m for m in db.scalars(scoped(Meddpicc, ctx).where(Meddpicc.opportunity_id == o.id))}
    return {"score": o.meddpicc_score, "max": len(MEDDPICC_CRITERIA) * 2,
            "items": [{"criterion": c, "score": rows[c].score if c in rows else 0, "note": rows[c].note if c in rows else ""} for c in MEDDPICC_CRITERIA]}


class MeddpiccItem(BaseModel):
    criterion: str
    score: int
    note: str = ""


@router.put("/opportunities/{opp_id}/meddpicc")
def put_meddpicc(opp_id: int, items: list[MeddpiccItem], ctx: Ctx = Depends(ws_ctx), db: Session = Depends(get_db), clock: Clock = Depends(get_clock)):
    o = get_owned(db, Opportunity, opp_id, ctx)
    try:
        set_meddpicc(db, ctx, o, [i.model_dump() for i in items], today_of(ctx, clock))
    except BusinessError as ex:
        raise HTTPException(422, str(ex))
    refresh(db, ctx, clock)
    db.commit()
    return meddpicc_dict(db, ctx, o)


# ------------------------------------------------------------------ actividades


def activity_dict(a: Activity) -> dict:
    return {"id": a.id, "opportunity_id": a.opportunity_id, "fecha": a.fecha, "tipo": a.tipo, "contacto": a.contacto, "resumen": a.resumen,
            "proximo_paso": a.proximo_paso, "fecha_proximo_paso": a.fecha_proximo_paso, "source": a.source}


class ActivityIn(BaseModel):
    fecha: date | None = None
    tipo: str = "Llamada"
    contacto: str = ""
    contact_id: int | None = None
    resumen: str = ""
    proximo_paso: str = ""
    fecha_proximo_paso: date | None = None
    sin_proximo_paso_motivo: str = ""


@router.post("/opportunities/{opp_id}/activities", status_code=201)
def add_activity(opp_id: int, body: ActivityIn, ctx: Ctx = Depends(ws_ctx), db: Session = Depends(get_db), clock: Clock = Depends(get_clock)):
    """Registra una actividad. Exige próxima acción con fecha o 'sin próximo paso' con motivo.
    Devuelve además sugerencias de fecha detectadas en el texto (no se crean sin confirmar)."""
    o = get_owned(db, Opportunity, opp_id, ctx)
    if body.contact_id is not None:
        get_owned(db, Contact, body.contact_id, ctx)
    today = today_of(ctx, clock)
    try:
        a = register_activity(db, ctx, o, fecha=body.fecha or today, tipo=body.tipo, resumen=body.resumen, contacto=body.contacto,
                              contact_id=body.contact_id, proximo_paso=body.proximo_paso, fecha_proximo_paso=body.fecha_proximo_paso,
                              sin_proximo_paso_motivo=body.sin_proximo_paso_motivo, today=today)
    except BusinessError as ex:
        raise HTTPException(422, str(ex))
    refresh(db, ctx, clock)
    db.commit()
    return {"activity": activity_dict(a), "suggestions": suggest(body.resumen + " " + body.proximo_paso, today)}


class ActivityPatch(BaseModel):
    proximo_paso: str | None = None
    fecha_proximo_paso: date | None = None


@router.patch("/activities/{act_id}")
def patch_activity(act_id: int, body: ActivityPatch, ctx: Ctx = Depends(ws_ctx), db: Session = Depends(get_db), clock: Clock = Depends(get_clock)):
    a = get_owned(db, Activity, act_id, ctx)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(a, k, v)
    refresh(db, ctx, clock)
    db.commit()
    return activity_dict(a)


def suggest(text: str, today: date) -> list[dict]:
    return [{"fecha": s.fecha, "texto": s.texto} for s in extract_dates(text, today)]


class TextIn(BaseModel):
    text: str


@router.post("/suggest-dates")
def suggest_dates(body: TextIn, ctx: Ctx = Depends(ws_ctx), clock: Clock = Depends(get_clock)):
    return suggest(body.text, today_of(ctx, clock))


@router.get("/activities")
def list_activities(limit: int = 100, ctx: Ctx = Depends(ws_ctx), db: Session = Depends(get_db)):
    return [activity_dict(a) for a in db.scalars(scoped(Activity, ctx).order_by(Activity.fecha.desc(), Activity.id.desc()).limit(limit))]


# ------------------------------------------------------------------ clientes / partners / contactos (CRUD)


class NameIn(BaseModel):
    name: str
    sector: str = ""
    notes: str = ""


def _simple_crud(path: str, model, fields: list[str]):
    def to_dict(x):
        return {"id": x.id, **{f: getattr(x, f) for f in fields}}

    @router.get(f"/{path}", name=f"list_{path}")
    def _list(ctx: Ctx = Depends(ws_ctx), db: Session = Depends(get_db)):
        return [to_dict(x) for x in db.scalars(scoped(model, ctx).order_by(model.id))]

    @router.post(f"/{path}", status_code=201, name=f"create_{path}")
    def _create(body: dict, ctx: Ctx = Depends(ws_ctx), db: Session = Depends(get_db)):
        data = {k: v for k, v in body.items() if k in fields}
        if "client_id" in data and data["client_id"] is not None:
            get_owned(db, Client, data["client_id"], ctx)
        if "partner_id" in data and data["partner_id"] is not None:
            get_owned(db, Partner, data["partner_id"], ctx)
        x = new_scoped(model, ctx, **data)
        db.add(x)
        db.commit()
        return to_dict(x)

    @router.patch(f"/{path}/{{item_id}}", name=f"patch_{path}")
    def _patch(item_id: int, body: dict, ctx: Ctx = Depends(ws_ctx), db: Session = Depends(get_db)):
        x = get_owned(db, model, item_id, ctx)
        for k, v in body.items():
            if k in fields:
                if k in ("client_id", "partner_id") and v is not None:
                    get_owned(db, Client if k == "client_id" else Partner, v, ctx)
                setattr(x, k, v)
        db.commit()
        return to_dict(x)

    @router.delete(f"/{path}/{{item_id}}", status_code=204, name=f"delete_{path}")
    def _delete(item_id: int, ctx: Ctx = Depends(admin_ctx), db: Session = Depends(get_db)):
        db.delete(get_owned(db, model, item_id, ctx))
        db.commit()


_simple_crud("clients", Client, ["name", "sector"])
_simple_crud("partners", Partner, ["name", "notes"])
_simple_crud("contacts", Contact, ["name", "kind", "client_id", "partner_id", "cargo", "email", "phone"])


# ------------------------------------------------------------------ catálogos, reglas, feriados, ajustes


@router.get("/catalogs")
def catalogs(ctx: Ctx = Depends(ws_ctx), db: Session = Depends(get_db)):
    out: dict[str, list] = {}
    for it in db.scalars(scoped(ListItem, ctx).order_by(ListItem.kind, ListItem.sort, ListItem.id)):
        out.setdefault(it.kind, []).append({"id": it.id, "value": it.value, "prob": it.prob, "is_closed": it.is_closed, "is_won": it.is_won, "is_paused": it.is_paused})
    return out


class CatalogIn(BaseModel):
    kind: str
    value: str
    prob: float | None = None
    is_closed: bool = False
    is_won: bool = False
    is_paused: bool = False


@router.post("/catalogs", status_code=201)
def add_catalog(body: CatalogIn, ctx: Ctx = Depends(admin_ctx), db: Session = Depends(get_db)):
    if db.scalar(scoped(ListItem, ctx).where(ListItem.kind == body.kind, ListItem.value == body.value)):
        raise HTTPException(409, "Ya existe")
    it = new_scoped(ListItem, ctx, **body.model_dump(), sort=99)
    db.add(it)
    db.commit()
    return {"id": it.id}


@router.patch("/catalogs/{item_id}")
def patch_catalog(item_id: int, body: dict, ctx: Ctx = Depends(admin_ctx), db: Session = Depends(get_db), clock: Clock = Depends(get_clock)):
    it = get_owned(db, ListItem, item_id, ctx)
    for k in ("value", "prob", "is_closed", "is_won", "is_paused"):
        if k in body:
            setattr(it, k, body[k])
    refresh(db, ctx, clock)
    db.commit()
    return {"ok": True}


@router.delete("/catalogs/{item_id}", status_code=204)
def delete_catalog(item_id: int, ctx: Ctx = Depends(admin_ctx), db: Session = Depends(get_db)):
    db.delete(get_owned(db, ListItem, item_id, ctx))
    db.commit()


@router.get("/rules")
def get_rules(ctx: Ctx = Depends(ws_ctx), db: Session = Depends(get_db)):
    return [{"code": r.code, "name": DEFAULT_RULES.get(r.code, {}).get("name", r.code), "enabled": r.enabled, "severity": r.severity, "params": r.params}
            for r in db.scalars(scoped(AlertRule, ctx))]


class RulePatch(BaseModel):
    enabled: bool | None = None
    severity: str | None = None
    params: dict | None = None


@router.patch("/rules/{code}")
def patch_rule(code: str, body: RulePatch, ctx: Ctx = Depends(admin_ctx), db: Session = Depends(get_db), clock: Clock = Depends(get_clock)):
    r = db.scalar(scoped(AlertRule, ctx).where(AlertRule.code == code))
    if not r:
        raise HTTPException(404, "Regla no encontrada")
    if body.severity and body.severity not in ("Alta", "Media", "Baja"):
        raise HTTPException(422, "Severidad inválida")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(r, k, v)
    refresh(db, ctx, clock)
    db.commit()
    return {"ok": True}


@router.get("/holidays")
def holidays(ctx: Ctx = Depends(ws_ctx), db: Session = Depends(get_db)):
    return [{"id": h.id, "fecha": h.fecha, "nombre": h.nombre} for h in db.scalars(scoped(Holiday, ctx).order_by(Holiday.fecha))]


class HolidayIn(BaseModel):
    fecha: date
    nombre: str = ""


@router.post("/holidays", status_code=201)
def add_holiday(body: HolidayIn, ctx: Ctx = Depends(admin_ctx), db: Session = Depends(get_db)):
    if db.scalar(scoped(Holiday, ctx).where(Holiday.fecha == body.fecha)):
        raise HTTPException(409, "Ya existe")
    h = new_scoped(Holiday, ctx, **body.model_dump())
    db.add(h)
    db.commit()
    return {"id": h.id}


@router.delete("/holidays/{hid}", status_code=204)
def del_holiday(hid: int, ctx: Ctx = Depends(admin_ctx), db: Session = Depends(get_db)):
    db.delete(get_owned(db, Holiday, hid, ctx))
    db.commit()


SETTINGS_EDITABLE = {"work_days", "work_start", "work_end", "digest_time", "weekly_time", "repeat_alta_days", "repeat_media_days",
                     "escalate_after", "digest_on_non_business_days", "email_to"}


@router.get("/settings")
def get_settings_(ctx: Ctx = Depends(ws_ctx)):
    st = ws_settings(ctx.ws)
    return {k: st[k] for k in SETTINGS_EDITABLE}


@router.patch("/settings")
def patch_settings(body: dict, ctx: Ctx = Depends(admin_ctx), db: Session = Depends(get_db)):
    ctx.ws.settings = {**ws_settings(ctx.ws), **{k: v for k, v in body.items() if k in SETTINGS_EDITABLE}}
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ alertas / bandeja in-app


@router.get("/alerts")
def list_alerts(include_snoozed: bool = False, ctx: Ctx = Depends(ws_ctx), db: Session = Depends(get_db), clock: Clock = Depends(get_clock)):
    rows = open_alerts_sorted(db, ctx.ws.id, today_of(ctx, clock), include_snoozed=include_snoozed)
    return {"count": len(rows), "unread": sum(1 for a in rows if not a.read_at), "alerts": [alert_dict(a) for a in rows]}


@router.post("/alerts/refresh")
def refresh_alerts(ctx: Ctx = Depends(ws_ctx), db: Session = Depends(get_db), clock: Clock = Depends(get_clock)):
    st = evaluate_workspace(db, ctx.ws, today_of(ctx, clock), clock.now_utc())
    db.commit()
    return st.as_dict()


class SnoozeIn(BaseModel):
    days: int | None = None
    until: date | None = None


@router.post("/alerts/{alert_id}/snooze")
def snooze(alert_id: int, body: SnoozeIn, ctx: Ctx = Depends(ws_ctx), db: Session = Depends(get_db), clock: Clock = Depends(get_clock)):
    a = get_owned(db, Alert, alert_id, ctx)
    if body.until:
        a.snoozed_until = body.until
    elif body.days:
        a.snoozed_until = today_of(ctx, clock) + timedelta(days=body.days)
    else:
        raise HTTPException(422, "Indica days o until")
    db.commit()
    return alert_dict(a)


@router.post("/alerts/{alert_id}/read")
def mark_read(alert_id: int, ctx: Ctx = Depends(ws_ctx), db: Session = Depends(get_db), clock: Clock = Depends(get_clock)):
    a = get_owned(db, Alert, alert_id, ctx)
    a.read_at = clock.now_utc()
    db.commit()
    return alert_dict(a)


@router.post("/alerts/read-all")
def read_all(ctx: Ctx = Depends(ws_ctx), db: Session = Depends(get_db), clock: Clock = Depends(get_clock)):
    for a in db.scalars(scoped(Alert, ctx).where(Alert.status == "open", Alert.read_at.is_(None))):
        a.read_at = clock.now_utc()
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ dashboard, excel, telegram


@router.get("/dashboard")
def dashboard(ctx: Ctx = Depends(ws_ctx), db: Session = Depends(get_db), clock: Clock = Depends(get_clock)):
    return reports.dashboard(db, ctx.ws, today_of(ctx, clock))


@router.post("/import/excel")
async def import_excel(file: UploadFile = File(...), ctx: Ctx = Depends(admin_ctx), db: Session = Depends(get_db), clock: Clock = Depends(get_clock)):
    today = today_of(ctx, clock)
    try:
        res = xl.import_excel(db, ctx, BytesIO(await file.read()), today)
    except ValueError as ex:
        raise HTTPException(422, str(ex))
    refresh(db, ctx, clock)
    report = xl.quality_report(db, ctx, today)
    db.commit()
    return {"result": res.__dict__, "quality": report}


@router.get("/quality-report")
def quality(ctx: Ctx = Depends(ws_ctx), db: Session = Depends(get_db), clock: Clock = Depends(get_clock)):
    return xl.quality_report(db, ctx, today_of(ctx, clock))


@router.get("/export/excel")
def export_excel(ctx: Ctx = Depends(ws_ctx), db: Session = Depends(get_db), clock: Clock = Depends(get_clock)):
    data = xl.export_excel(db, ctx, today_of(ctx, clock))
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="pipeline_{ctx.tenant.slug}_{ctx.ws.slug}.xlsx"'})


@router.post("/telegram/link-code")
def telegram_link_code(ctx: Ctx = Depends(ws_ctx), db: Session = Depends(get_db)):
    """Código de un solo uso para vincular el chat de Telegram: enviar `/start CODIGO` al bot de la empresa."""
    for old in db.scalars(select(TelegramLink).where(TelegramLink.workspace_id == ctx.ws.id, TelegramLink.user_id == ctx.user.id, TelegramLink.chat_id.is_(None))):
        db.delete(old)
    code = secrets.token_hex(4).upper()
    db.add(TelegramLink(tenant_id=ctx.tenant.id, workspace_id=ctx.ws.id, user_id=ctx.user.id, link_code=code, state={}))
    db.commit()
    return {"code": code, "instruccion": f"Envía /start {code} a tu bot de Telegram"}


@router.get("/telegram/status")
def telegram_status(ctx: Ctx = Depends(ws_ctx), db: Session = Depends(get_db)):
    link = db.scalar(select(TelegramLink).where(TelegramLink.workspace_id == ctx.ws.id, TelegramLink.user_id == ctx.user.id, TelegramLink.chat_id.is_not(None)))
    return {"linked": bool(link), "bot_configured": bool((ctx.tenant.settings or {}).get("telegram_bot_token"))}
