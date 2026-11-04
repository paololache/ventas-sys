"""Tests unitarios de R1–R13 (funciones puras, fecha inyectada)."""
from dataclasses import replace
from datetime import date

from app.alerts import rules as R
from app.calendar_util import business_days_between, is_work_time
from datetime import datetime

TODAY = date(2026, 11, 3)  # martes


def opp(**kw):
    base = dict(
        id=1, code="OP-001", cliente="ACME", descripcion="x", tipo="DR", stage="Propuesta enviada", is_open=True, is_paused=False,
        prioridad="Media", monto=1000, fecha_cierre_est=date(2026, 12, 1), prox_accion="Llamar", fecha_prox_accion=date(2026, 11, 20),
        sin_proximo_paso_motivo="", ultima_actualizacion=TODAY, stage_entered_on=TODAY, dr_vencimiento=None, contrato_vencimiento=None,
        seace_publicacion=None, seace_buena_pro=None, seace_propuestas=None, meddpicc_score=8, has_contact=True, partner_id=1, owner_id=1,
    )
    base.update(kw)
    return R.OppView(**base)


def ev(o, **kw):
    return {c.rule: c for c in R.evaluate_opportunity(o, R.EvalCtx(today=kw.pop("today", TODAY), **kw))}


def test_opp_sana_no_genera_nada():
    assert ev(opp()) == {}


def test_r1_vencida_y_borde_hoy():
    assert "R1" in ev(opp(fecha_prox_accion=date(2026, 11, 2)))
    assert ev(opp(fecha_prox_accion=date(2026, 11, 2)))["R1"].severity == "Alta"
    assert "R1" not in ev(opp(fecha_prox_accion=TODAY))  # hoy no está vencida


def test_r2_hoy_y_manana():
    assert "R2" in ev(opp(fecha_prox_accion=TODAY))
    assert "R2" in ev(opp(fecha_prox_accion=date(2026, 11, 4)))
    assert "R2" not in ev(opp(fecha_prox_accion=date(2026, 11, 5)))


def test_r3_sin_accion_fecha_o_motivo():
    assert "R3" in ev(opp(prox_accion="", fecha_prox_accion=None))
    assert "R3" in ev(opp(fecha_prox_accion=None))
    assert "R3" in ev(opp(prox_accion=""))
    assert "R3" not in ev(opp(prox_accion="", fecha_prox_accion=None, sin_proximo_paso_motivo="Cliente pausó"))


def test_cerrada_o_pausada_no_alerta():
    sin = dict(prox_accion="", fecha_prox_accion=None, fecha_cierre_est=None, ultima_actualizacion=date(2026, 1, 1))
    assert ev(opp(is_open=False, **sin)) == {}
    assert ev(opp(is_paused=True, **sin)) == {}


def test_r4_estancada_dias_habiles_y_severidad():
    # Propuesta enviada: límite 5 días hábiles. Último update viernes 23/10 → 7 hábiles hasta el 3/11 (sin feriados)
    o = opp(ultima_actualizacion=date(2026, 10, 23))
    assert ev(o)["R4"].severity == "Media"
    assert ev(replace(o, prioridad="Alta"))["R4"].severity == "Alta"


def test_r4_borde_exacto_y_fin_de_semana():
    # lunes 26/10 → martes 3/11 = 6 días hábiles (>5) ; jueves 29/10 → 3 hábiles
    assert "R4" in ev(opp(ultima_actualizacion=date(2026, 10, 26)))
    assert "R4" not in ev(opp(ultima_actualizacion=date(2026, 10, 27)))  # exactamente 5 → no
    # actualizado el viernes y hoy lunes: 1 día hábil, el fin de semana no cuenta
    assert "R4" not in ev(opp(ultima_actualizacion=date(2026, 10, 30)))
    assert business_days_between(date(2026, 10, 30), date(2026, 11, 2)) == 1


def test_r4_feriado_no_cuenta():
    hol = frozenset({date(2026, 10, 28)})
    assert business_days_between(date(2026, 10, 26), TODAY, hol) == 5
    assert "R4" not in ev(opp(ultima_actualizacion=date(2026, 10, 26)), holidays=hol)


def test_r5_cierre_pasado():
    assert "R5" in ev(opp(fecha_cierre_est=date(2026, 11, 1)))
    assert "R5" not in ev(opp(fecha_cierre_est=TODAY))


def test_r6_sin_cierre_baja():
    assert ev(opp(fecha_cierre_est=None))["R6"].severity == "Baja"


def test_r7_dr_por_vencer():
    assert "R7" in ev(opp(dr_vencimiento=date(2026, 11, 18)))
    assert "R7" not in ev(opp(dr_vencimiento=date(2026, 11, 19)))
    c = ev(opp(dr_vencimiento=TODAY))["R7"]
    assert c.urgent and c.severity == "Alta"
    assert "R7" in ev(opp(dr_vencimiento=date(2026, 10, 1)))  # vencido


