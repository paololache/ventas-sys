"""Adaptadores preparados para fases posteriores (no activos)."""
from .base import Channel, Message, Target


class GoogleCalendarChannel(Channel):
    """Fase posterior: crear eventos de Google Calendar para las próximas acciones."""

    name = "google_calendar"

    def available(self, tenant, target: Target) -> bool:
        return False

    def send(self, tenant, target: Target, msg: Message, kind: str = "alert") -> None:
        raise NotImplementedError("Google Calendar aún no implementado")


class WhatsAppChannel(Channel):
    """Fase posterior: WhatsApp Business API."""

    name = "whatsapp"

    def available(self, tenant, target: Target) -> bool:
        return False

    def send(self, tenant, target: Target, msg: Message, kind: str = "alert") -> None:
        raise NotImplementedError("WhatsApp aún no implementado")
