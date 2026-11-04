import os
import sys
from datetime import datetime
from pathlib import Path

os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["DATABASE_URL"] = "sqlite://"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import channels  # noqa
from app.channels import email as email_ch
from app.channels import telegram as tg
from app.clock import FixedClock, set_clock
from app.db import Base, get_db
from app.main import app
from app.models import User
from app.security import hash_password


class FakeTelegram:
    """Registra lo que se enviaría a Telegram."""

    def __init__(self):
        self.sent = []  # (chat_id, html, buttons)
        self.answered = []

    def send_message(self, chat_id, html, buttons=None):
        self.sent.append((str(chat_id), html, buttons))
        return {"ok": True}

    def answer_callback(self, cid, text=""):
        self.answered.append(cid)

    def set_webhook(self, url, secret):
        return {"ok": True}


@pytest.fixture()
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture()
def db(engine):
    S = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    with S() as s:
        yield s


@pytest.fixture()
def clock():
    # martes 2026-11-03 14:00 en Lima = 19:00 UTC
    c = FixedClock(datetime(2026, 11, 3, 19, 0))
    set_clock(c)
    yield c


@pytest.fixture()
def fake_tg():
    f = FakeTelegram()
    tg.set_client_factory(lambda tenant: f)
    yield f
    tg.set_client_factory(None)


@pytest.fixture()
def emails():
    sent = []
    email_ch.set_email_sender(lambda cfg, em: sent.append(em))
    yield sent
    email_ch.set_email_sender(None)


@pytest.fixture()
def client(engine, clock):
    S = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    def _get_db():
        with S() as s:
            yield s

    app.dependency_overrides[get_db] = _get_db
    with S() as s:
        s.add(User(email="root@x.com", name="Root", password_hash=hash_password("rootpass"), is_superadmin=True))
        s.commit()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def auth(client, email, password):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def root(client):
    return auth(client, "root@x.com", "rootpass")


@pytest.fixture()
def tenant_a(client, root):
    r = client.post("/api/tenants", json={"name": "Empresa A", "slug": "empresa-a", "owner_email": "a@a.com", "owner_password": "passA123", "workspace_name": "Ventas"}, headers=root)
    assert r.status_code == 201, r.text
    return {**r.json(), "headers": auth(client, "a@a.com", "passA123")}


@pytest.fixture()
def tenant_b(client, root):
    r = client.post("/api/tenants", json={"name": "Empresa B", "slug": "empresa-b", "owner_email": "b@b.com", "owner_password": "passB123", "workspace_name": "Canal"}, headers=root)
    assert r.status_code == 201, r.text
    return {**r.json(), "headers": auth(client, "b@b.com", "passB123")}
