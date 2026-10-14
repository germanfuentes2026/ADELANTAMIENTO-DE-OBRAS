"""Modelo de flujo de obras: situación contrato vs. situación propuesta (corrimiento).

Replica la hoja 'Alt I' del Excel. Todo en pesos corrientes, periodos semestrales.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

N_SEM_CERT = 8      # semestres con certificación (4 años)
HORIZONTE = 40      # semestres del flujo (20 años)


# --------------------------------------------------------------------------- #
# Datos de entrada
# --------------------------------------------------------------------------- #
@dataclass
class Supuestos:
    tasa_anual: float = 0.15          # TIR objetivo
    crec_anual: float = 0.02          # crecimiento anual del ingreso
    sem_inicio_ingreso: int = 3       # semestre en que empieza el cobro (3 = año 2)
    impuesto: float = 0.20
    utequis: float = 157_126_576
    horizonte: int = HORIZONTE

    @property
    def tasa_sem(self) -> float:
        return (1 + self.tasa_anual) ** 0.5 - 1

    @property
    def crec_sem(self) -> float:
        return (1 + self.crec_anual) ** 0.5 - 1


def obras_default() -> pd.DataFrame:
    """Obras del Excel. Columnas: obra, monto, adelanto (semestres), s1..s8 (% contrato)."""
    filas = [
        ("DISTRIBUIDOR TREBOL", 35_529_000_000, 1, {3: .1, 4: .3, 5: .3, 6: .3}),
        ("TERCER CARRIL NEWVERY", 23_434_000_000, 1, {5: .1, 6: .2, 7: .4, 8: .3}),
        ("4TO CARRIL RICCHERI", 28_345_000_000, 1, {5: .2, 6: .3, 7: .3, 8: .2}),
        ("AUTOPISTA RN N°3 FIN VARIANTE LAS FLORES - INTERSECCIÓN RP N° 30", 12_700_000_000, 1, {3: .1, 4: .2, 5: .4, 6: .3}),
        ("REPAVIMENTACIÓN RN N° 3 KM 88 - KM 104 Y KM 104 - KM 109", 4_545_454_545.45455, 1, {3: .1, 4: .2, 5: .4, 6: .3}),
        ("CONSTRUCCIÓN DE COLECTORA - TANDIL", 1_200_000_000, 1, {3: .1, 4: .3, 5: .3, 6: .3}),
        ("SEMAFORIZACIÓN TRAVESÍA URBANA TANDIL", 1_200_000_000, 1, {3: .1, 4: .2, 5: .4, 6: .3}),
    ]
    rows = []
    for nombre, monto, adel, pct in filas:
        r = {"obra": nombre, "monto": monto, "adelanto": adel}
        r.update({f"s{i}": pct.get(i, 0.0) for i in range(1, N_SEM_CERT + 1)})
        rows.append(r)
    return pd.DataFrame(rows)


COLS_SEM = [f"s{i}" for i in range(1, N_SEM_CERT + 1)]


# --------------------------------------------------------------------------- #
# Certificaciones: contrato y propuesta (corrimiento)
# --------------------------------------------------------------------------- #
def correr(pct: np.ndarray, adelanto: int) -> np.ndarray:
    """Corre el vector de % `adelanto` semestres hacia adelante (adelanto>0 = antes,
    adelanto<0 = se posterga). Lanza error si algún % cae fuera de la ventana."""
    out = np.zeros_like(pct, dtype=float)
    for i, v in enumerate(pct):
        j = i - int(adelanto)
        if v == 0:
            continue
        if not 0 <= j < len(pct):
            raise ValueError(f"El corrimiento de {adelanto} semestres saca un % fuera de los semestres 1-{len(pct)}.")
        out[j] += v
    return out


def certificaciones(obras: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devuelve (contrato, propuesta): $ por obra y semestre (filas=obras, cols=s1..s8)."""
    pct_c = obras[COLS_SEM].to_numpy(float)
    monto = obras["monto"].to_numpy(float)[:, None]
    pct_p = np.vstack([correr(p, a) for p, a in zip(pct_c, obras["adelanto"])])
    if "monto_propuesta" in obras:
        monto_p = obras["monto_propuesta"].to_numpy(float)[:, None]
    else:
        monto_p = monto
    idx = obras["obra"]
    contrato = pd.DataFrame(pct_c * monto, index=idx, columns=COLS_SEM)
    propuesta = pd.DataFrame(pct_p * monto_p, index=idx, columns=COLS_SEM)
    return contrato, propuesta


# --------------------------------------------------------------------------- #
# Matemática financiera (equivalente a NPV / IRR de Excel)
# --------------------------------------------------------------------------- #
def npv(tasa: float, flujos: np.ndarray) -> float:
    """Igual a NPV() de Excel: el primer flujo se descuenta un periodo."""
    t = np.arange(1, len(flujos) + 1)
    return float(np.sum(flujos / (1 + tasa) ** t))


