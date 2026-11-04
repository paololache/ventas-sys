from datetime import datetime, timedelta

from sqlalchemy import select

from app.models import Alert, Opportunity
from .helpers import W, import_fixture, setup_bot, tick


def lima(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi) + timedelta(hours=5)  # Lima = UTC-5


def test_primera_corrida_agrupa_las_sin_accion_ordenadas_por_prioridad_y_monto(client, db, tmp_path, fake_tg, tenant_a, clock):
    say = setup_bot(client, db, tenant_a)
    rep = import_fixture(client, tenant_a, tmp_path)["quality"]
    fake_tg.sent.clear()
    tick(db)
    r3 = [m for m in fake_tg.sent if "Sin próxima acción" in m[1]]
    assert len(r3) == 1, "las sin-acción van en UN mensaje agrupado"
    n = rep["sin_proxima_accion"]
    assert f"{n} alertas" in r3[0][1]
    # orden por prioridad (Alta primero) y luego monto desc
    opps = {o.code: o for o in db.scalars(select(Opportunity))}
    codes = [c for c in __import__("re").findall(r"OP-\d{3}", r3[0][1])]
    keys = [(("Alta", "Media", "Baja").index(opps[c].prioridad), -opps[c].monto) for c in codes]
    assert keys == sorted(keys)
    # menos de ~10 mensajes en total aunque haya decenas de alertas
    assert len(fake_tg.sent) < 10


def test_dedupe_no_reenvia_en_el_mismo_dia_y_si_al_dia_siguiente(client, db, tmp_path, fake_tg, tenant_a, clock):
    setup_bot(client, db, tenant_a)
    import_fixture(client, tenant_a, tmp_path)
    tick(db)
    n1 = len(fake_tg.sent)
    assert n1 > 0
    clock.advance(minutes=15)
    tick(db)
    assert len(fake_tg.sent) == n1  # sin reenvío
    clock.advance(days=1)  # miércoles 14:15
    tick(db)
    assert len(fake_tg.sent) > n1  # Alta: se repite diario


def test_fuera_de_horario_solo_urgentes_de_hoy(client, db, fake_tg, tenant_a, clock):
    setup_bot(client, db, tenant_a)
    fake_tg.sent.clear()
    # oportunidad con DR que vence HOY (urgente) y otra sin acción (no urgente)
    o1 = client.post(f"{W(tenant_a)}/opportunities", json={"descripcion": "DR hoy", "dr_vencimiento": "2026-11-03", "prox_accion": "x", "fecha_prox_accion": "2026-12-01", "fecha_cierre_est": "2026-12-20", "monto": 1}, headers=tenant_a["headers"]).json()
    client.post(f"{W(tenant_a)}/opportunities", json={"descripcion": "sin accion"}, headers=tenant_a["headers"])
    clock.at = lima(2026, 11, 3, 21, 30)  # martes 21:30
    tick(db)
    txt = " ".join(m[1] for m in fake_tg.sent)
    assert "deal registration vence hoy" in txt
    assert "Sin próxima acción" not in txt
    # sábado 11:00: tampoco se envía lo no urgente
    fake_tg.sent.clear()
    clock.at = lima(2026, 11, 7, 11)
    tick(db)
    assert all("Sin próxima acción" not in m[1] for m in fake_tg.sent)
    # lunes por la mañana sí
    clock.at = lima(2026, 11, 9, 9)
    tick(db)
    assert any("Sin próxima acción" in m[1] for m in fake_tg.sent)


def test_feriado_no_notifica_lo_no_urgente(client, db, fake_tg, tenant_a, clock):
    setup_bot(client, db, tenant_a)
    client.post(f"{W(tenant_a)}/opportunities", json={"descripcion": "sin accion"}, headers=tenant_a["headers"])
    fake_tg.sent.clear()
    clock.at = lima(2026, 12, 8, 10)  # Inmaculada Concepción (martes)
    tick(db)
    assert not [m for m in fake_tg.sent if "Sin próxima acción" in m[1]]


