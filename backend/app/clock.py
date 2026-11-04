"""Reloj inyectable: toda la app obtiene "ahora/hoy" de aquí (sobrescribible en tests)."""
from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo


class Clock:
    def now_utc(self) -> datetime:
        """UTC naive (así se guardan los datetimes en la base)."""
        return datetime.now(timezone.utc).replace(tzinfo=None)

    def local_now(self, tz: str) -> datetime:
        return self.now_utc().replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz))

    def today(self, tz: str) -> date:
        return self.local_now(tz).date()


class FixedClock(Clock):
    """Reloj controlado para tests. `at_utc` es UTC naive."""

    def __init__(self, at_utc: datetime):
        self.at = at_utc

    def now_utc(self) -> datetime:
        return self.at

    def advance(self, **kw):
        from datetime import timedelta

        self.at = self.at + timedelta(**kw)


_clock: Clock = Clock()


def get_clock() -> Clock:
    return _clock


def set_clock(c: Clock) -> None:
    global _clock
    _clock = c
