"""Detección de fechas en texto libre en español ("el 15/11", "la semana que viene", ...).

Primera versión con reglas/regex. No crea nada: sólo *propone* fechas.
"""
from __future__ import annotations

import calendar
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}
DIAS = {"lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4, "sabado": 5, "domingo": 6}
NUMS = {"un": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "diez": 10, "quince": 15}


@dataclass(frozen=True)
class DateSuggestion:
    fecha: date
    texto: str  # fragmento detectado
    start: int
    end: int


def _norm(s: str) -> str:
    # NFD + quitar marcas conserva la longitud 1:1 para letras sin tilde combinada múltiple
    out = []
    for ch in s:
        d = unicodedata.normalize("NFD", ch)
        out.append(d[0].lower())
    return "".join(out)


def _safe(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _resolve_year(m: int, d: int, ref: date) -> date | None:
    """Fecha sin año: este año; si ya pasó hace mucho, el próximo; si pasó hace poco, se descarta."""
    cand = _safe(ref.year, m, d)
    if cand is None:
        return None
    if cand >= ref:
        return cand
    if (ref - cand).days > 180:
        return _safe(ref.year + 1, m, d)
    return None


def _next_weekday(ref: date, wd: int, strictly_after: bool = True) -> date:
    delta = (wd - ref.weekday()) % 7
    if delta == 0 and strictly_after:
        delta = 7
    return ref + timedelta(days=delta)


def extract_dates(text: str, ref: date) -> list[DateSuggestion]:
    """Devuelve fechas futuras (>= ref) mencionadas en `text`, en orden de aparición."""
    if not text:
        return []
    t = _norm(text)
    found: list[DateSuggestion] = []

    def add(m: re.Match, fecha: date | None):
        if fecha is not None and fecha >= ref:
            found.append(DateSuggestion(fecha, text[m.start():m.end()], m.start(), m.end()))

    # 15/11, 15-11, 15/11/2026, 15/11/26
    for m in re.finditer(r"(?<![\d/])(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?(?![\d/])", t):
        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
        if not (1 <= mo <= 12 and 1 <= d <= 31):
            continue
        if y:
            yy = int(y) + (2000 if len(y) == 2 else 0)
            add(m, _safe(yy, mo, d))
        else:
            add(m, _resolve_year(mo, d, ref))

    # 15 de noviembre [de 2026]
    meses = "|".join(MESES)
    for m in re.finditer(rf"(?<!\d)(\d{{1,2}})\s+de\s+({meses})(?:\s+(?:de|del)\s+(\d{{4}}))?", t):
        d, mo = int(m.group(1)), MESES[m.group(2)]
        if m.group(3):
            add(m, _safe(int(m.group(3)), mo, d))
        else:
            add(m, _resolve_year(mo, d, ref))

    for m in re.finditer(r"\bpasado\s+manana\b", t):
        add(m, ref + timedelta(days=2))
    for m in re.finditer(r"\bmanana\b", t):
        if t[max(0, m.start() - 7):m.start()].strip().endswith("pasado"):
            continue
        add(m, ref + timedelta(days=1))
    for m in re.finditer(r"\bhoy\b", t):
        add(m, ref)

    for m in re.finditer(r"\b(?:la\s+)?semana\s+(?:que\s+viene|proxima)\b|\bproxima\s+semana\b", t):
        add(m, _next_weekday(ref, 0))  # lunes de la próxima semana
    for m in re.finditer(r"\b(?:el\s+)?mes\s+(?:que\s+viene|proximo)\b|\bproximo\s+mes\b", t):
        add(m, _safe(ref.year + (ref.month == 12), ref.month % 12 + 1, 1))
    for m in re.finditer(r"\bfin(?:es)?\s+de\s+mes\b|\bfinal\s+de\s+mes\b", t):
        add(m, _safe(ref.year, ref.month, calendar.monthrange(ref.year, ref.month)[1]))

    # en 3 días / dentro de 2 semanas
    for m in re.finditer(r"\b(?:en|dentro\s+de)\s+(\d+|un|una|dos|tres|cuatro|cinco|seis|siete|diez|quince)\s+(dias?|semanas?)\b", t):
        n = int(m.group(1)) if m.group(1).isdigit() else NUMS[m.group(1)]
        add(m, ref + timedelta(days=n * (7 if m.group(2).startswith("semana") else 1)))

    # el lunes / el próximo viernes / este jueves
    dias = "|".join(DIAS)
    for m in re.finditer(rf"\b(?:(?:el|este|proximo|el\s+proximo)\s+)({dias})\b", t):
        add(m, _next_weekday(ref, DIAS[m.group(1)]))

    # ordenar, quitar solapamientos y duplicados de fecha+rango
    found.sort(key=lambda s: (s.start, -(s.end - s.start)))
    result: list[DateSuggestion] = []
    last_end = -1
    for s in found:
        if s.start >= last_end:
            result.append(s)
            last_end = s.end
    return result


def first_future_date(text: str, ref: date) -> DateSuggestion | None:
    s = extract_dates(text, ref)
    return s[0] if s else None
