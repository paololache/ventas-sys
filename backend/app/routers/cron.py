"""Disparador externo del scheduler para despliegues serverless (Vercel Cron / GitHub Actions / cron-job.org)."""
from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..services.scheduler import run_tick

router = APIRouter(prefix="/api/cron")


@router.api_route("/tick", methods=["GET", "POST"])
def tick(authorization: str = Header(default=""), db: Session = Depends(get_db)):
    secret = get_settings().cron_secret
    given = authorization.removeprefix("Bearer ").strip()
    if not secret or not hmac.compare_digest(given, secret):
        raise HTTPException(401, "No autorizado")
    out = run_tick(db)
    return {"workspaces": len(out), "stats": out}
