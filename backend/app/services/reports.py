"""Dashboard (equivalente a la hoja Dashboard del Excel + forecast, aging y salud del pipeline)."""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Opportunity, Partner, Workspace
from .seed import stage_info


def _prob(info, stage):
    i = info.get(stage)
    return i.prob if i and i.prob is not None else 0.0


def dashboard(db: Session, ws: Workspace, today: date) -> dict:
    info = stage_info(db, ws.id)
    opps = db.scalars(select(Opportunity).where(Opportunity.workspace_id == ws.id)).all()
    partners = {p.id: p.name for p in db.scalars(select(Partner).where(Partner.workspace_id == ws.id))}

    def closed(o): return bool(info.get(o.stage) and info[o.stage].is_closed)
    def paused(o): return bool(info.get(o.stage) and info[o.stage].is_paused)

    open_ = [o for o in opps if not closed(o)]
    active = [o for o in open_ if not paused(o)]
    won = [o for o in opps if info.get(o.stage) and info[o.stage].is_won]
    lost = [o for o in opps if closed(o) and not (info.get(o.stage) and info[o.stage].is_won)]

    by_stage: dict[str, dict] = {}
    for st in info.values():
        by_stage[st.value] = {"stage": st.value, "count": 0, "monto": 0.0, "ponderado": 0.0, "sort": st.sort}
    for o in opps:
        b = by_stage.setdefault(o.stage, {"stage": o.stage, "count": 0, "monto": 0.0, "ponderado": 0.0, "sort": 99})
        b["count"] += 1
        b["monto"] += o.monto or 0
        b["ponderado"] += (o.monto or 0) * _prob(info, o.stage)

    def group(key):
        d: dict[str, dict] = defaultdict(lambda: {"count": 0, "monto": 0.0, "ponderado": 0.0})
        for o in active:
            k = key(o) or "—"
            d[k]["count"] += 1
            d[k]["monto"] += o.monto or 0
            d[k]["ponderado"] += (o.monto or 0) * _prob(info, o.stage)
        return [{"name": k, **v} for k, v in sorted(d.items(), key=lambda kv: -kv[1]["monto"])]

    forecast_mes: dict[str, dict] = defaultdict(lambda: {"monto": 0.0, "ponderado": 0.0, "count": 0})
    for o in active:
        k = o.fecha_cierre_est.strftime("%Y-%m") if o.fecha_cierre_est else "sin fecha"
        forecast_mes[k]["monto"] += o.monto or 0
        forecast_mes[k]["ponderado"] += (o.monto or 0) * _prob(info, o.stage)
        forecast_mes[k]["count"] += 1

    aging = []
    for st in sorted(info.values(), key=lambda s: s.sort):
        if st.is_closed:
            continue
        ds = [(today - o.stage_entered_on).days for o in active if o.stage == st.value and o.stage_entered_on]
        aging.append({"stage": st.value, "count": len(ds), "avg_days": round(sum(ds) / len(ds), 1) if ds else 0, "max_days": max(ds) if ds else 0})

    n = len(active) or 1
    con_accion = sum(1 for o in active if o.prox_accion.strip() and o.fecha_prox_accion and o.fecha_prox_accion >= today)
    salud = {
        "total_activas": len(active),
        "pct_proxima_accion_vigente": round(100 * con_accion / n, 1),
        "pct_fecha_cierre": round(100 * sum(1 for o in active if o.fecha_cierre_est) / n, 1),
        "pct_meddpicc": round(100 * sum(1 for o in active if o.meddpicc_score) / n, 1),
    }
    vencidas = sum(1 for o in active if o.fecha_prox_accion and o.fecha_prox_accion < today)
    decided = len(won) + len(lost)
    return {
        "pipeline_abierto": sum(o.monto or 0 for o in active),
        "forecast_ponderado": sum((o.monto or 0) * _prob(info, o.stage) for o in active),
        "ganado": sum(o.monto or 0 for o in won),
        "abiertas": len(active),
        "acciones_vencidas": vencidas,
        "win_rate": round(100 * len(won) / decided, 1) if decided else None,
        "por_etapa": sorted(by_stage.values(), key=lambda b: b["sort"]),
        "por_tipo": group(lambda o: o.tipo),
        "por_partner": group(lambda o: partners.get(o.partner_id)),
        "forecast_por_mes": [{"mes": k, **v} for k, v in sorted(forecast_mes.items())],
        "aging": aging,
        "salud": salud,
    }
