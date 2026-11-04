from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..channels.telegram import get_client
from ..clock import Clock, get_clock
from ..db import get_db
from ..models import Tenant
from ..services.bot import Bot

router = APIRouter(prefix="/api/telegram")


@router.post("/webhook/{tenant_slug}/{secret}")
async def webhook(tenant_slug: str, secret: str, request: Request, db: Session = Depends(get_db), clock: Clock = Depends(get_clock),
                  x_telegram_bot_api_secret_token: str | None = Header(default=None)):
    """Un webhook por empresa: el tenant sale de la URL y se valida con su secreto. Así cada empresa tiene su propio bot."""
    t = db.scalar(select(Tenant).where(Tenant.slug == tenant_slug, Tenant.is_active))
    expected = (t.settings or {}).get("telegram_webhook_secret") if t else None
    if not t or not expected or secret != expected or (x_telegram_bot_api_secret_token not in (None, expected)):
        raise HTTPException(404, "No encontrado")
    client = get_client(t)
    if client is None:
        raise HTTPException(422, "Bot no configurado")
    Bot(db, t, client, clock).handle(await request.json())
    db.commit()
    return {"ok": True}
