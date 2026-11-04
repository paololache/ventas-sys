"""Días hábiles, feriados y horario laboral. Todo recibe la fecha por parámetro (sin date.today())."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

DEFAULT_WORK_DAYS = (0, 1, 2, 3, 4)


def is_business_day(d: date, holidays: frozenset[date] | set[date], work_days=DEFAULT_WORK_DAYS) -> bool:
    return d.weekday() in work_days and d not in holidays


def business_days_between(start: date, end: date, holidays=frozenset(), work_days=DEFAULT_WORK_DAYS) -> int:
    """Días hábiles transcurridos desde `start` (excluido) hasta `end` (incluido). Negativo si end < start."""
    if end < start:
        return -business_days_between(end, start, holidays, work_days)
    n, d = 0, start
    while d < end:
        d += timedelta(days=1)
        if is_business_day(d, holidays, work_days):
            n += 1
    return n


def first_business_day_of_week(d: date, holidays, work_days=DEFAULT_WORK_DAYS) -> date:
    cur = d - timedelta(days=d.weekday())
    for _ in range(7):
        if is_business_day(cur, holidays, work_days):
            return cur
        cur += timedelta(days=1)
    return cur


def parse_hhmm(s: str, default: time) -> time:
    try:
        h, m = s.split(":")
        return time(int(h), int(m))
    except Exception:
        return default


def is_work_time(local_now: datetime, holidays, work_days=DEFAULT_WORK_DAYS, start_hour=8, end_hour=19) -> bool:
    if not is_business_day(local_now.date(), holidays, work_days):
        return False
    return start_hour <= local_now.hour < end_hour
