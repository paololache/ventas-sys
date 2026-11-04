"""Entrega de notificaciones: alertas puntuales agrupadas, resumen diario (Telegram) y semanal (email).

Reglas de entrega:
- Una alerta se re-avisa según severidad (Alta: diario; Media: cada 3 días; configurable). Baja sólo va en el resumen semanal.
- Media que acumula `escalate_after` avisos sin atenderse escala a Alta.
- Fuera de horario laboral (L-V 8–19 por defecto, sin feriados) sólo salen Alta con fecha de hoy ("urgent").
- Las alertas se envían AGRUPADAS por regla (nunca 25 mensajes sueltos), ordenadas por prioridad y monto.
- Snooze vigente = no se notifica.
"""
from __future__ import annotations

import html
import logging
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..alerts import rules as R
from ..alerts.engine import load_holidays, open_alerts_sorted, ws_settings
from ..calendar_util import first_business_day_of_week, is_business_day, is_work_time, parse_hhmm
from ..channels import registry
from ..channels.base import Button, Message, Target
from ..config import get_settings
from ..models import Alert, Opportunity, TelegramLink, Tenant, User, Workspace, WorkspaceMember, Membership
from . import reports
from ..clock import Clock
from datetime import time

log = logging.getLogger("crm.notify")
e = html.escape
SEV_ICON = {"Alta": "🔴", "Media": "🟠", "Baja": "⚪"}
MAX_LINES = 12


def app_url(ws: Workspace, path: str = "") -> str:
    return f"{get_settings().public_url.rstrip('/')}/w/{ws.id}{path}"


def _line(a: Alert) -> str:
    return f"{SEV_ICON[a.severity]} {e(a.title)}" + (f"\n    <i>{e(a.detail)}</i>" if a.detail else "")


def alert_buttons(ws: Workspace, a: Alert) -> list[list[Button]]:
    row = [Button("✅ Hecho", f"done:{a.id}"), Button("⏰ Posponer", f"snzm:{a.id}")]
    row2 = [Button("📞 Ver contacto", f"ct:{a.id}"), Button("🔗 Abrir en la app", url=app_url(ws, f"/opportunities/{a.opportunity_id}" if a.opportunity_id else "/alerts"))]
    return [row, row2]


def group_message(ws: Workspace, rule_code: str, rule_name: str, alerts: list[Alert]) -> Message:
    n = len(alerts)
    head = f"<b>{SEV_ICON[alerts[0].severity]} {e(rule_name)}</b> · {n} alerta{'s' if n != 1 else ''}"
    if n == 1:
        a = alerts[0]
        return Message(f"{head}\n\n{_line(a)}", alert_buttons(ws, a), subject=rule_name)
    lines = [f"{i}. {_line(a)}" for i, a in enumerate(alerts[:MAX_LINES], 1)]
    if n > MAX_LINES:
        lines.append(f"… y {n - MAX_LINES} más (ver bandeja en la app)")
    buttons = [[Button(f"✅ {i}", f"done:{a.id}"), Button(f"⏰ {i}", f"snzm:{a.id}")] for i, a in list(enumerate(alerts, 1))[:4]]
    buttons.append([Button("🔗 Abrir bandeja", url=app_url(ws, "/alerts"))])
    return Message(head + "\n\n" + "\n".join(lines) + "\n\n<i>Ordenadas por prioridad y monto.</i>", buttons, subject=rule_name)


# ------------------------------------------------------------------ destinatarios


def targets_for(db: Session, tenant: Tenant, ws: Workspace) -> list[tuple[User, Target]]:
    """Usuarios del workspace con su chat de Telegram vinculado y email."""
    users: dict[int, User] = {}
    for m in db.scalars(select(Membership).where(Membership.tenant_id == tenant.id)):
        if m.role in ("owner", "admin"):
            users[m.user_id] = db.get(User, m.user_id)
    for wm in db.scalars(select(WorkspaceMember).where(WorkspaceMember.workspace_id == ws.id)):
        users[wm.user_id] = db.get(User, wm.user_id)
    links = {l.user_id: l for l in db.scalars(select(TelegramLink).where(TelegramLink.workspace_id == ws.id, TelegramLink.chat_id.is_not(None)))}
    out = []
    for uid, u in users.items():
        if not u or not u.is_active:
            continue
        link = links.get(uid)
        email = ws_settings(ws).get("email_to") or u.email
        out.append((u, Target(tenant.id, ws.id, uid, link.chat_id if link else None, email)))
    return out


def _deliver(channel_name: str, tenant: Tenant, target: Target, msg: Message, kind: str) -> bool:
    ch = registry.get(channel_name)
    if not ch.available(tenant, target):
        return False
    try:
        ch.send(tenant, target, msg, kind)
        return True
    except Exception:  # un canal caído no debe tumbar el ciclo
        log.exception("notify_failed channel=%s ws=%s", channel_name, target.workspace_id)
        return False


