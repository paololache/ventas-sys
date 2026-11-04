"""Orquesta las reglas puras contra la base: construye vistas, deduplica, escala y auto-resuelve."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Activity, Alert, AlertRule, Client, Contact, Holiday, Opportunity, Partner, Workspace
from ..services.opportunities import stage_durations
from ..services.seed import DEFAULT_WS_SETTINGS, stage_info
from . import rules as R

log = logging.getLogger("crm.alerts")

PRIO_RANK = R.PRIO_ORDER


@dataclass
class EvalStats:
    rules_evaluated: int = 0
    candidates: int = 0
    created: int = 0
    deduplicated: int = 0
    resolved: int = 0
    reopened_after_snooze: int = 0
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if k != "extra"} | self.extra


def ws_settings(ws: Workspace) -> dict:
    return {**DEFAULT_WS_SETTINGS, **(ws.settings or {})}


def load_holidays(db: Session, ws_id: int) -> frozenset[date]:
    return frozenset(db.scalars(select(Holiday.fecha).where(Holiday.workspace_id == ws_id)).all())


def load_rule_cfgs(db: Session, ws_id: int) -> dict[str, R.RuleCfg]:
    cfgs = R.default_cfgs()
    for r in db.scalars(select(AlertRule).where(AlertRule.workspace_id == ws_id)):
        cfgs[r.code] = R.RuleCfg(r.enabled, r.severity, r.params or R.DEFAULT_RULES.get(r.code, {}).get("params", {}))
    return cfgs


def build_views(db: Session, ws: Workspace, today: date):
    stages = stage_info(db, ws.id)
    opps = db.scalars(select(Opportunity).where(Opportunity.workspace_id == ws.id)).all()
    clients = {c.id: c.name for c in db.scalars(select(Client).where(Client.workspace_id == ws.id))}
    # contacto "con contacto" = responsable asignado o algún contacto del cliente
    clients_with_contact = set(db.scalars(select(Contact.client_id).where(Contact.workspace_id == ws.id, Contact.client_id.is_not(None))))
    views: dict[int, R.OppView] = {}
    for o in opps:
        st = stages.get(o.stage)
        views[o.id] = R.OppView(
            id=o.id, code=o.code, cliente=clients.get(o.client_id, ""), descripcion=o.descripcion, tipo=o.tipo,
            stage=o.stage, is_open=not (st.is_closed if st else False), is_paused=bool(st.is_paused) if st else False,
            prioridad=o.prioridad, monto=o.monto or 0.0, fecha_cierre_est=o.fecha_cierre_est, prox_accion=o.prox_accion or "",
            fecha_prox_accion=o.fecha_prox_accion, sin_proximo_paso_motivo=o.sin_proximo_paso_motivo or "",
            ultima_actualizacion=o.ultima_actualizacion, stage_entered_on=o.stage_entered_on,
            dr_vencimiento=o.dr_vencimiento, contrato_vencimiento=o.contrato_vencimiento,
            seace_publicacion=o.seace_publicacion, seace_buena_pro=o.seace_buena_pro, seace_propuestas=o.seace_propuestas,
            meddpicc_score=o.meddpicc_score or 0,
            has_contact=bool(o.responsable_id or (o.client_id in clients_with_contact)),
            partner_id=o.partner_id, owner_id=o.owner_id,
        )
    acts = [R.ActivityView(a.id, a.opportunity_id, a.fecha, a.proximo_paso or "", a.fecha_proximo_paso)
            for a in db.scalars(select(Activity).where(Activity.workspace_id == ws.id))]
    last_act: dict[int, date] = {}
    opp_partner = {o.id: o.partner_id for o in opps}
    for a in acts:
        pid = opp_partner.get(a.opportunity_id)
        if pid and (pid not in last_act or a.fecha > last_act[pid]):
            last_act[pid] = a.fecha
    partners = []
    for p in db.scalars(select(Partner).where(Partner.workspace_id == ws.id)):
        open_ops = [views[o.id] for o in opps if o.partner_id == p.id and views[o.id].is_open and not views[o.id].is_paused]
        upd = [v.ultima_actualizacion for v in open_ops if v.ultima_actualizacion]
        partners.append(R.PartnerView(p.id, p.name, len(open_ops), last_act.get(p.id), min(upd) if upd else None, p.owner_id))
    return views, acts, partners


def compute_candidates(db: Session, ws: Workspace, today: date) -> tuple[list[R.Candidate], int]:
    """Evalúa todas las reglas (sin escribir). Devuelve (candidatas, reglas_evaluadas)."""
    st = ws_settings(ws)
    durs = stage_durations(db, ws.id, today)
    ctx = R.EvalCtx(
        today=today, holidays=load_holidays(db, ws.id), work_days=tuple(st["work_days"]), rules=load_rule_cfgs(db, ws.id),
        stage_avg_days={k: (sum(v) / len(v), len(v)) for k, v in durs.items() if v},
    )
    views, acts, partners = build_views(db, ws, today)
    cands: list[R.Candidate] = []
    for v in views.values():
        cands.extend(R.evaluate_opportunity(v, ctx))
    cands.extend(R.r10_paso_huerfano(acts, views, ctx))
    cands.extend(R.r12_partner_silencioso(partners, ctx))
    enabled = sum(1 for c in ctx.rules.values() if c.enabled)
    return cands, enabled


def evaluate_workspace(db: Session, ws: Workspace, today: date, now: datetime) -> EvalStats:
    """Sincroniza la tabla `alerts` con el estado actual:

    - nuevas → se crean; existentes → se actualizan (dedupe, sin reenviar);
    - las que ya no aplican → se resuelven solas.
    """
    stats = EvalStats()
    cands, stats.rules_evaluated = compute_candidates(db, ws, today)
    stats.candidates = len(cands)
    open_alerts = {a.dedupe_key: a for a in db.scalars(select(Alert).where(Alert.workspace_id == ws.id, Alert.status == "open"))}
    seen: set[str] = set()
    tenant_id = ws.tenant_id
    for c in cands:
        seen.add(c.key)
        a = open_alerts.get(c.key)
        if a is None:
            db.add(Alert(
                tenant_id=tenant_id, workspace_id=ws.id, owner_id=c.owner_id, rule_code=c.rule, dedupe_key=c.key,
                opportunity_id=c.opp_id, partner_id=c.partner_id, activity_id=c.activity_id,
                base_severity=c.severity, urgent=c.urgent, title=c.title, detail=c.detail,
                sort_prioridad=PRIO_RANK.get(c.prioridad, 1), sort_monto=c.monto, first_seen=now,
            ))
            stats.created += 1
        else:
            stats.deduplicated += 1
            a.title, a.detail, a.base_severity, a.urgent = c.title, c.detail, c.severity, c.urgent
            a.sort_prioridad, a.sort_monto, a.owner_id = PRIO_RANK.get(c.prioridad, 1), c.monto, c.owner_id
    for key, a in open_alerts.items():
        if key not in seen:
            a.status, a.resolved_at, a.resolved_reason = "resolved", now, "ya no aplica"
            stats.resolved += 1
    db.flush()
    log.info("alert_eval workspace=%s %s", ws.id, stats.as_dict())
    return stats


def open_alerts_sorted(db: Session, ws_id: int, today: date, owner_id: int | None = None, include_snoozed=False) -> list[Alert]:
    q = select(Alert).where(Alert.workspace_id == ws_id, Alert.status == "open")
    if owner_id is not None:
        q = q.where((Alert.owner_id == owner_id) | (Alert.owner_id.is_(None)))
    rows = db.scalars(q).all()
    if not include_snoozed:
        rows = [a for a in rows if not a.snoozed_until or a.snoozed_until < today]
    return sorted(rows, key=lambda a: (R.SEV_ORDER[a.severity], a.sort_prioridad, -a.sort_monto, a.id))


def count_open(db: Session, ws_id: int) -> int:
    return db.scalar(select(func.count()).select_from(Alert).where(Alert.workspace_id == ws_id, Alert.status == "open")) or 0
