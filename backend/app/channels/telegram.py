from __future__ import annotations

import httpx

from ..config import get_settings
from .base import Channel, Message, Target


class TelegramClient:
    """Cliente mínimo del Bot API (cada empresa usa su propio token)."""

    def __init__(self, token: str, api_base: str | None = None):
        self.token = token
        self.base = (api_base or get_settings().telegram_api_base).rstrip("/")

    def _call(self, method: str, payload: dict) -> dict:
        r = httpx.post(f"{self.base}/bot{self.token}/{method}", json=payload, timeout=15)
        r.raise_for_status()
        return r.json()

    def send_message(self, chat_id, html: str, buttons: list[list[dict]] | None = None) -> dict:
        payload = {"chat_id": chat_id, "text": html[:4000], "parse_mode": "HTML", "disable_web_page_preview": True}
        if buttons:
            payload["reply_markup"] = {"inline_keyboard": buttons}
        return self._call("sendMessage", payload)

    def answer_callback(self, callback_id: str, text: str = "") -> dict:
        return self._call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

    def set_webhook(self, url: str, secret: str) -> dict:
        return self._call("setWebhook", {"url": url, "secret_token": secret, "allowed_updates": ["message", "callback_query"]})


_override = None  # tests: callable(tenant) -> cliente falso


def set_client_factory(fn) -> None:
    global _override
    _override = fn


def get_client(tenant) -> TelegramClient | None:
    if _override:
        return _override(tenant)
    token = (tenant.settings or {}).get("telegram_bot_token")
    return TelegramClient(token) if token else None


def to_markup(msg: Message) -> list[list[dict]] | None:
    rows = []
    for row in msg.buttons:
        r = []
        for b in row:
            r.append({"text": b.text, "url": b.url} if b.url else {"text": b.text, "callback_data": b.callback})
        rows.append(r)
    return rows or None


class TelegramChannel(Channel):
    name = "telegram"

    def available(self, tenant, target: Target) -> bool:
        return bool(target.chat_id) and get_client(tenant) is not None

    def send(self, tenant, target: Target, msg: Message, kind: str = "alert") -> None:
        get_client(tenant).send_message(target.chat_id, msg.html, to_markup(msg))
