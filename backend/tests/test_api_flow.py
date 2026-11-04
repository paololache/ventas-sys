from datetime import date


def W(t):
    return f"/api/w/{t['workspace_id']}"


def mk(client, t, **kw):
    r = client.post(f"{W(t)}/opportunities", json={"descripcion": "Renovación", "monto": 20000, "stage": "Propuesta enviada", "prioridad": "Alta", **kw}, headers=t["headers"])
    assert r.status_code == 201, r.text
    return r.json()


def rules_of(client, t, opp_id):
    return {a["rule"] for a in client.get(f"{W(t)}/alerts", headers=t["headers"]).json()["alerts"] if a["opportunity_id"] == opp_id}


def test_oportunidad_sin_accion_dispara_R3_y_actividad_obliga_proxima_accion(client, tenant_a):
    o = mk(client, tenant_a)
    assert "R3" in rules_of(client, tenant_a, o["id"])
    # sin próxima acción ni motivo → 422
    r = client.post(f"{W(tenant_a)}/opportunities/{o['id']}/activities", json={"tipo": "Llamada", "resumen": "hablé con el cliente"}, headers=tenant_a["headers"])
    assert r.status_code == 422
    # con próxima acción + fecha → se resuelve R3 sola
    r = client.post(f"{W(tenant_a)}/opportunities/{o['id']}/activities",
                    json={"tipo": "Llamada", "resumen": "ok", "proximo_paso": "Enviar propuesta", "fecha_proximo_paso": "2026-11-10"}, headers=tenant_a["headers"])
    assert r.status_code == 201
    assert "R3" not in rules_of(client, tenant_a, o["id"])
    d = client.get(f"{W(tenant_a)}/opportunities/{o['id']}", headers=tenant_a["headers"]).json()
    assert d["prox_accion"] == "Enviar propuesta" and d["fecha_prox_accion"] == "2026-11-10"
    assert d["ultima_actualizacion"] == "2026-11-03"
    assert len(d["activities"]) == 1


def test_sin_proximo_paso_con_motivo_es_valido(client, tenant_a):
    o = mk(client, tenant_a)
    r = client.post(f"{W(tenant_a)}/opportunities/{o['id']}/activities",
                    json={"tipo": "Email", "resumen": "cliente pausó", "sin_proximo_paso_motivo": "Presupuesto congelado"}, headers=tenant_a["headers"])
    assert r.status_code == 201
    assert "R3" not in rules_of(client, tenant_a, o["id"])


def test_sugerencia_de_fecha_en_texto_libre(client, tenant_a):
    o = mk(client, tenant_a)
    r = client.post(f"{W(tenant_a)}/opportunities/{o['id']}/activities",
                    json={"resumen": "se publica el 15/11 en el SEACE", "sin_proximo_paso_motivo": "esperando publicación"}, headers=tenant_a["headers"]).json()
    assert r["suggestions"][0]["fecha"] == "2026-11-15"
    # sólo propone: no creó ninguna acción
    d = client.get(f"{W(tenant_a)}/opportunities/{o['id']}", headers=tenant_a["headers"]).json()
    assert d["fecha_prox_accion"] is None


def test_ultima_actualizacion_y_historial_de_etapas(client, tenant_a, clock):
    o = mk(client, tenant_a)
    clock.advance(days=5)
    r = client.patch(f"{W(tenant_a)}/opportunities/{o['id']}", json={"stage": "Negociación"}, headers=tenant_a["headers"]).json()
    assert r["ultima_actualizacion"] == "2026-11-08"
    # comentarios no son cambio relevante
    clock.advance(days=2)
    r = client.patch(f"{W(tenant_a)}/opportunities/{o['id']}", json={"comentarios": "nota"}, headers=tenant_a["headers"]).json()
    assert r["ultima_actualizacion"] == "2026-11-08"
    d = client.get(f"{W(tenant_a)}/opportunities/{o['id']}", headers=tenant_a["headers"]).json()
    assert [h["to"] for h in d["stage_history"]] == ["Propuesta enviada", "Negociación"]


def test_meddpicc_score_se_calcula_solo(client, tenant_a):
    o = mk(client, tenant_a)
    r = client.put(f"{W(tenant_a)}/opportunities/{o['id']}/meddpicc", json=[
        {"criterion": "Metrics", "score": 2}, {"criterion": "Champion", "score": 1, "note": "Miriam"}], headers=tenant_a["headers"])
    assert r.json()["score"] == 3 and r.json()["max"] == 16
    assert client.put(f"{W(tenant_a)}/opportunities/{o['id']}/meddpicc", json=[{"criterion": "Metrics", "score": 3}], headers=tenant_a["headers"]).status_code == 422
    assert client.put(f"{W(tenant_a)}/opportunities/{o['id']}/meddpicc", json=[{"criterion": "Foo", "score": 1}], headers=tenant_a["headers"]).status_code == 422


def test_etapa_ganada_cierra_y_resuelve_alertas(client, tenant_a):
    o = mk(client, tenant_a)
    assert rules_of(client, tenant_a, o["id"])
    client.patch(f"{W(tenant_a)}/opportunities/{o['id']}", json={"stage": "Ganada"}, headers=tenant_a["headers"])
    assert rules_of(client, tenant_a, o["id"]) == set()
    dash = client.get(f"{W(tenant_a)}/dashboard", headers=tenant_a["headers"]).json()
    assert dash["ganado"] == 20000 and dash["abiertas"] == 0 and dash["win_rate"] == 100.0


def test_snooze_oculta_la_alerta(client, tenant_a):
    o = mk(client, tenant_a)
    alerts = client.get(f"{W(tenant_a)}/alerts", headers=tenant_a["headers"]).json()["alerts"]
    a = next(x for x in alerts if x["rule"] == "R3")
    client.post(f"{W(tenant_a)}/alerts/{a['id']}/snooze", json={"days": 3}, headers=tenant_a["headers"])
    assert "R3" not in rules_of(client, tenant_a, o["id"])
    assert any(x["id"] == a["id"] for x in client.get(f"{W(tenant_a)}/alerts?include_snoozed=true", headers=tenant_a["headers"]).json()["alerts"])


def test_reglas_configurables_desde_la_app(client, tenant_a):
    o = mk(client, tenant_a, fecha_cierre_est=None)
    assert "R6" in rules_of(client, tenant_a, o["id"])
    client.patch(f"{W(tenant_a)}/rules/R6", json={"enabled": False}, headers=tenant_a["headers"])
    assert "R6" not in rules_of(client, tenant_a, o["id"])


def test_dashboard_y_export(client, tenant_a):
    mk(client, tenant_a, monto=10000, stage="Negociación", fecha_cierre_est="2026-12-15")
    d = client.get(f"{W(tenant_a)}/dashboard", headers=tenant_a["headers"]).json()
    assert d["pipeline_abierto"] == 10000 and d["forecast_ponderado"] == 7000
    assert d["forecast_por_mes"][0]["mes"] == "2026-12"
    r = client.get(f"{W(tenant_a)}/export/excel", headers=tenant_a["headers"])
    assert r.status_code == 200 and r.content[:2] == b"PK"
