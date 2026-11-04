"""Importación idempotente desde CRM_Oportunidades_Adistec.xlsx, reporte de calidad y exportación al mismo formato."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from io import BytesIO

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..alerts.engine import compute_candidates
from ..deps import Ctx
from ..models import Activity, Client, Contact, ListItem, Opportunity, Partner, StageHistory
from .seed import CATALOGS, stage_info

PIPELINE_HEADERS = [
    "ID", "Tipo", "Cliente final", "Oportunidad / Descripción", "Sector", "Partner", "Distribuidor", "Marca", "Monto (USD)",
    "MEDDPICC", "Etapa", "Prob.", "Monto ponderado", "Prioridad", "Fecha cierre estimada", "Próxima acción",
    "Fecha próx. acción", "Días para acción", "Alerta", "Responsable cliente", "Última actualización", "Comentarios",
]
BITACORA_HEADERS = ["Fecha", "ID Oportunidad", "Cliente", "Tipo acción", "Contacto", "Resumen / Acuerdos", "Próximo paso", "Fecha próximo paso"]

PIPELINE_MAP = {
    "id": "code", "tipo": "tipo", "clientefinal": "cliente", "oportunidaddescripcion": "descripcion", "sector": "sector",
    "partner": "partner", "distribuidor": "distribuidor", "marca": "marca", "montousd": "monto", "meddpicc": "meddpicc",
    "etapa": "stage", "prioridad": "prioridad", "fechacierreestimada": "fecha_cierre_est", "proximaaccion": "prox_accion",
    "fechaproxaccion": "fecha_prox_accion", "responsablecliente": "responsable", "ultimaactualizacion": "ultima",
    "comentarios": "comentarios",
}
BITACORA_MAP = {
    "fecha": "fecha", "idoportunidad": "code", "cliente": "cliente", "tipoaccion": "tipo", "contacto": "contacto",
    "resumenacuerdos": "resumen", "proximopaso": "proximo_paso", "fechaproximopaso": "fecha_proximo_paso",
}
LISTAS_KINDS = {"etapa": "stage", "tipo": "tipo", "prioridad": "prioridad", "sector": "sector", "marca": "marca", "tipoaccion": "tipo_accion"}


def norm(s) -> str:
    s = unicodedata.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def clean(s) -> str:
    return re.sub(r"\s+", " ", str(s)).strip() if s is not None else ""


def to_date(v) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = clean(v)
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def to_num(v) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d.\-]", "", clean(v).replace(",", ""))
    try:
        return float(s)
    except ValueError:
        return 0.0


def find_sheet(wb, name: str):
    for ws in wb.worksheets:
        if norm(ws.title) == name:
            return ws
    return None


def header_row(ws, mapping: dict, required: set[str], scan: int = 15):
    """Devuelve (fila, {campo: col}) de la primera fila que contiene los encabezados requeridos."""
    for r in range(1, scan + 1):
        cols = {}
        for c in range(1, ws.max_column + 1):
            k = mapping.get(norm(ws.cell(r, c).value))
            if k and k not in cols:
                cols[k] = c
        if required <= set(cols):
            return r, cols
    raise ValueError(f"Hoja '{ws.title}': no encontré la fila de encabezados {sorted(required)}")


@dataclass
class ImportResult:
    opportunities_created: int = 0
    opportunities_updated: int = 0
    activities_created: int = 0
    activities_skipped: int = 0
    partners: int = 0
    clients: int = 0
    contacts: int = 0
    warnings: list[str] = field(default_factory=list)


class _Cache:
    """Búsqueda case-insensitive con normalización de espacios."""

    def __init__(self, db: Session, ctx: Ctx, model, extra=None):
        self.db, self.ctx, self.model, self.extra = db, ctx, model, extra or {}
        self.items = {clean(o.name).casefold(): o for o in db.scalars(select(model).where(model.workspace_id == ctx.ws.id))}
        self.created = 0

    def get(self, name: str, **kw):
        name = clean(name)
        if not name:
            return None
        key = name.casefold()
        if key not in self.items:
            obj = self.model(tenant_id=self.ctx.tenant.id, workspace_id=self.ctx.ws.id, owner_id=self.ctx.user.id, name=name, **kw)
            self.db.add(obj)
            self.db.flush()
            self.items[key] = obj
            self.created += 1
        return self.items[key]


def _read_listas(ws_sheet) -> dict[str, list[tuple[str, float | None]]]:
    out: dict[str, list] = {}
    if ws_sheet is None:
        return out
    for r in range(1, 11):
        cols = {}
        for c in range(1, ws_sheet.max_column + 1):
            k = norm(ws_sheet.cell(r, c).value)
            if k in LISTAS_KINDS and LISTAS_KINDS[k] not in cols:
                cols[LISTAS_KINDS[k]] = c
        if not cols:
            continue
        for kind, c in cols.items():
            nxt = norm(ws_sheet.cell(r, c + 1).value)
            for rr in range(r + 1, ws_sheet.max_row + 1):
                v = clean(ws_sheet.cell(rr, c).value)
                if not v:
                    break
                p = None
                if kind == "stage" and nxt.startswith("prob"):
                    pv = ws_sheet.cell(rr, c + 1).value
                    p = to_num(pv) if pv is not None else None
                    p = p / 100 if p is not None and p > 1 else p
                out.setdefault(kind, []).append((v, p))
        break
    return out


def import_excel(db: Session, ctx: Ctx, source, today: date) -> ImportResult:
    """Importa Pipeline, Bitácora y Listas. Idempotente: reimportar actualiza, no duplica."""
    wb = load_workbook(source, data_only=True)
    res = ImportResult()

    # ---- Listas (catálogos editables)
    existing = {(i.kind, i.value.casefold()): i for i in db.scalars(select(ListItem).where(ListItem.workspace_id == ctx.ws.id))}
    for kind, vals in _read_listas(find_sheet(wb, "listas")).items():
        for i, (v, p) in enumerate(vals):
            it = existing.get((kind, v.casefold()))
            if it is None:
                it = ListItem(tenant_id=ctx.tenant.id, workspace_id=ctx.ws.id, owner_id=ctx.user.id, kind=kind, value=v, sort=i)
                db.add(it)
                existing[(kind, v.casefold())] = it
            if kind == "stage":
                if p is not None:
                    it.prob = p
                n = v.casefold()
                it.is_closed = n in ("ganada", "perdida", "cerrada ganada", "cerrada perdida")
                it.is_won = n.startswith("ganada")
                it.is_paused = "pausa" in n
    db.flush()

    ps = find_sheet(wb, "pipeline")
    if ps is None:
        raise ValueError("El Excel no tiene hoja 'Pipeline'")
    hr, cols = header_row(ps, PIPELINE_MAP, {"code", "stage"})
    partners, clients = _Cache(db, ctx, Partner), _Cache(db, ctx, Client)
    contacts_created = 0

    def ensure_item(kind: str, v: str, prob=None):
        v = clean(v)
        if v and (kind, v.casefold()) not in existing:
            it = ListItem(tenant_id=ctx.tenant.id, workspace_id=ctx.ws.id, owner_id=ctx.user.id, kind=kind, value=v, prob=prob, sort=99)
            db.add(it)
            existing[(kind, v.casefold())] = it

    opps = {o.code: o for o in db.scalars(select(Opportunity).where(Opportunity.workspace_id == ctx.ws.id))}
    for r in range(hr + 1, ps.max_row + 1):
        row = {k: ps.cell(r, c).value for k, c in cols.items()}
        code = clean(row.get("code")).upper()
        if not re.fullmatch(r"OP-\d+", code):
            if code:
                res.warnings.append(f"Fila {r}: ID '{code}' no tiene formato OP-xxx; omitida")
            continue
        for kind, key in (("tipo", "tipo"), ("sector", "sector"), ("marca", "marca"), ("prioridad", "prioridad"), ("stage", "stage")):
            ensure_item(kind, row.get(key) or "")
        client = clients.get(row.get("cliente"), sector=clean(row.get("sector")))
        partner = partners.get(row.get("partner"))
        data = dict(
            tipo=clean(row.get("tipo")) or "DR", client_id=client.id if client else None, descripcion=clean(row.get("descripcion")),
            sector=clean(row.get("sector")), partner_id=partner.id if partner else None, distribuidor=clean(row.get("distribuidor")),
            marca=clean(row.get("marca")), monto=to_num(row.get("monto")), stage=clean(row.get("stage")) or "Prospección",
            prioridad=clean(row.get("prioridad")) or "Media", fecha_cierre_est=to_date(row.get("fecha_cierre_est")),
            prox_accion=clean(row.get("prox_accion")), fecha_prox_accion=to_date(row.get("fecha_prox_accion")),
            comentarios=clean(row.get("comentarios")),
        )
        opp = opps.get(code)
        created = opp is None
        if created:
            opp = Opportunity(tenant_id=ctx.tenant.id, workspace_id=ctx.ws.id, owner_id=ctx.user.id, code=code, **data)
            db.add(opp)
            db.flush()
            opp.ultima_actualizacion = to_date(row.get("ultima")) or today
            opp.stage_entered_on = opp.ultima_actualizacion
            db.add(StageHistory(tenant_id=ctx.tenant.id, workspace_id=ctx.ws.id, owner_id=ctx.user.id, opportunity_id=opp.id,
                                from_stage=None, to_stage=opp.stage, changed_on=opp.ultima_actualizacion))
            opps[code] = opp
            res.opportunities_created += 1
        else:
            if opp.stage != data["stage"]:
                db.add(StageHistory(tenant_id=ctx.tenant.id, workspace_id=ctx.ws.id, owner_id=ctx.user.id, opportunity_id=opp.id,
                                    from_stage=opp.stage, to_stage=data["stage"], changed_on=today))
                opp.stage_entered_on = today
            for k, v in data.items():
                setattr(opp, k, v)
            res.opportunities_updated += 1
        resp = clean(row.get("responsable"))
        if resp and client:
            c = db.scalar(select(Contact).where(Contact.workspace_id == ctx.ws.id, Contact.client_id == client.id, Contact.name.ilike(resp)))
            if c is None:
                c = Contact(tenant_id=ctx.tenant.id, workspace_id=ctx.ws.id, owner_id=ctx.user.id, name=resp, kind="client", client_id=client.id)
                db.add(c)
                db.flush()
                contacts_created += 1
            opp.responsable_id = c.id
        score = row.get("meddpicc")
        if isinstance(score, (int, float)) and score:
            opp.meddpicc_score = int(score)
    db.flush()

    # ---- Bitácora
    bs = find_sheet(wb, "bitacora")
    if bs is not None:
        hr2, bcols = header_row(bs, BITACORA_MAP, {"fecha", "code"})
        existing_keys = set(db.scalars(select(Activity.import_key).where(Activity.workspace_id == ctx.ws.id, Activity.import_key.is_not(None))))
        for r in range(hr2 + 1, bs.max_row + 1):
            row = {k: bs.cell(r, c).value for k, c in bcols.items()}
            code, fecha = clean(row.get("code")).upper(), to_date(row.get("fecha"))
            if not code and not fecha:
                continue
            opp = opps.get(code)
            if opp is None or fecha is None:
                res.warnings.append(f"Bitácora fila {r}: oportunidad '{code}' o fecha inválida; omitida")
                continue
            tipo = clean(row.get("tipo")) or "Llamada"
            ensure_item("tipo_accion", tipo)
            resumen, paso, fpaso = clean(row.get("resumen")), clean(row.get("proximo_paso")), to_date(row.get("fecha_proximo_paso"))
            key = hashlib.sha1("|".join([code, fecha.isoformat(), tipo, resumen, paso]).encode()).hexdigest()
            if key in existing_keys:
                res.activities_skipped += 1
                continue
            existing_keys.add(key)
            db.add(Activity(tenant_id=ctx.tenant.id, workspace_id=ctx.ws.id, owner_id=ctx.user.id, opportunity_id=opp.id, fecha=fecha,
                            tipo=tipo, contacto=clean(row.get("contacto")), resumen=resumen, proximo_paso=paso,
                            fecha_proximo_paso=fpaso, source="import", import_key=key))
            if not opp.ultima_actualizacion or fecha > opp.ultima_actualizacion:
                opp.ultima_actualizacion = fecha  # última actualización = última actividad o cambio relevante
            res.activities_created += 1
    res.partners, res.clients, res.contacts = partners.created, clients.created, contacts_created
    db.flush()
    return res


# ------------------------------------------------------------------ reporte de calidad


def quality_report(db: Session, ctx: Ctx, today: date) -> dict:
    """Cuenta lo mismo que el motor de alertas generará en su primera corrida (se calcula con las mismas reglas)."""
    info = stage_info(db, ctx.ws.id)
    opps = db.scalars(select(Opportunity).where(Opportunity.workspace_id == ctx.ws.id)).all()
    active = [o for o in opps if not (info.get(o.stage) and (info[o.stage].is_closed or info[o.stage].is_paused))]
    cands, _ = compute_candidates(db, ctx.ws, today)
    by_rule: dict[str, int] = {}
    for c in cands:
        by_rule[c.rule] = by_rule.get(c.rule, 0) + 1
    clients_with_contact = set(db.scalars(select(Contact.client_id).where(Contact.workspace_id == ctx.ws.id, Contact.client_id.is_not(None))))
    return {
        "oportunidades_total": len(opps),
        "oportunidades_activas": len(active),
        "sin_proxima_accion": by_rule.get("R3", 0),
        "sin_fecha_cierre": by_rule.get("R6", 0),
        "sin_contacto": sum(1 for o in active if not o.responsable_id and o.client_id not in clients_with_contact),
        "sin_meddpicc": sum(1 for o in active if not o.meddpicc_score),
        "actividades_proximo_paso_sin_fecha": db.scalar(
            select(func.count()).select_from(Activity).where(
                Activity.workspace_id == ctx.ws.id, Activity.proximo_paso != "", Activity.fecha_proximo_paso.is_(None))) or 0,
        "alertas_primera_corrida": {k: by_rule[k] for k in sorted(by_rule)},
    }


def format_report(rep: dict) -> str:
    return "\n".join([
        "=== Reporte de calidad de datos ===",
        f"Oportunidades: {rep['oportunidades_total']} ({rep['oportunidades_activas']} activas)",
        f"  · sin próxima acción (R3):        {rep['sin_proxima_accion']}",
        f"  · sin fecha de cierre (R6):       {rep['sin_fecha_cierre']}",
        f"  · sin contacto:                   {rep['sin_contacto']}",
        f"  · sin MEDDPICC:                   {rep['sin_meddpicc']}",
        f"  · actividades con próximo paso sin fecha: {rep['actividades_proximo_paso_sin_fecha']}",
        "Alertas que generará la primera corrida: " + ", ".join(f"{k}={v}" for k, v in rep["alertas_primera_corrida"].items()),
    ])


# ------------------------------------------------------------------ exportación


def _alerta_label(o: Opportunity, closed: bool, today: date) -> tuple[int | None, str]:
    if closed:
        return None, "Cerrada"
    if not o.fecha_prox_accion:
        return None, "Sin acción"
    n = (o.fecha_prox_accion - today).days
    return n, "Vencida" if n < 0 else "Esta semana" if n <= 3 else "En tiempo"


def export_excel(db: Session, ctx: Ctx, today: date) -> bytes:
    info = stage_info(db, ctx.ws.id)
    wb = Workbook()
    ws = wb.active
    ws.title = "Pipeline"
    ws["A1"] = f"Pipeline · {ctx.tenant.name} / {ctx.ws.name}"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = f"Exportado el {today:%d/%m/%Y}"
    for i, h in enumerate(PIPELINE_HEADERS, 1):
        c = ws.cell(4, i, h)
        c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F3A5F")
        c.alignment = Alignment(wrap_text=True, vertical="center")
    clients = {c.id: c for c in db.scalars(select(Client).where(Client.workspace_id == ctx.ws.id))}
    partners = {p.id: p for p in db.scalars(select(Partner).where(Partner.workspace_id == ctx.ws.id))}
    contacts = {c.id: c for c in db.scalars(select(Contact).where(Contact.workspace_id == ctx.ws.id))}
    opps = db.scalars(select(Opportunity).where(Opportunity.workspace_id == ctx.ws.id).order_by(Opportunity.code)).all()
    for r, o in enumerate(opps, 5):
        st = info.get(o.stage)
        prob = st.prob if st and st.prob is not None else 0
        dias, alerta = _alerta_label(o, bool(st and st.is_closed), today)
        row = [o.code, o.tipo, clients[o.client_id].name if o.client_id in clients else "", o.descripcion, o.sector,
               partners[o.partner_id].name if o.partner_id in partners else "", o.distribuidor, o.marca, o.monto, o.meddpicc_score or None,
               o.stage, prob, (o.monto or 0) * prob, o.prioridad, o.fecha_cierre_est, o.prox_accion, o.fecha_prox_accion, dias, alerta,
               contacts[o.responsable_id].name if o.responsable_id in contacts else "", o.ultima_actualizacion, o.comentarios]
        for i, v in enumerate(row, 1):
            c = ws.cell(r, i, v)
            if isinstance(v, date):
                c.number_format = "dd/mm/yyyy"
        ws.cell(r, 12).number_format = "0%"
        ws.cell(r, 9).number_format = ws.cell(r, 13).number_format = "#,##0"
    for i, w in enumerate([9, 7, 26, 40, 16, 20, 14, 18, 12, 10, 18, 7, 14, 10, 14, 34, 14, 9, 12, 22, 14, 40], 1):
        ws.column_dimensions[ws.cell(4, i).column_letter].width = w
    ws.freeze_panes = "B5"

    bs = wb.create_sheet("Bitácora")
    for i, h in enumerate(BITACORA_HEADERS, 1):
        c = bs.cell(4, i, h)
        c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F3A5F")
    by_id = {o.id: o for o in opps}
    for r, a in enumerate(db.scalars(select(Activity).where(Activity.workspace_id == ctx.ws.id).order_by(Activity.fecha, Activity.id)), 5):
        o = by_id.get(a.opportunity_id)
        vals = [a.fecha, o.code if o else "", clients[o.client_id].name if o and o.client_id in clients else "", a.tipo, a.contacto,
                a.resumen, a.proximo_paso, a.fecha_proximo_paso]
        for i, v in enumerate(vals, 1):
            c = bs.cell(r, i, v)
            if isinstance(v, date):
                c.number_format = "dd/mm/yyyy"

    ls = wb.create_sheet("Listas")
    kinds = [("stage", "Etapa"), ("tipo", "Tipo"), ("prioridad", "Prioridad"), ("sector", "Sector"), ("marca", "Marca"), ("tipo_accion", "Tipo acción")]
    col = 1
    for kind, title in kinds:
        ls.cell(1, col, title).font = Font(bold=True)
        if kind == "stage":
            ls.cell(1, col + 1, "Probabilidad").font = Font(bold=True)
        items = db.scalars(select(ListItem).where(ListItem.workspace_id == ctx.ws.id, ListItem.kind == kind).order_by(ListItem.sort, ListItem.id)).all()
        for r, it in enumerate(items, 2):
            ls.cell(r, col, it.value)
            if kind == "stage":
                ls.cell(r, col + 1, it.prob).number_format = "0%"
        col += 3 if kind == "stage" else 2
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