# ------------------------------------------------------------------ alertas puntuales


def _repeat_days(st: dict, sev: str) -> int | None:
    return {"Alta": st["repeat_alta_days"], "Media": st["repeat_media_days"]}.get(sev)


def _is_due(a: Alert, now: datetime, st: dict) -> bool:
    days = _repeat_days(st, a.severity)
    if days is None:
        return False
    if a.last_notified_at is None:
        return True
    return now >= a.last_notified_at + timedelta(days=days) - timedelta(minutes=1)


def mark_notified(a: Alert, now: datetime, st: dict) -> None:
    a.notify_count += 1
    a.last_notified_at = now
    if a.severity == "Media" and a.notify_count >= int(st["escalate_after"]):
        a.escalated = True  # escala si sigue sin atenderse


def deliver_due_alerts(db: Session, tenant: Tenant, ws: Workspace, clock: Clock, rule_names: dict[str, str] | None = None) -> dict:
    """Envía alertas puntuales de severidad Alta (agrupadas por regla). Las Media/Baja viajan en el resumen."""
    now = clock.now_utc()
    local = clock.local_now(tenant.timezone)
    today = local.date()
    st = ws_settings(ws)
    holidays = load_holidays(db, ws.id)
    in_hours = is_work_time(local, holidays, tuple(st["work_days"]), st["work_start"], st["work_end"])
    stats = {"sent_messages": 0, "alerts_notified": 0, "skipped_off_hours": 0, "skipped_snoozed": 0}
    names = rule_names or {c: d["name"] for c, d in R.DEFAULT_RULES.items()}
    for user, target in targets_for(db, tenant, ws):
        mine = open_alerts_sorted(db, ws.id, today, owner_id=user.id, include_snoozed=True)
        due = []
        for a in mine:
            if a.snoozed_until and a.snoozed_until >= today:
                stats["skipped_snoozed"] += 1
                continue
            if a.severity != "Alta" or not _is_due(a, now, st):
                continue
            if not in_hours and not a.urgent:
                stats["skipped_off_hours"] += 1
                continue
            due.append(a)
        groups: dict[str, list[Alert]] = {}
        for a in due:
            groups.setdefault(a.rule_code, []).append(a)
        for code, items in sorted(groups.items(), key=lambda kv: (R.SEV_ORDER[kv[1][0].severity], kv[0])):
            if _deliver("telegram", tenant, target, group_message(ws, code, names.get(code, code), items), "alert"):
                stats["sent_messages"] += 1
                for a in items:
                    mark_notified(a, now, st)
                    stats["alerts_notified"] += 1
    db.flush()
    return stats


# ------------------------------------------------------------------ resumen diario


SECTIONS = [
    ("Acciones vencidas", {"R1"}), ("Para hoy y mañana", {"R2"}), ("Hitos próximos (DR · renovaciones · SEACE)", {"R7", "R8", "R9"}),
    ("Sin próxima acción", {"R3"}), ("Estancadas", {"R4", "R11"}), ("Fecha de cierre pasada", {"R5"}),
    ("Datos incompletos / seguimiento", {"R10", "R12", "R13"}),
]


def daily_digest_message(db: Session, ws: Workspace, user: User, today: date) -> Message | None:
    alerts = open_alerts_sorted(db, ws.id, today, owner_id=user.id)
    alerts = [a for a in alerts if a.rule_code != "R6"]
    if not alerts:
        return Message(f"☀️ <b>Resumen del {today:%d/%m}</b>\n\nTodo al día: no hay alertas abiertas. 🎉", [[Button("🔗 Abrir app", url=app_url(ws))]], subject="Resumen diario")
    parts = [f"☀️ <b>Resumen del {today:%d/%m/%Y}</b> · {len(alerts)} alertas abiertas"]
    for title, codes in SECTIONS:
        items = [a for a in alerts if a.rule_code in codes]
        if not items:
            continue
        parts.append(f"\n<b>{title}</b> ({len(items)})")
        for a in items[:10]:
            parts.append(f"• {e(a.title)}")
        if len(items) > 10:
            parts.append(f"  … y {len(items) - 10} más")
    parts.append("\n<i>Orden: severidad → prioridad → monto.</i>")
    buttons = [[Button("🔗 Abrir bandeja", url=app_url(ws, "/alerts"))]]
    return Message("\n".join(parts), buttons, subject="Resumen diario")


def send_daily_digest(db: Session, tenant: Tenant, ws: Workspace, clock: Clock) -> dict:
    now, today = clock.now_utc(), clock.today(tenant.timezone)
    st = ws_settings(ws)
    sent = 0
    for user, target in targets_for(db, tenant, ws):
        msg = daily_digest_message(db, ws, user, today)
        if msg and _deliver("telegram", tenant, target, msg, "daily"):
            sent += 1
            # las Media viajan sólo en el resumen: cada resumen cuenta como "aviso" (cadencia + escalamiento).
            # Las Alta llevan su propio aviso agrupado (deliver_due_alerts), con todo el detalle.
            for a in open_alerts_sorted(db, ws.id, today, owner_id=user.id):
                if a.severity == "Media" and a.rule_code != "R6" and _is_due(a, now, st):
                    mark_notified(a, now, st)
    return {"digests_sent": sent}


