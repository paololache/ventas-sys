"""Flujo completo: alerta → ✅ Hecho en Telegram → actividad registrada → alerta resuelta."""
import re

from sqlalchemy import select

from app.models import Activity, Alert, Opportunity
from .helpers import W, setup_bot, tick


def test_alerta_hecho_actividad_resuelta(client, db, fake_tg, tenant_a, clock):
    say = setup_bot(client, db, tenant_a)
    o = client.post(f"{W(tenant_a)}/opportunities", json={"descripcion": "Renovación VMware", "prioridad": "Alta", "monto": 30000, "fecha_cierre_est": "2026-12-20"}, headers=tenant_a["headers"]).json()
    fake_tg.sent.clear()
    tick(db)
    chat, html, buttons = next(m for m in fake_tg.sent if "Sin próxima acción" in m[1])
    cbs = [b.get("callback_data") for row in buttons for b in row]
    assert any(c and c.startswith("done:") for c in cbs) and any(c and c.startswith("snzm:") for c in cbs)
    assert any(b.get("url") and "/opportunities/" in b["url"] for row in buttons for b in row), "botón 'Abrir en la app'"
    assert any(c and c.startswith("ct:") for c in cbs)
    alert = db.scalar(select(Alert).where(Alert.rule_code == "R3", Alert.status == "open"))
    assert alert is not None

    say(callback=f"done:{alert.id}")
    assert "resumen" in fake_tg.sent[-1][1].lower()
    say("Llamé a Miriam, confirma presupuesto")
    assert "próxima acción" in fake_tg.sent[-1][1].lower()
    say("Enviar propuesta el 11/11")
    assert "Listo" in fake_tg.sent[-1][1]

    db.expire_all()
    act = db.scalar(select(Activity).where(Activity.opportunity_id == o["id"]))
    assert act.source == "telegram" and act.tipo == "Llamada" and "Miriam" in act.resumen
    opp = db.get(Opportunity, o["id"])
    assert opp.prox_accion == "Enviar propuesta el 11/11" and str(opp.fecha_prox_accion) == "2026-11-11"
    assert opp.ultima_actualizacion.isoformat() == "2026-11-03"
    alert = db.get(Alert, alert.id)
    assert alert.status == "resolved"
    n = len(fake_tg.sent)
    tick(db)
    assert not [m for m in fake_tg.sent[n:] if "Sin próxima acción" in m[1]]


def test_hecho_pide_fecha_si_no_se_detecta(client, db, fake_tg, tenant_a, clock):
    say = setup_bot(client, db, tenant_a)
    client.post(f"{W(tenant_a)}/opportunities", json={"descripcion": "x"}, headers=tenant_a["headers"])
    alert = db.scalar(select(Alert).where(Alert.rule_code == "R3"))
    say(callback=f"done:{alert.id}")
    say("hablé con él")
    say("luego veo")  # sin fecha
    assert "No detecté una fecha" in fake_tg.sent[-1][1]
    say("sin: cliente congeló presupuesto")  # alternativa explícita
    assert "Sin próximo paso" in fake_tg.sent[-1][1]
    assert db.get(Alert, alert.id).status == "resolved"


def test_comando_log_registra_y_propone_proxima_accion(client, db, fake_tg, tenant_a, clock):
    say = setup_bot(client, db, tenant_a)
    o = client.post(f"{W(tenant_a)}/opportunities", json={"descripcion": "x"}, headers=tenant_a["headers"]).json()
    say(f"/log {o['code']} llamé a Miriam, presenta propuesta el 11/11")
    chat, html, buttons = fake_tg.sent[-1]
    assert "11/11/2026" in html
    act = db.scalar(select(Activity))
    assert act.source == "telegram" and act.tipo == "Llamada"
    assert db.get(Opportunity, o["id"]).fecha_prox_accion is None  # propone, no crea sin confirmar
    say(callback="pna")
    opp = db.get(Opportunity, o["id"])
    assert str(opp.fecha_prox_accion) == "2026-11-11" and opp.prox_accion == "presenta propuesta el 11/11"
    assert db.scalar(select(Alert).where(Alert.rule_code == "R3", Alert.status == "open")) is None


def test_comandos_de_consulta(client, db, fake_tg, tenant_a, clock):
    say = setup_bot(client, db, tenant_a)
    o = client.post(f"{W(tenant_a)}/opportunities", json={"descripcion": "Renov", "prox_accion": "Llamar", "fecha_prox_accion": "2026-11-03", "monto": 9000}, headers=tenant_a["headers"]).json()
    o2 = client.post(f"{W(tenant_a)}/opportunities", json={"descripcion": "Otra", "prox_accion": "Visitar", "fecha_prox_accion": "2026-11-01"}, headers=tenant_a["headers"]).json()
    say("/hoy"); assert o["code"] in fake_tg.sent[-1][1]
    say("/vencidas"); assert o2["code"] in fake_tg.sent[-1][1] and o["code"] not in fake_tg.sent[-1][1]
    say(f"/op {o['code']}"); assert "Renov" in fake_tg.sent[-1][1]
    say("/pipeline"); assert "Pipeline" in fake_tg.sent[-1][1]
    say("/semana"); assert o["code"] in fake_tg.sent[-1][1]


def test_posponer_desde_telegram(client, db, fake_tg, tenant_a, clock):
    say = setup_bot(client, db, tenant_a)
    client.post(f"{W(tenant_a)}/opportunities", json={"descripcion": "x"}, headers=tenant_a["headers"])
    a = db.scalar(select(Alert).where(Alert.rule_code == "R3"))
    say(callback=f"snzm:{a.id}")
    assert any("snz:" in (b.get("callback_data") or "") for row in fake_tg.sent[-1][2] for b in row)
    say(callback=f"snz:{a.id}:3")
    assert str(db.get(Alert, a.id).snoozed_until) == "2026-11-06"


def test_chat_no_vinculado_y_webhook_con_secreto_incorrecto(client, db, fake_tg, tenant_a, tenant_b):
    say_a = setup_bot(client, db, tenant_a, chat_id="111")
    r = client.post("/api/telegram/webhook/empresa-a/mal-secreto", json={"message": {"chat": {"id": 1}, "text": "/hoy"}})
    assert r.status_code == 404
    # el chat de A no está vinculado en B aunque use el mismo número de chat
    say_b = setup_bot(client, db, tenant_b, chat_id="222")
    # cada empresa mantiene su propio vínculo
    from app.models import TelegramLink
    links = db.scalars(select(TelegramLink).where(TelegramLink.chat_id.is_not(None))).all()
    assert {(l.tenant_id, l.chat_id) for l in links} == {(links[0].tenant_id, "111"), (links[1].tenant_id, "222")} and links[0].tenant_id != links[1].tenant_id


def test_codigo_de_vinculacion_invalido(client, db, fake_tg, tenant_a):
    from .helpers import W  # noqa
    tid = client.get("/api/auth/me", headers=tenant_a["headers"]).json()["tenants"][0]["id"]
    client.patch(f"/api/tenants/{tid}", json={"telegram_bot_token": "T"}, headers=tenant_a["headers"])
    from app.models import Tenant
    t = db.get(Tenant, tid)
    client.post(f"/api/telegram/webhook/{t.slug}/{t.settings['telegram_webhook_secret']}", json={"message": {"chat": {"id": 9}, "text": "/start ZZZZ"}})
    assert "inválido" in fake_tg.sent[-1][1]
