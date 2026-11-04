"""Reglas de alerta R1–R13 como funciones puras.

Entrada: vistas inmutables de los datos + `today` inyectado.  Salida: lista de `Candidate`.
No tocan la base de datos ni el reloj, así que son triviales de testear.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

from ..calendar_util import business_days_between

SEV_ORDER = {"Alta": 0, "Media": 1, "Baja": 2}
PRIO_ORDER = {"Alta": 0, "Media": 1, "Baja": 2}

# Definición por defecto: se siembra en `alert_rules` por workspace y es editable desde la app.
DEFAULT_RULES: dict[str, dict] = {
    "R1": {"name": "Acción vencida", "severity": "Alta", "params": {}},
    "R2": {"name": "Acción para hoy / mañana", "severity": "Media", "params": {"dias": 1}},
    "R3": {"name": "Sin próxima acción", "severity": "Alta", "params": {}},
    "R4": {
        "name": "Oportunidad estancada",
        "severity": "Media",  # sube a Alta si la prioridad es Alta
        "params": {
            "dias_habiles_por_etapa": {
                "Prospección": 14, "Calificación": 10, "Deal Registrado": 10,
                "Propuesta enviada": 5, "Negociación": 3, "Renovación": 15,
            },
            "default": 14,
        },
    },
    "R5": {"name": "Fecha de cierre pasada", "severity": "Alta", "params": {}},
    "R6": {"name": "Sin fecha de cierre", "severity": "Baja", "params": {}},
    "R7": {"name": "DR por vencer", "severity": "Alta", "params": {"dias": 15}},
    "R8": {"name": "Renovación por vencer", "severity": "Media", "params": {"tramos": [60, 30, 15], "alta_en": 15}},
    "R9": {"name": "Hito SEACE", "severity": "Alta", "params": {"dias": 3}},
    "R10": {"name": "Próximo paso huérfano", "severity": "Media", "params": {}},
    "R11": {"name": "Demasiado tiempo en la etapa", "severity": "Media", "params": {"factor": 2.0, "min_muestras": 3}},
    "R12": {"name": "Partner silencioso", "severity": "Media", "params": {"dias": 21}},
    "R13": {"name": "Datos incompletos en oportunidad grande", "severity": "Media", "params": {"monto_usd": 50000}},
}


@dataclass(frozen=True)
class RuleCfg:
    enabled: bool = True
    severity: str = "Media"
    params: dict = field(default_factory=dict)


def default_cfgs() -> dict[str, RuleCfg]:
    return {c: RuleCfg(True, d["severity"], d["params"]) for c, d in DEFAULT_RULES.items()}


@dataclass(frozen=True)
class OppView:
    id: int
    code: str
    cliente: str
    descripcion: str
    tipo: str
    stage: str
    is_open: bool
    is_paused: bool
    prioridad: str
    monto: float
    fecha_cierre_est: date | None
    prox_accion: str
    fecha_prox_accion: date | None
    sin_proximo_paso_motivo: str
    ultima_actualizacion: date | None
    stage_entered_on: date | None
    dr_vencimiento: date | None
    contrato_vencimiento: date | None
    seace_publicacion: date | None
    seace_buena_pro: date | None
    seace_propuestas: date | None
    meddpicc_score: int
    has_contact: bool
    partner_id: int | None
    owner_id: int | None


@dataclass(frozen=True)
class ActivityView:
    id: int
    opportunity_id: int
    fecha: date
    proximo_paso: str
    fecha_proximo_paso: date | None


@dataclass(frozen=True)
class PartnerView:
    id: int
    name: str
    open_opps: int
    last_activity: date | None  # última actividad con cualquiera de sus oportunidades
    oldest_open_update: date | None
    owner_id: int | None = None


@dataclass(frozen=True)
class Candidate:
    rule: str
    severity: str
    key: str
    title: str
    detail: str = ""
    opp_id: int | None = None
    partner_id: int | None = None
    activity_id: int | None = None
    urgent: bool = False  # Alta con fecha de hoy → puede notificarse fuera de horario
    prioridad: str = "Media"
    monto: float = 0.0
    owner_id: int | None = None


@dataclass(frozen=True)
class EvalCtx:
    today: date
    holidays: frozenset[date] = frozenset()
    work_days: tuple[int, ...] = (0, 1, 2, 3, 4)
    rules: dict[str, RuleCfg] = field(default_factory=default_cfgs)
    stage_avg_days: dict[str, tuple[float, int]] = field(default_factory=dict)  # etapa → (promedio, n muestras)

    def cfg(self, code: str) -> RuleCfg:
        return self.rules.get(code) or default_cfgs()[code]


def _fmt(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else "—"


def _label(o: OppView) -> str:
    return f"{o.code} · {o.cliente or 'Sin cliente'}"


def _c(o: OppView, rule: str, sev: str, title: str, detail: str = "", suffix: str = "", urgent: bool = False) -> Candidate:
    return Candidate(
        rule=rule, severity=sev, key=f"{rule}:opp:{o.id}{suffix}", title=title, detail=detail,
        opp_id=o.id, urgent=urgent and sev == "Alta", prioridad=o.prioridad, monto=o.monto, owner_id=o.owner_id,
    )


def _days_to(d: date, today: date) -> int:
    return (d - today).days


# ------------------------------------------------------------------ reglas por oportunidad


def r1_accion_vencida(o: OppView, x: EvalCtx) -> list[Candidate]:
    cfg = x.cfg("R1")
    if not cfg.enabled or not o.is_open or o.is_paused or not o.fecha_prox_accion:
        return []
    if o.fecha_prox_accion < x.today:
        n = (x.today - o.fecha_prox_accion).days
        return [_c(o, "R1", cfg.severity, f"{_label(o)}: acción vencida hace {n} d",
                   f"{o.prox_accion or 'Acción'} (era para {_fmt(o.fecha_prox_accion)})")]
    return []


def r2_accion_proxima(o: OppView, x: EvalCtx) -> list[Candidate]:
    cfg = x.cfg("R2")
    if not cfg.enabled or not o.is_open or o.is_paused or not o.fecha_prox_accion:
        return []
    dias = int(cfg.params.get("dias", 1))
    n = _days_to(o.fecha_prox_accion, x.today)
    if 0 <= n <= dias:
        cuando = "hoy" if n == 0 else "mañana" if n == 1 else f"en {n} d"
        return [_c(o, "R2", cfg.severity, f"{_label(o)}: acción {cuando}", o.prox_accion)]
    return []


def r3_sin_proxima_accion(o: OppView, x: EvalCtx) -> list[Candidate]:
    cfg = x.cfg("R3")
    if not cfg.enabled or not o.is_open or o.is_paused:
        return []
    if o.sin_proximo_paso_motivo.strip():
        return []  # marcado explícitamente "sin próximo paso" con motivo
    if not o.prox_accion.strip() or not o.fecha_prox_accion:
        falta = "sin acción ni fecha" if not o.prox_accion.strip() and not o.fecha_prox_accion else (
            "acción sin fecha" if not o.fecha_prox_accion else "fecha sin acción")
        return [_c(o, "R3", cfg.severity, f"{_label(o)}: sin próxima acción", f"{falta} · etapa {o.stage}")]
    return []


def r4_estancada(o: OppView, x: EvalCtx) -> list[Candidate]:
    cfg = x.cfg("R4")
    if not cfg.enabled or not o.is_open or o.is_paused or not o.ultima_actualizacion:
        return []
    por_etapa = cfg.params.get("dias_habiles_por_etapa", {})
    limite = por_etapa.get(o.stage, cfg.params.get("default"))
    if limite is None:
        return []
    dias = business_days_between(o.ultima_actualizacion, x.today, x.holidays, x.work_days)
    if dias > int(limite):
        sev = "Alta" if o.prioridad == "Alta" else cfg.severity
        return [_c(o, "R4", sev, f"{_label(o)}: estancada {dias} d hábiles en {o.stage}",
                   f"Límite {limite} d · última actualización {_fmt(o.ultima_actualizacion)}")]
    return []


def r5_cierre_pasado(o: OppView, x: EvalCtx) -> list[Candidate]:
    cfg = x.cfg("R5")
    if not cfg.enabled or not o.is_open or o.is_paused or not o.fecha_cierre_est:
        return []
    if o.fecha_cierre_est < x.today:
        n = (x.today - o.fecha_cierre_est).days
        return [_c(o, "R5", cfg.severity, f"{_label(o)}: fecha de cierre pasada hace {n} d",
                   f"Cierre estimado {_fmt(o.fecha_cierre_est)} · sigue en {o.stage}")]
    return []


def r6_sin_fecha_cierre(o: OppView, x: EvalCtx) -> list[Candidate]:
    cfg = x.cfg("R6")
    if not cfg.enabled or not o.is_open or o.is_paused or o.fecha_cierre_est:
        return []
    return [_c(o, "R6", cfg.severity, f"{_label(o)}: sin fecha de cierre estimada", f"Etapa {o.stage}")]


def r7_dr_por_vencer(o: OppView, x: EvalCtx) -> list[Candidate]:
    cfg = x.cfg("R7")
    if not cfg.enabled or not o.is_open or o.is_paused or not o.dr_vencimiento:
        return []
    n = _days_to(o.dr_vencimiento, x.today)
    if n <= int(cfg.params.get("dias", 15)):
        txt = "VENCIDO" if n < 0 else "vence hoy" if n == 0 else f"vence en {n} d"
        return [_c(o, "R7", cfg.severity, f"{_label(o)}: deal registration {txt}",
                   f"Vencimiento DR {_fmt(o.dr_vencimiento)}", urgent=(n == 0))]
    return []


def r8_renovacion(o: OppView, x: EvalCtx) -> list[Candidate]:
    cfg = x.cfg("R8")
    if not cfg.enabled or not o.is_open or o.is_paused or o.tipo not in ("EW", "CSS") or not o.contrato_vencimiento:
        return []
    n = _days_to(o.contrato_vencimiento, x.today)
    tramos = sorted(int(t) for t in cfg.params.get("tramos", [60, 30, 15]))
    if n > tramos[-1]:
        return []
    alta_en = int(cfg.params.get("alta_en", tramos[0]))
    sev = "Alta" if n <= alta_en else cfg.severity
    txt = "VENCIDO" if n < 0 else "vence hoy" if n == 0 else f"vence en {n} d"
    return [_c(o, "R8", sev, f"{_label(o)}: contrato {o.tipo} {txt}",
               f"Vencimiento {_fmt(o.contrato_vencimiento)}", urgent=(n == 0))]


def r9_hito_seace(o: OppView, x: EvalCtx) -> list[Candidate]:
    cfg = x.cfg("R9")
    if not cfg.enabled or not o.is_open or o.is_paused:
        return []
    out = []
    hitos = (("publicación", o.seace_publicacion), ("buena pro", o.seace_buena_pro), ("presentación de propuestas", o.seace_propuestas))
    for nombre, fecha in hitos:
        if not fecha:
            continue
        n = _days_to(fecha, x.today)
        if 0 <= n <= int(cfg.params.get("dias", 3)):
            cuando = "hoy" if n == 0 else f"en {n} d"
            out.append(_c(o, "R9", cfg.severity, f"{_label(o)}: SEACE {nombre} {cuando}",
                          f"{_fmt(fecha)}", suffix=f":{nombre}", urgent=(n == 0)))
    return out


def r13_datos_incompletos(o: OppView, x: EvalCtx) -> list[Candidate]:
    cfg = x.cfg("R13")
    if not cfg.enabled or not o.is_open or o.is_paused:
        return []
    if o.monto <= float(cfg.params.get("monto_usd", 50000)):
        return []
    falta = []
    if not o.meddpicc_score:
        falta.append("MEDDPICC")
    if not o.has_contact:
        falta.append("contacto")
    if not o.fecha_cierre_est:
        falta.append("fecha de cierre")
    if falta:
        return [_c(o, "R13", cfg.severity, f"{_label(o)}: oportunidad de USD {o.monto:,.0f} con datos incompletos",
                   "Falta: " + ", ".join(falta))]
    return []


def r11_demasiado_en_etapa(o: OppView, x: EvalCtx) -> list[Candidate]:
    cfg = x.cfg("R11")
    if not cfg.enabled or not o.is_open or o.is_paused or not o.stage_entered_on:
        return []
    avg = x.stage_avg_days.get(o.stage)
    if not avg or avg[1] < int(cfg.params.get("min_muestras", 3)) or avg[0] <= 0:
        return []
    dias = (x.today - o.stage_entered_on).days
    factor = float(cfg.params.get("factor", 2.0))
    if dias > factor * avg[0]:
        return [_c(o, "R11", cfg.severity, f"{_label(o)}: {dias} d en {o.stage}",
                   f"Promedio histórico {avg[0]:.0f} d (umbral {factor:g}× = {factor * avg[0]:.0f} d)")]
    return []


OPP_RULES = (
    r1_accion_vencida, r2_accion_proxima, r3_sin_proxima_accion, r4_estancada, r5_cierre_pasado,
    r6_sin_fecha_cierre, r7_dr_por_vencer, r8_renovacion, r9_hito_seace, r11_demasiado_en_etapa,
    r13_datos_incompletos,
)


def evaluate_opportunity(o: OppView, x: EvalCtx) -> list[Candidate]:
    out: list[Candidate] = []
    for rule in OPP_RULES:
        out.extend(rule(o, x))
    return out


# ------------------------------------------------------------------ reglas con otro sujeto


def r10_paso_huerfano(activities: Iterable[ActivityView], opps: dict[int, OppView], x: EvalCtx) -> list[Candidate]:
    """Actividad con 'próximo paso' escrito, sin fecha, en una oportunidad abierta que no tiene próxima acción con fecha."""
    cfg = x.cfg("R10")
    if not cfg.enabled:
        return []
    out = []
    for a in activities:
        o = opps.get(a.opportunity_id)
        if o is None or not o.is_open or o.is_paused:
            continue
        if a.proximo_paso.strip() and a.fecha_proximo_paso is None and o.fecha_prox_accion is None:
            out.append(Candidate(
                rule="R10", severity=cfg.severity, key=f"R10:act:{a.id}",
                title=f"{_label(o)}: próximo paso sin fecha",
                detail=f"«{a.proximo_paso}» (actividad del {_fmt(a.fecha)})",
                opp_id=o.id, activity_id=a.id, prioridad=o.prioridad, monto=o.monto, owner_id=o.owner_id,
            ))
    return out


def r12_partner_silencioso(partners: Iterable[PartnerView], x: EvalCtx) -> list[Candidate]:
    cfg = x.cfg("R12")
    if not cfg.enabled:
        return []
    limite = int(cfg.params.get("dias", 21))
    out = []
    for p in partners:
        if p.open_opps <= 0:
            continue
        ref = p.last_activity or p.oldest_open_update
        if ref is None:
            continue
        dias = (x.today - ref).days
        if dias > limite:
            out.append(Candidate(
                rule="R12", severity=cfg.severity, key=f"R12:partner:{p.id}",
                title=f"Partner {p.name}: {dias} d sin actividad",
                detail=f"{p.open_opps} oportunidades abiertas · última actividad {_fmt(p.last_activity)}",
                partner_id=p.id, owner_id=p.owner_id,
            ))
    return out
