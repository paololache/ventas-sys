from datetime import date

from app.dates_es import extract_dates, first_future_date

REF = date(2026, 11, 3)  # martes


def fechas(t):
    return [s.fecha for s in extract_dates(t, REF)]


def test_dd_mm():
    assert fechas("se publica el 15/11 en el SEACE") == [date(2026, 11, 15)]
    assert fechas("presentará 11/11/2026") == [date(2026, 11, 11)]


def test_texto_mes():
    assert fechas("buena pro el 20 de diciembre") == [date(2026, 12, 20)]


def test_relativas():
    assert fechas("llamar mañana") == [date(2026, 11, 4)]
    assert fechas("pasado mañana reunión") == [date(2026, 11, 5)]
    assert fechas("la semana que viene") == [date(2026, 11, 9)]  # lunes siguiente
    assert fechas("en 3 días") == [date(2026, 11, 6)]
    assert fechas("el viernes") == [date(2026, 11, 6)]
    assert fechas("fin de mes") == [date(2026, 11, 30)]


def test_pasadas_se_descartan_y_year_roll():
    assert fechas("lo hice el 01/11") == []
    assert fechas("el 05/01") == [date(2027, 1, 5)]  # 05/01/2026 pasó hace >180 d: se asume el año siguiente


def test_primera_futura():
    s = first_future_date("llamé a Miriam, presenta propuesta el 11/11", REF)
    assert s and s.fecha == date(2026, 11, 11) and s.texto == "11/11"


def test_sin_fecha():
    assert fechas("sin novedades") == []
