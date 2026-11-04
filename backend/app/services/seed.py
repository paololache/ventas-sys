"""Siembra de un workspace nuevo: catálogos, reglas de alerta, feriados de Perú y ajustes."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..alerts.rules import DEFAULT_RULES
from ..models import AlertRule, Holiday, ListItem, Tenant, Workspace

DEFAULT_WS_SETTINGS = {
    "work_days": [0, 1, 2, 3, 4],
    "work_start": 8,
    "work_end": 19,
    "digest_time": "08:00",
    "weekly_time": "07:30",
    "repeat_alta_days": 1,
    "repeat_media_days": 3,
    "escalate_after": 3,
    "digest_on_non_business_days": False,
    "email_to": "",
    "last_digest_date": "",
    "last_weekly_week": "",
}

STAGES = [  # (valor, prob, cerrada, ganada, pausada)
    ("Prospección", 0.10, False, False, False),
    ("Calificación", 0.20, False, False, False),
    ("Deal Registrado", 0.30, False, False, False),
    ("Propuesta enviada", 0.50, False, False, False),
    ("Negociación", 0.70, False, False, False),
    ("Renovación", 0.60, False, False, False),
    ("Ganada", 1.0, True, True, False),
    ("Perdida", 0.0, True, False, False),
    ("En pausa", 0.0, False, False, True),
]
CATALOGS = {
    "tipo": ["DR", "EW", "CSS"],
    "prioridad": ["Alta", "Media", "Baja"],
    "sector": ["Gobierno", "Banca y Finanzas", "Salud", "Educación", "Minería", "Retail", "Telecomunicaciones", "Industria", "Otro"],
    "marca": ["Extreme Networks", "VMware", "Citrix", "Omnissa", "Otra"],
    "tipo_accion": ["Llamada", "Reunión", "Email", "Demo/POC", "Envío de propuesta", "Seguimiento partner", "Visita cliente"],
}

# Feriados nacionales de Perú (fijos y Semana Santa). EDITABLES desde la app: verifique cada año el calendario oficial.
PERU_HOLIDAYS = [
    ("2026-01-01", "Año Nuevo"), ("2026-04-02", "Jueves Santo"), ("2026-04-03", "Viernes Santo"),
    ("2026-05-01", "Día del Trabajo"), ("2026-06-29", "San Pedro y San Pablo"), ("2026-07-23", "Día de la Fuerza Aérea"),
    ("2026-07-28", "Fiestas Patrias"), ("2026-07-29", "Fiestas Patrias"), ("2026-08-06", "Batalla de Junín"),
    ("2026-08-30", "Santa Rosa de Lima"), ("2026-10-08", "Combate de Angamos"), ("2026-10-31", "Día de las Iglesias Evangélicas"),
    ("2026-11-01", "Todos los Santos"), ("2026-12-08", "Inmaculada Concepción"), ("2026-12-09", "Batalla de Ayacucho"),
    ("2026-12-25", "Navidad"),
    ("2027-01-01", "Año Nuevo"), ("2027-03-25", "Jueves Santo"), ("2027-03-26", "Viernes Santo"),
    ("2027-05-01", "Día del Trabajo"), ("2027-06-29", "San Pedro y San Pablo"), ("2027-07-23", "Día de la Fuerza Aérea"),
    ("2027-07-28", "Fiestas Patrias"), ("2027-07-29", "Fiestas Patrias"), ("2027-08-06", "Batalla de Junín"),
    ("2027-08-30", "Santa Rosa de Lima"), ("2027-10-08", "Combate de Angamos"), ("2027-10-31", "Día de las Iglesias Evangélicas"),
    ("2027-11-01", "Todos los Santos"), ("2027-12-08", "Inmaculada Concepción"), ("2027-12-09", "Batalla de Ayacucho"),
    ("2027-12-25", "Navidad"),
]


def seed_workspace(db: Session, tenant: Tenant, ws: Workspace, owner_id: int | None, holidays: bool = True) -> None:
    ws.settings = {**DEFAULT_WS_SETTINGS, **(ws.settings or {})}
    base = dict(tenant_id=tenant.id, workspace_id=ws.id, owner_id=owner_id)
    for i, (v, p, closed, won, paused) in enumerate(STAGES):
        db.add(ListItem(kind="stage", value=v, prob=p, is_closed=closed, is_won=won, is_paused=paused, sort=i, **base))
    for kind, values in CATALOGS.items():
        for i, v in enumerate(values):
            db.add(ListItem(kind=kind, value=v, sort=i, **base))
    for code, d in DEFAULT_RULES.items():
        db.add(AlertRule(code=code, enabled=True, severity=d["severity"], params=d["params"], **base))
    if holidays:
        for f, n in PERU_HOLIDAYS:
            db.add(Holiday(fecha=date.fromisoformat(f), nombre=n, **base))
    db.flush()


def stage_info(db: Session, ws_id: int) -> dict[str, ListItem]:
    rows = db.scalars(select(ListItem).where(ListItem.workspace_id == ws_id, ListItem.kind == "stage")).all()
    return {r.value: r for r in rows}