def test_snooze_vigente_no_notifica(client, db, fake_tg, tenant_a, clock):
    setup_bot(client, db, tenant_a)
    client.post(f"{W(tenant_a)}/opportunities", json={"descripcion": "sin accion"}, headers=tenant_a["headers"])
    a = db.scalar(select(Alert).where(Alert.rule_code == "R3"))
    client.post(f"{W(tenant_a)}/alerts/{a.id}/snooze", json={"days": 7}, headers=tenant_a["headers"])
    fake_tg.sent.clear()
    tick(db)
    assert not fake_tg.sent
    clock.advance(days=8)  # vence el snooze (martes 11/11)
    tick(db)
    assert any("Sin próxima acción" in m[1] for m in fake_tg.sent)


def test_resumen_diario_a_las_8_hora_lima_una_sola_vez(client, db, fake_tg, tenant_a, clock):
    setup_bot(client, db, tenant_a)
    client.post(f"{W(tenant_a)}/opportunities", json={"descripcion": "sin accion"}, headers=tenant_a["headers"])
    fake_tg.sent.clear()
    clock.at = lima(2026, 11, 4, 7, 45)
    tick(db)
    assert not [m for m in fake_tg.sent if "Resumen" in m[1]]
    clock.at = lima(2026, 11, 4, 8, 5)
    tick(db)
    assert len([m for m in fake_tg.sent if "Resumen del" in m[1]]) == 1
    clock.advance(minutes=30)
    tick(db)
    assert len([m for m in fake_tg.sent if "Resumen del" in m[1]]) == 1


def test_escalamiento_media_a_alta_tras_3_avisos(client, db, fake_tg, tenant_a, clock):
    setup_bot(client, db, tenant_a)
    client.patch(f"{W(tenant_a)}/settings", json={"repeat_media_days": 1}, headers=tenant_a["headers"])
    # R13 (Media): monto grande, con acción y cierre, pero sin MEDDPICC/contacto
    client.post(f"{W(tenant_a)}/opportunities", json={"descripcion": "grande", "monto": 80000, "prox_accion": "x", "fecha_prox_accion": "2026-12-30",
                                                     "fecha_cierre_est": "2026-12-31"}, headers=tenant_a["headers"])
    for d in (4, 5, 6):  # mié, jue, vie 08:05 → 3 resúmenes
        clock.at = lima(2026, 11, d, 8, 5)
        tick(db)
    a = db.scalar(select(Alert).where(Alert.rule_code == "R13"))
    assert a.notify_count == 3 and a.escalated and a.severity == "Alta"
    # ya Alta: aparece arriba en el resumen del lunes
    fake_tg.sent.clear()
    clock.at = lima(2026, 11, 9, 8, 5)
    tick(db)
    digest = next(m for m in fake_tg.sent if "Resumen del" in m[1])
    assert "🔴" in digest[1] or "grande" in digest[1] or "OP-001" in digest[1]


def test_resumen_semanal_por_email_lunes_730(client, db, emails, fake_tg, tenant_a, clock):
    setup_bot(client, db, tenant_a)
    tid = client.get("/api/auth/me", headers=tenant_a["headers"]).json()["tenants"][0]["id"]
    client.patch(f"/api/tenants/{tid}", json={"smtp_host": "smtp.test", "smtp_user": "u", "smtp_password": "p"}, headers=tenant_a["headers"])
    client.post(f"{W(tenant_a)}/opportunities", json={"descripcion": "algo", "monto": 5000, "stage": "Negociación"}, headers=tenant_a["headers"])
    clock.at = lima(2026, 11, 9, 7, 0)  # lunes antes de las 7:30
    tick(db)
    assert not emails
    clock.at = lima(2026, 11, 9, 7, 35)
    tick(db)
    assert len(emails) == 1
    body = emails[0].get_body(("html",)).get_content()
    assert "Resumen semanal" in body and "A quién llamar" in body and "Pipeline abierto" in body
    clock.advance(minutes=15)
    tick(db)
    assert len(emails) == 1  # sólo una vez por semana


def test_resolucion_automatica_evita_avisos(client, db, fake_tg, tenant_a, clock):
    setup_bot(client, db, tenant_a)
    o = client.post(f"{W(tenant_a)}/opportunities", json={"descripcion": "sin accion", "fecha_cierre_est": "2026-12-20"}, headers=tenant_a["headers"]).json()
    client.patch(f"{W(tenant_a)}/opportunities/{o['id']}", json={"prox_accion": "Llamar", "fecha_prox_accion": "2026-11-20"}, headers=tenant_a["headers"])
    fake_tg.sent.clear()
    tick(db)
    assert not fake_tg.sent
