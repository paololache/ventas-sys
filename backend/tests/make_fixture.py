"""Genera un Excel SINTÉTICO con la estructura descrita del CRM_Oportunidades_Adistec.xlsx (el real no está en el repo).

Reproduce los problemas observados: 26 oportunidades, 25 sin próxima acción, 1 con fecha de cierre, 1 con responsable,
MEDDPICC vacío en 23, y bitácora con 'Próximo paso' sin fecha.
"""
from datetime import date

from openpyxl import Workbook

from app.services.excel import BITACORA_HEADERS, PIPELINE_HEADERS

PARTNERS = ["Think Networks", "SYPSA", "Zentury", "La Viga Tech", "think networks ", "Zentury"]
STAGES = ["Prospección", "Calificación", "Deal Registrado", "Propuesta enviada", "Negociación", "Renovación", "Ganada", "Perdida", "En pausa"]


def build(path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Pipeline"
    ws["A1"] = "CRM Oportunidades Adistec"
    for i, h in enumerate(PIPELINE_HEADERS, 1):
        ws.cell(4, i, h)
    for n in range(1, 27):
        r = 4 + n
        stage = STAGES[(n - 1) % 9] if n > 3 else ["Propuesta enviada", "Negociación", "Deal Registrado"][n - 1]
        tipo = ["DR", "EW", "CSS"][n % 3]
        row = {
            1: f"OP-{n:03d}", 2: tipo, 3: f"Cliente {n % 12 + 1}  SA", 4: f"Oportunidad {n}", 5: "Gobierno" if n % 4 == 0 else "Banca y Finanzas",
            6: PARTNERS[n % len(PARTNERS)], 7: "Adistec Corp", 8: ["Extreme Networks", "VMware", "Citrix", "Omnissa", "Otra"][n % 5],
            9: 10000 * n, 11: stage, 12: 0.5, 14: ["Alta", "Media", "Baja"][n % 3], 22: "",
        }
        if n == 1:  # única con acción, cierre, responsable y MEDDPICC alto
            row.update({15: date(2026, 11, 30), 16: "Enviar propuesta", 17: date(2026, 11, 10), 20: "Miriam Quispe", 10: 12, 21: date(2026, 11, 2)})
        if n in (2, 3):
            row[10] = 5 + n
        if n == 4:
            row[22] = "se publica el 15/11 en el SEACE"
        for c, v in row.items():
            ws.cell(r, c, v)
    bs = wb.create_sheet("Bitácora")
    for i, h in enumerate(BITACORA_HEADERS, 1):
        bs.cell(4, i, h)
    rows = [
        (date(2026, 10, 20), "OP-001", "Cliente 2  SA", "Llamada", "Miriam", "Revisamos alcance", "Enviar propuesta", date(2026, 11, 10)),
        (date(2026, 10, 25), "OP-002", "", "Reunión", "Juan", "Reunión con el partner", "Presenta propuesta", None),
        (date(2026, 10, 28), "OP-005", "", "Email", "", "Se envió cotización", "Llamar la semana que viene", None),
    ]
    for i, vals in enumerate(rows, 5):
        for c, v in enumerate(vals, 1):
            bs.cell(i, c, v)
    ls = wb.create_sheet("Listas")
    ls["A1"], ls["B1"] = "Etapa", "Probabilidad"
    for i, (s, p) in enumerate(zip(STAGES, [10, 20, 30, 50, 70, 60, 100, 0, 0]), 2):
        ls.cell(i, 1, s)
        ls.cell(i, 2, p)
    ls["D1"] = "Tipo"
    for i, v in enumerate(["DR", "EW", "CSS"], 2):
        ls.cell(i, 4, v)
    wb.save(path)
    return path


if __name__ == "__main__":
    build("fixtures/CRM_Oportunidades_sintetico.xlsx")
