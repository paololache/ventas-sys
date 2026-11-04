from sqlalchemy import select

from app.alerts.engine import evaluate_workspace
from app.deps import Ctx
from app.models import Activity, Alert, Client, Contact, Opportunity, Partner, Tenant, User, Workspace, Membership
from app.services import excel as xl
from app.services.seed import seed_workspace
from datetime import date, datetime

from .make_fixture import build

TODAY = date(2026, 11, 3)


def setup(db):
    t = Tenant(name="Adistec", slug="adistec", settings={})
    u = User(email="o@x.com", password_hash="x")
    db.add_all([t, u]); db.flush()
    ws = Workspace(tenant_id=t.id, name="Canal", slug="canal", settings={})
    db.add(ws); db.flush()
    seed_workspace(db, t, ws, u.id)
    return Ctx(u, t, ws, "owner")


def test_importa_excel_y_normaliza(db, tmp_path):
    ctx = setup(db)
    path = build(tmp_path / "crm.xlsx")
    res = xl.import_excel(db, ctx, path, TODAY)
    db.commit()
    assert res.opportunities_created == 26 and res.activities_created == 3
    ops = db.scalars(select(Opportunity).order_by(Opportunity.code)).all()
    assert ops[0].code == "OP-001" and len(ops) == 26
    # partners/clientes únicos: "Think Networks" y "think networks " se unifican; "Cliente 1  SA" normaliza espacios
    names = {p.name.casefold() for p in db.scalars(select(Partner))}
    assert "think networks" in names and len(names) == len(db.scalars(select(Partner)).all())
    assert all("  " not in c.name for c in db.scalars(select(Client)))
    # responsable del cliente → contacto
    assert db.scalar(select(Contact).where(Contact.name == "Miriam Quispe")) is not None
    # última actualización = máx(excel, última actividad)
    op1 = db.scalar(select(Opportunity).where(Opportunity.code == "OP-001"))
    assert op1.ultima_actualizacion == date(2026, 11, 2)
    # Listas: probabilidades 10..100 → 0.1..1
    from app.models import ListItem
    assert db.scalar(select(ListItem).where(ListItem.kind == "stage", ListItem.value == "Negociación")).prob == 0.7


def test_importacion_idempotente(db, tmp_path):
    ctx = setup(db)
    path = build(tmp_path / "crm.xlsx")
    xl.import_excel(db, ctx, path, TODAY); db.commit()
    res2 = xl.import_excel(db, ctx, path, TODAY); db.commit()
    assert res2.opportunities_created == 0 and res2.opportunities_updated == 26
    assert res2.activities_created == 0 and res2.activities_skipped == 3
    assert len(db.scalars(select(Opportunity)).all()) == 26
    assert len(db.scalars(select(Activity)).all()) == 3


def test_reporte_de_calidad_coincide_con_primera_corrida_de_alertas(db, tmp_path):
    ctx = setup(db)
    xl.import_excel(db, ctx, build(tmp_path / "crm.xlsx"), TODAY); db.commit()
    rep = xl.quality_report(db, ctx, TODAY)
    # abiertas = las que no son Ganada/Perdida/En pausa; el fixture tiene 26 con etapas rotando
    assert rep["oportunidades_total"] == 26
    evaluate_workspace(db, ctx.ws, TODAY, datetime(2026, 11, 3, 19))
    db.commit()
    alerts = db.scalars(select(Alert).where(Alert.status == "open")).all()
    by = {}
    for a in alerts:
        by[a.rule_code] = by.get(a.rule_code, 0) + 1
    assert rep["alertas_primera_corrida"] == by
    assert rep["sin_proxima_accion"] == by.get("R3", 0) and rep["sin_proxima_accion"] > 0
    assert rep["sin_fecha_cierre"] == by.get("R6", 0)
    assert rep["actividades_proximo_paso_sin_fecha"] == 2
    print(xl.format_report(rep))


def test_export_reimporta_sin_perdida(db, tmp_path):
    ctx = setup(db)
    xl.import_excel(db, ctx, build(tmp_path / "crm.xlsx"), TODAY); db.commit()
    out = tmp_path / "out.xlsx"
    out.write_bytes(xl.export_excel(db, ctx, TODAY))
    ctx2 = setup_second(db)
    res = xl.import_excel(db, ctx2, out, TODAY)
    assert res.opportunities_created == 26 and res.activities_created == 3


def setup_second(db):
    t = Tenant(name="Otra", slug="otra", settings={})
    u = User(email="o2@x.com", password_hash="x")
    db.add_all([t, u]); db.flush()
    ws = Workspace(tenant_id=t.id, name="W", slug="w", settings={})
    db.add(ws); db.flush()
    seed_workspace(db, t, ws, u.id)
    return Ctx(u, t, ws, "owner")
