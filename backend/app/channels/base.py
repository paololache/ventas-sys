"""Interfaz común de canales de notificación. Para sumar un canal: heredar `Channel` y registrarlo en `registry`."""
from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field


@dataclass
class Button:
    text: str
    callback: str | None = None
    url: str | None = None


@dataclass
class Message:
    """Mensaje neutro: texto en HTML simple (<b>, <i>, <code>) + filas de botones."""

    html: str
    buttons: list[list[Button]] = field(default_factory=list)
    subject: str = ""


@dataclass
class Target:
    tenant_id: int
    workspace_id: int
    user_id: int
    chat_id: str | None = None
    email: str | None = None


class Channel(ABC):
    name = "base"

    def available(self, tenant, target: Target) -> bool:
        return False

    def send(self, tenant, target: Target, msg: Message, kind: str = "alert") -> None:
        """kind: alert | daily | weekly"""
        raise NotImplementedError
