"""Tick del scheduler: corre cada N minutos y decide, por tenant (hora local propia), qué toca enviar."""
from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..alerts.engine import evaluate_workspace, ws_settings
from ..clock import Clock, get_clock
from ..models import SchedulerRun, Tenant, Workspace
from . import notify

log = logging.getLogger("crm.scheduler")


def run_workspace(db: Session, tenant: Tenant, ws: Workspace, clock: Clock) -> dict:
    today, now = clock.today(tenant.timezone), clock.now_utc()
    ev = evaluate_workspace(db, ws, today, now)
    stats = {"rules_evaluated": ev.rules_evaluated, "created": ev.created, "deduplicated": ev.deduplicated, "resolved": ev.resolved}
    daily, weekly = notify.digests_due(db, tenant, ws, clock)
    if daily:
        stats.update(notify.send_daily_digest(db, tenant, ws, clock))
        ws.settings = {**ws_settings(ws), "last_digest_date": today.isoformat()}
    stats.update(notify.deliver_due_alerts(db, tenant, ws, clock))
    if weekly:
        stats.update(notify.send_weekly_digest(db, tenant, ws, clock))
        iso = today.isocalendar()
        ws.settings = {**ws_settings(ws), "last_weekly_week": f"{iso.year}-W{iso.week:02d}"}
    db.add(SchedulerRun(workspace_id=ws.id, ran_at=now, stats=stats))
    log.info("scheduler_run %s", json.dumps({"tenant": tenant.slug, "workspace": ws.id, **stats}))
    return stats


def run_tick(db: Session, clock: Clock | None = None) -> dict[int, dict]:
    clock = clock or get_clock()
    out = {}
    for tenant in db.scalars(select(Tenant).where(Tenant.is_active)):
        for ws in db.scalars(select(Workspace).where(Workspace.tenant_id == tenant.id)):
            try:
                out[ws.id] = run_workspace(db, tenant, ws, clock)
                db.commit()
            except Exception:
                db.rollback()
                log.exception("scheduler_failed tenant=%s workspace=%s", tenant.slug, ws.id)
    return out