def test_r8_renovacion_tramos():
    base = opp(tipo="EW", stage="Renovación")
    assert "R8" not in ev(replace(base, contrato_vencimiento=date(2027, 2, 1)))  # >60 d
    assert ev(replace(base, contrato_vencimiento=date(2026, 12, 20)))["R8"].severity == "Media"  # 47 d
    assert ev(replace(base, contrato_vencimiento=date(2026, 11, 15)))["R8"].severity == "Alta"  # 12 d
    assert "R8" not in ev(opp(tipo="DR", contrato_vencimiento=date(2026, 11, 15)))  # sólo EW/CSS


def test_r9_hitos_seace():
    c = ev(opp(seace_publicacion=date(2026, 11, 6)))
    assert c["R9"].severity == "Alta" and c["R9"].key.endswith("publicación")
    assert "R9" not in ev(opp(seace_publicacion=date(2026, 11, 7)))
    assert "R9" not in ev(opp(seace_publicacion=date(2026, 11, 2)))  # ya pasó


def test_r10_paso_huerfano():
    o = opp(prox_accion="", fecha_prox_accion=None)
    a = R.ActivityView(5, 1, date(2026, 10, 30), "Presentar propuesta", None)
    out = R.r10_paso_huerfano([a], {1: o}, R.EvalCtx(today=TODAY))
    assert len(out) == 1 and out[0].key == "R10:act:5"
    # con fecha en la actividad o con próxima acción definida en la opp → no aplica
    assert not R.r10_paso_huerfano([R.ActivityView(5, 1, TODAY, "x", date(2026, 11, 9))], {1: o}, R.EvalCtx(today=TODAY))
    assert not R.r10_paso_huerfano([a], {1: opp()}, R.EvalCtx(today=TODAY))
    assert not R.r10_paso_huerfano([a], {1: opp(is_open=False)}, R.EvalCtx(today=TODAY))


def test_r11_etapa_vs_promedio():
    x = {"Propuesta enviada": (5.0, 4)}
    assert "R11" in ev(opp(stage_entered_on=date(2026, 10, 20)), stage_avg_days=x)  # 14 d > 10
    assert "R11" not in ev(opp(stage_entered_on=date(2026, 10, 24)), stage_avg_days=x)  # 10 d, no >
    assert "R11" not in ev(opp(stage_entered_on=date(2026, 10, 1)), stage_avg_days={"Propuesta enviada": (5.0, 2)})  # pocas muestras


def test_r12_partner_silencioso():
    ctx = R.EvalCtx(today=TODAY)
    p = R.PartnerView(1, "SYPSA", 2, date(2026, 10, 1), None)
    assert len(R.r12_partner_silencioso([p], ctx)) == 1
    assert not R.r12_partner_silencioso([R.PartnerView(1, "SYPSA", 2, date(2026, 10, 20), None)], ctx)
    assert not R.r12_partner_silencioso([R.PartnerView(1, "SYPSA", 0, date(2026, 1, 1), None)], ctx)  # sin abiertas


def test_r13_datos_incompletos_oportunidad_grande():
    assert not ev(opp(monto=50000, meddpicc_score=0))  # no supera 50k
    c = ev(opp(monto=50001, meddpicc_score=0, has_contact=False, fecha_cierre_est=None))["R13"]
    assert "MEDDPICC" in c.detail and "contacto" in c.detail and "fecha de cierre" in c.detail
    assert "R13" not in ev(opp(monto=90000))


def test_regla_deshabilitada_y_umbral_configurable():
    rules = R.default_cfgs()
    rules["R1"] = R.RuleCfg(False, "Alta", {})
    assert "R1" not in ev(opp(fecha_prox_accion=date(2026, 11, 2)), rules=rules)
    rules["R7"] = R.RuleCfg(True, "Alta", {"dias": 30})
    assert "R7" in ev(opp(dr_vencimiento=date(2026, 11, 28)), rules=rules)


def test_horario_laboral_fin_de_semana_y_feriado():
    wd = (0, 1, 2, 3, 4)
    assert is_work_time(datetime(2026, 11, 3, 10), frozenset(), wd)
    assert not is_work_time(datetime(2026, 11, 3, 7, 59), frozenset(), wd)
    assert not is_work_time(datetime(2026, 11, 3, 19, 0), frozenset(), wd)
    assert not is_work_time(datetime(2026, 11, 7, 10), frozenset(), wd)  # sábado
    assert not is_work_time(datetime(2026, 11, 3, 10), frozenset({date(2026, 11, 3)}), wd)  # feriado
