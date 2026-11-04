from sqlalchemy import select

from app.models import Alert, Tenant
from app.services.scheduler import run_tick
from .make_fixture import build


def W(t):
    return f"/api/w/{t['workspace_id']}"


def setup_bot(client, db, t, chat_id="555"):
    """Configura el bot de la empresa, vincula un chat y devuelve (webhook_url, post_update)."""
    tid = client.get("/api/auth/me", headers=t["headers"]).json()["tenants"][0]["id"]
    client.patch(f"/api/tenants/{tid}", json={"telegram_bot_token": "FAKE:TOKEN"}, headers=t["headers"])
    code = client.post(f"{W(t)}/telegram/link-code", headers=t["headers"]).json()["code"]
    tenant = db.get(Tenant, tid)
    db.refresh(tenant)
    url = f"/api/telegram/webhook/{tenant.slug}/{tenant.settings['telegram_webhook_secret']}"

    def say(text=None, callback=None):
        if callback is not None:
            upd = {"callback_query": {"id": "cb1", "data": callback, "message": {"chat": {"id": int(chat_id)}}}}
        else:
            upd = {"message": {"chat": {"id": int(chat_id)}, "text": text}}
        r = client.post(url, json=upd)
        assert r.status_code == 200, r.text
        db.expire_all()

    say(f"/start {code}")
    return say


def import_fixture(client, t, tmp_path):
    p = build(tmp_path / "crm.xlsx")
    with open(p, "rb") as f:
        r = client.post(f"{W(t)}/import/excel", files={"file": ("crm.xlsx", f)}, headers=t["headers"])
    assert r.status_code == 200, r.text
    return r.json()


def tick(db):
    db.expire_all()
    out = run_tick(db)
    db.expire_all()
    return out
