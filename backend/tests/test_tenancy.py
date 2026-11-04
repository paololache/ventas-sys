"""Aislamiento multi-tenant / multi-workspace."""
from .conftest import auth


def opp(client, t, **kw):
    return client.post(f"/api/w/{t['workspace_id']}/opportunities", json={"descripcion": "x", "monto": 1000, **kw}, headers=t["headers"])


def test_cada_empresa_ve_solo_lo_suyo(client, tenant_a, tenant_b):
    a = opp(client, tenant_a, descripcion="Op de A")
    assert a.status_code == 201 and a.json()["code"] == "OP-001"
    b = opp(client, tenant_b, descripcion="Op de B")
    assert b.json()["code"] == "OP-001"  # numeración independiente por workspace
    la = client.get(f"/api/w/{tenant_a['workspace_id']}/opportunities", headers=tenant_a["headers"]).json()
    assert [o["descripcion"] for o in la] == ["Op de A"]


def test_no_se_puede_acceder_a_workspace_ajeno(client, tenant_a, tenant_b):
    r = client.get(f"/api/w/{tenant_b['workspace_id']}/opportunities", headers=tenant_a["headers"])
    assert r.status_code == 404
    r = client.post(f"/api/w/{tenant_b['workspace_id']}/opportunities", json={}, headers=tenant_a["headers"])
    assert r.status_code == 404


def test_no_se_puede_leer_ni_modificar_objeto_ajeno_por_id(client, tenant_a, tenant_b):
    ob = opp(client, tenant_b).json()
    # A intenta tocar la oportunidad de B usando SU propio workspace
    wa = tenant_a["workspace_id"]
    assert client.get(f"/api/w/{wa}/opportunities/{ob['id']}", headers=tenant_a["headers"]).status_code == 404
    assert client.patch(f"/api/w/{wa}/opportunities/{ob['id']}", json={"monto": 1}, headers=tenant_a["headers"]).status_code == 404
    assert client.delete(f"/api/w/{wa}/opportunities/{ob['id']}", headers=tenant_a["headers"]).status_code == 404


def test_referencias_cruzadas_rechazadas(client, tenant_a, tenant_b):
    pb = client.post(f"/api/w/{tenant_b['workspace_id']}/partners", json={"name": "P-B"}, headers=tenant_b["headers"]).json()
    r = opp(client, tenant_a, partner_id=pb["id"])
    assert r.status_code == 404  # el partner de B no existe para A


def test_varios_workspaces_en_la_misma_empresa_estan_separados(client, tenant_a):
    h = tenant_a["headers"]
    ws2 = client.post(f"/api/tenants/{client.get('/api/auth/me', headers=h).json()['tenants'][0]['id']}/workspaces", json={"name": "Canal"}, headers=h).json()
    opp(client, tenant_a, descripcion="solo en ventas")
    assert client.get(f"/api/w/{ws2['id']}/opportunities", headers=h).json() == []
    # catálogos y reglas sembrados por separado
    assert "Prospección" in [s["value"] for s in client.get(f"/api/w/{ws2['id']}/catalogs", headers=h).json()["stage"]]
    assert len(client.get(f"/api/w/{ws2['id']}/rules", headers=h).json()) == 13


def test_miembro_solo_ve_sus_workspaces(client, tenant_a):
    h = tenant_a["headers"]
    tid = client.get("/api/auth/me", headers=h).json()["tenants"][0]["id"]
    ws2 = client.post(f"/api/tenants/{tid}/workspaces", json={"name": "Canal"}, headers=h).json()
    client.post(f"/api/tenants/{tid}/members", json={"email": "v@a.com", "password": "vend1234", "role": "member", "workspace_ids": [ws2["id"]]}, headers=h)
    hv = auth(client, "v@a.com", "vend1234")
    assert client.get(f"/api/w/{ws2['id']}/opportunities", headers=hv).status_code == 200
    assert client.get(f"/api/w/{tenant_a['workspace_id']}/opportunities", headers=hv).status_code == 404
    me = client.get("/api/auth/me", headers=hv).json()
    assert [w["id"] for w in me["tenants"][0]["workspaces"]] == [ws2["id"]]
    # un vendedor no puede administrar
    assert client.post(f"/api/tenants/{tid}/workspaces", json={"name": "Otro"}, headers=hv).status_code == 403


def test_solo_superadmin_crea_empresas(client, tenant_a):
    r = client.post("/api/tenants", json={"name": "X", "owner_email": "x@x.com", "owner_password": "xxxxxxxx"}, headers=tenant_a["headers"])
    assert r.status_code == 403


def test_alertas_aisladas(client, tenant_a, tenant_b):
    opp(client, tenant_a)
    la = client.get(f"/api/w/{tenant_a['workspace_id']}/alerts", headers=tenant_a["headers"]).json()
    lb = client.get(f"/api/w/{tenant_b['workspace_id']}/alerts", headers=tenant_b["headers"]).json()
    assert la["count"] > 0 and lb["count"] == 0


def test_sin_token_401(client):
    assert client.get("/api/w/1/opportunities").status_code == 401