def irr(flujos: np.ndarray, lo: float = -0.99, hi: float = 10.0) -> float:
    """TIR por bisección (mismo criterio de signo que IRR de Excel)."""
    f = lambda r: npv(r, flujos)
    flo, fhi = f(lo), f(hi)
    if np.sign(flo) == np.sign(fhi):
        return float("nan")
    for _ in range(300):
        mid = (lo + hi) / 2
        fm = f(mid)
        if np.sign(fm) == np.sign(flo):
            lo, flo = mid, fm
        else:
            hi = mid
    return (lo + hi) / 2


# --------------------------------------------------------------------------- #
# Flujo
# --------------------------------------------------------------------------- #
@dataclass
class Resultado:
    contrato: pd.DataFrame            # $ por obra y semestre
    propuesta: pd.DataFrame
    corrimiento: pd.Series            # contrato - propuesta, por semestre (1..8)
    semestral: pd.DataFrame           # flujo semestral (filas = conceptos, cols = semestre)
    anual: pd.DataFrame               # flujo anual
    indicadores: dict = field(default_factory=dict)


def calcular(obras: pd.DataFrame, sup: Supuestos | None = None) -> Resultado:
    sup = sup or Supuestos()
    H = sup.horizonte
    r, g, S0, t = sup.tasa_sem, sup.crec_sem, sup.sem_inicio_ingreso, sup.impuesto

    contrato, propuesta = certificaciones(obras)
    tot_c, tot_p = contrato.sum(), propuesta.sum()
    corr = tot_c - tot_p                      # egreso: negativo = obra adelantada

    sem = np.arange(1, H + 1)
    egreso = np.zeros(H)
    egreso[:N_SEM_CERT] = corr.to_numpy()

    costo_fin_van = -npv(r, egreso)           # C48

    # Ingreso bruto del semestre de inicio tal que TIR del resultado = tasa objetivo (C62)
    q = (1 + g) / (1 + r)
    ing0 = (costo_fin_van * (1 + r) ** S0 * (1 - q) / (1 - q ** (H + 1 - S0)) / (1 - t))

    ingreso = np.where(sem >= S0, ing0 * (1 + g) ** (sem - S0), 0.0)
    impuesto = ingreso * t
    saldo = np.cumsum(-egreso)                # saldo de obra adelantada
    interes = np.concatenate([[0.0], saldo[:-1] * r])
    resultado = ingreso - impuesto - interes

    semestral = pd.DataFrame(
        {"egreso": egreso, "ingreso": ingreso, "impuesto": impuesto,
         "costo financiero": interes, "resultado": resultado,
         "saldo obra adelantada": saldo},
        index=pd.Index(sem, name="semestre"),
    ).T
    semestral["TOTAL"] = semestral.sum(axis=1)
    semestral.loc["saldo obra adelantada", "TOTAL"] = np.nan

    # Anual: suma de dos semestres (el saldo es el del cierre del año)
    anio = (sem + 1) // 2
    flujos = semestral.drop(columns="TOTAL").T.groupby(anio)
    anual = flujos.sum().T
    anual.loc["saldo obra adelantada"] = flujos["saldo obra adelantada"].last().to_numpy()
    anual.columns.name = "año"
    anual["TOTAL"] = anual.sum(axis=1)
    anual.loc["saldo obra adelantada", "TOTAL"] = np.nan

    tir_sem = irr(resultado)
    ind = {
        "Costo financiero (VAN)": costo_fin_van,
        "Ingreso bruto 1er semestre": ing0,
        "TIR semestral": tir_sem,
        "TIR anual": (1 + tir_sem) ** 2 - 1,
        "Delta tarifario ($/UTEQUI)": float(ingreso[(sem >= S0) & (sem < S0 + 2)].sum() / sup.utequis),
        "Costo financiero / obras": costo_fin_van / tot_p.sum(),
        "Total obras (propuesta)": float(tot_p.sum()),
        "Control VAN costo fin. − C48": npv(r, interes) - costo_fin_van,
        "Control VAN resultado (=0)": npv(r, resultado),
    }
    return Resultado(contrato, propuesta, corr, semestral, anual, ind)


def exportar_excel(res: Resultado, ruta_o_buffer) -> None:
    with pd.ExcelWriter(ruta_o_buffer, engine="openpyxl") as xw:
        pd.Series(res.indicadores, name="valor").to_frame().to_excel(xw, sheet_name="Indicadores")
        res.contrato.to_excel(xw, sheet_name="Contrato")
        res.propuesta.to_excel(xw, sheet_name="Propuesta")
        res.corrimiento.to_frame("contrato - propuesta").T.to_excel(xw, sheet_name="Corrimiento")
        res.semestral.to_excel(xw, sheet_name="Flujo semestral")
        res.anual.to_excel(xw, sheet_name="Flujo anual")
