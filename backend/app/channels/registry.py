from .base import Channel
from .email import EmailChannel
from .stubs import GoogleCalendarChannel, WhatsAppChannel
from .telegram import TelegramChannel

# El canal "in-app" no necesita adaptador: la bandeja lee directamente la tabla `alerts`.
CHANNELS: dict[str, Channel] = {c.name: c for c in (TelegramChannel(), EmailChannel(), GoogleCalendarChannel(), WhatsAppChannel())}


def get(name: str) -> Channel:
    return CHANNELS[name]