# ------------------------------------------------------------------ resumen semanal (email)


def weekly_digest_message(db: Session, ws: Workspace, user: User, today: date) -> Message:
    info = reports.dashboard(db, ws, today)
    alerts = open_alerts_sorted(db, ws.id, today, owner_id=user.id, include_snoozed=True)
    month = today.strftime("%Y-%m")
    fm = next((x for x in info["forecast_por_mes"] if x["mes"] == month), {"monto": 0, "ponderado": 0, "count": 0})

    def li(items, empty="—"):
        return "<ul>" + "".join(f"<li>{e(a.title)}<br><small>{e(a.detail)}</small></li>" for a in items) + "</ul>" if items else f"<p>{empty}</p>"

    stale = [a for a in alerts if a.rule_code in ("R4", "R11")]
    incomplete = [a for a in alerts if a.rule_code in ("R13", "R6", "R3", "R10")]
    # llamadas sugeridas: acciones de la semana + estancadas + partners silenciosos
    week_end = today + timedelta(days=6)
    opps = db.scalars(select(Opportunity).where(Opportunity.workspace_id == ws.id, Opportunity.fecha_prox_accion.is_not(None),
                                                 Opportunity.fecha_prox_accion <= week_end)).all()
    calls = [f"<li><b>{e(o.code)}</b> — {e(o.prox_accion or 'acción')} ({o.fecha_prox_accion:%d/%m})</li>" for o in sorted(opps, key=lambda o: o.fecha_prox_accion)]
    calls += [f"<li>{e(a.title)} <small>(por qué: {e(a.detail)})</small></li>" for a in alerts if a.rule_code in ("R4", "R12", "R9", "R7", "R8")][:10]
    body = f"""
    <h2>Resumen semanal · {e(ws.name)}</h2>
    <p><b>Pipeline abierto:</b> USD {info['pipeline_abierto']:,.0f} ({info['abiertas']} oportunidades) ·
       <b>Forecast ponderado:</b> USD {info['forecast_ponderado']:,.0f} · <b>Ganado:</b> USD {info['ganado']:,.0f}</p>
    <p><b>Forecast del mes ({month}):</b> USD {fm['ponderado']:,.0f} ponderado / USD {fm['monto']:,.0f} bruto ({fm['count']} op.)</p>
    <h3>A quién llamar esta semana</h3><ul>{''.join(calls) or '<li>Nada programado.</li>'}</ul>
    <h3>Oportunidades sin actualizar</h3>{li(stale)}
    <h3>Datos incompletos</h3>{li(incomplete)}
    <p><a href="{app_url(ws)}">Abrir el CRM</a></p>"""
    return Message(body, subject=f"Resumen semanal · {ws.name} · semana del {today:%d/%m}")


def send_weekly_digest(db: Session, tenant: Tenant, ws: Workspace, clock: Clock) -> dict:
    today = clock.today(tenant.timezone)
    sent = 0
    for user, target in targets_for(db, tenant, ws):
        if _deliver("email", tenant, target, weekly_digest_message(db, ws, user, today), "weekly"):
            sent += 1
    return {"weekly_sent": sent}


# ------------------------------------------------------------------ programación por tenant (zona horaria propia)


def digests_due(db: Session, tenant: Tenant, ws: Workspace, clock: Clock) -> tuple[bool, bool]:
    """(toca resumen diario, toca resumen semanal) según hora local del tenant y lo ya enviado."""
    local = clock.local_now(tenant.timezone)
    today = local.date()
    st = ws_settings(ws)
    holidays = load_holidays(db, ws.id)
    wd = tuple(st["work_days"])
    biz = is_business_day(today, holidays, wd)
    dtime = parse_hhmm(st["digest_time"], time(8, 0))
    wtime = parse_hhmm(st["weekly_time"], time(7, 30))
    now_t = local.time().replace(second=0, microsecond=0)
    daily = (
        st.get("last_digest_date") != today.isoformat() and now_t >= dtime
        and (local.hour * 60 + local.minute) < dtime.hour * 60 + dtime.minute + 180  # ventana de 3 h: no enviar resúmenes "viejos"
        and (biz or st.get("digest_on_non_business_days"))
    )
    iso = f"{today.isocalendar().year}-W{today.isocalendar().week:02d}"
    weekly = (
        st.get("last_weekly_week") != iso and today == first_business_day_of_week(today, holidays, wd) and now_t >= wtime
    )
    return daily, weekly
