"""Compara el modelo con los valores calculados del Excel original."""
import sys, openpyxl, numpy as np
from modelo import obras_default, calcular

ws = openpyxl.load_workbook(sys.argv[1], data_only=True).active
res = calcular(obras_default())
ind = res.indicadores
chk = {
    "C48 costo fin. VAN": (ws["C48"].value, ind["Costo financiero (VAN)"]),
    "C62 ingreso 1er sem": (ws["C62"].value, ind["Ingreso bruto 1er semestre"]),
    "D57 TIR sem": (ws["D57"].value, ind["TIR semestral"]),
    "D58 TIR anual": (ws["D58"].value, ind["TIR anual"]),
    "D60 delta tarifario": (ws["D60"].value, ind["Delta tarifario ($/UTEQUI)"]),
    "D61 CF/obras": (ws["D61"].value, ind["Costo financiero / obras"]),
    "L40 total obras": (ws["L40"].value, ind["Total obras (propuesta)"]),
}
ok = True
for k, (x, p) in chk.items():
    good = np.isclose(x, p, rtol=1e-6, atol=1e-6)
    ok &= good
    print(f"{'OK ' if good else 'MAL'} {k}: excel={x:,.6f} python={p:,.6f}")
# filas semestrales 76..81 y resumen anual 51..56
sem = res.semestral
filas = {"egreso": 76, "ingreso": 77, "impuesto": 78, "costo financiero": 79, "resultado": 80, "saldo obra adelantada": 81}
for nombre, fila in filas.items():
    xl = np.array([ws.cell(fila, c).value or 0 for c in range(4, 44)], float)
    good = np.allclose(xl, sem.loc[nombre].iloc[:40].to_numpy(float), rtol=1e-6, atol=1.0)
    ok &= good; print("OK " if good else "MAL", "semestral", nombre)
filas_a = {"egreso": 51, "ingreso": 52, "impuesto": 53, "costo financiero": 54, "resultado": 55, "saldo obra adelantada": 56}
for nombre, fila in filas_a.items():
    xl = np.array([ws.cell(fila, c).value or 0 for c in range(4, 24)], float)
    good = np.allclose(xl, res.anual.loc[nombre].iloc[:20].to_numpy(float), rtol=1e-6, atol=1.0)
    ok &= good; print("OK " if good else "MAL", "anual", nombre)
print("TODO OK" if ok else "HAY DIFERENCIAS")
