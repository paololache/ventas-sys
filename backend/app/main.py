from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from .config import get_settings
from .db import SessionLocal
from .models import User
from .routers import auth_admin, cron, telegram, workspace
from .security import hash_password
from .services.scheduler import run_tick

logging.basicConfig(level=logging.INFO, format='{"ts":"%(asctime)s","lvl":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}')
log = logging.getLogger("crm")


def bootstrap_admin() -> None:
    s = get_settings()
    if not (s.bootstrap_admin_email and s.bootstrap_admin_password):
        return
    with SessionLocal() as db:
        if not db.scalar(select(User).where(User.email == s.bootstrap_admin_email.lower())):
            db.add(User(email=s.bootstrap_admin_email.lower(), name="Superadmin", password_hash=hash_password(s.bootstrap_admin_password), is_superadmin=True))
            db.commit()
            log.info("superadmin creado: %s", s.bootstrap_admin_email)


def _job():
    with SessionLocal() as db:
        run_tick(db)


@asynccontextmanager
async def lifespan(app: FastAPI):
    bootstrap_admin()
    sched = None
    s = get_settings()
    if s.scheduler_enabled:
        sched = BackgroundScheduler(timezone="America/Lima")
        sched.add_job(_job, "interval", minutes=s.scheduler_interval_minutes, id="crm_tick", max_instances=1, coalesce=True)
        sched.start()
        log.info("scheduler iniciado cada %s min", s.scheduler_interval_minutes)
    yield
    if sched:
        sched.shutdown(wait=False)


app = FastAPI(title="CRM comercial proactivo", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in get_settings().cors_origins.split(",")], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(auth_admin.router)
app.include_router(workspace.router)
app.include_router(telegram.router)
app.include_router(cron.router)


@app.get("/health")
def health():
    return {"ok": True}
