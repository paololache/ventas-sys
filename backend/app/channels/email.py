from __future__ import annotations

import smtplib
from email.message import EmailMessage

from ..config import get_settings
from .base import Channel, Message, Target

_sender = None  # tests: callable(smtp_cfg, EmailMessage)


def set_email_sender(fn) -> None:
    global _sender
    _sender = fn


def smtp_config(tenant) -> dict:
    t, g = (tenant.settings or {}), get_settings()
    return {
        "host": t.get("smtp_host") or g.smtp_host, "port": int(t.get("smtp_port") or g.smtp_port),
        "user": t.get("smtp_user") or g.smtp_user, "password": t.get("smtp_password") or g.smtp_password,
        "from": t.get("smtp_from") or g.smtp_from or t.get("smtp_user") or g.smtp_user,
    }


def _smtp_send(cfg: dict, em: EmailMessage) -> None:
    with smtplib.SMTP(cfg["host"], cfg["port"], timeout=20) as s:
        s.starttls()
        if cfg["user"]:
            s.login(cfg["user"], cfg["password"])
        s.send_message(em)


class EmailChannel(Channel):
    """Resumen semanal (y cualquier mensaje con kind=weekly). SMTP configurable por empresa (Gmail + app password)."""

    name = "email"

    def available(self, tenant, target: Target) -> bool:
        return bool(target.email) and bool(smtp_config(tenant)["host"] or _sender)

    def send(self, tenant, target: Target, msg: Message, kind: str = "weekly") -> None:
        cfg = smtp_config(tenant)
        em = EmailMessage()
        em["Subject"] = msg.subject or "CRM"
        em["From"] = cfg["from"]
        em["To"] = target.email
        em.set_content("Este mensaje requiere un cliente de correo con soporte HTML.")
        em.add_alternative(msg.html, subtype="html")
        (_sender or _smtp_send)(cfg, em)
