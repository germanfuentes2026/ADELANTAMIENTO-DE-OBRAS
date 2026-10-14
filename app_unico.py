"""Modelo de flujo de obras: situación contrato vs. situación propuesta (corrimiento).
 
Replica la hoja 'Alt I' del Excel. Todo en pesos corrientes, periodos semestrales.
"""
from __future__ import annotations
 
from dataclasses import dataclass, field
 
import io
 
import numpy as np
import pandas as pd
import streamlit as st
 
N_SEM_CERT = 16     # semestres con certificación (8 años)
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
    """Obras del Excel. Columnas: obra, monto, adelanto (semestres), s1..s16 (% contrato)."""
    filas = [
        ("DISTRIBUIDOR TREBOL", 35_529_000_000, 1, {3: .1, 4: .3, 5: .3, 6: .3}),
        ("TERCER CARRIL NEWVERY", 23_434_000_000, 1, {5: .1, 6: .2, 7: .4, 8: .3}),
        ("4TO CARRIL RICCHERI", 28_345_000_000, 1, {5: .2, 6: .3, 7: .3, 8: .2}),
        ("AUTOPISTA RN N°3 FIN VARIANTE LAS FLORES - INTERSECCIÓN RP N° 30", 12_700_000_000, 1, {3: .1, 4: .2, 5: .4, 6: .3}),
        ("REPAVIMENTACIÓN RN N° 3 KM 88 - KM 104 Y KM 104 - KM 109", 4_545_454_545.45455, 1, {3: .1, 4: .2, 5: .4, 6: .3}),
        ("CONSTRUCCIÓN DE COLECTORA - TANDIL", 1_200_000_000, 1, {3: .1, 4: .3, 5: .3, 6: .3}),
        ("SEMAFORIZACIÓN TRAVESÍA URBANA TANDIL", 1_200_000_000, 1, {3: .1, 4: .2, 5: .4, 6: .3}),
        ("OBRA 8 (completar)", 0, 1, {}),
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
    """Devuelve (contrato, propuesta): $ por obra y semestre (filas=obras, cols=s1..s16)."""
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
 
 
def irr(flujos: np.ndarray, guess: float = 0.1) -> float:
    """TIR: busca los cambios de signo del VAN en una grilla y devuelve la raíz
    más cercana a `guess` (como hace IRR de Excel con su valor inicial)."""
    f = lambda r: npv(r, flujos)
    grid = np.linspace(-0.9, 5.0, 1200)
    vals = np.array([f(x) for x in grid])
    raices = []
    for i in np.where(np.sign(vals[:-1]) * np.sign(vals[1:]) < 0)[0]:
        lo, hi, flo = grid[i], grid[i + 1], vals[i]
        for _ in range(200):
            mid = (lo + hi) / 2
            fm = f(mid)
            if np.sign(fm) == np.sign(flo):
                lo, flo = mid, fm
            else:
                hi = mid
        raices.append((lo + hi) / 2)
    if not raices:
        return float("nan")
    return min(raices, key=lambda x: abs(x - guess))
 
 
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
 
    tir_sem = irr(resultado, guess=r)
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
 
 
# =========================== APP STREAMLIT =========================== #
st.set_page_config(page_title="Flujo de obras", layout="wide")
st.title("Flujo de obras: contrato vs. propuesta")
 
# ---------------------------- Supuestos ---------------------------------- #
with st.sidebar:
    st.header("Supuestos")
    tasa = st.number_input("Tasa anual (TIR objetivo)", 0.0, 1.0, 0.15, 0.01, format="%.4f")
    crec = st.number_input("Crecimiento anual del ingreso", 0.0, 1.0, 0.02, 0.01, format="%.4f")
    inicio = st.number_input("Semestre de inicio del ingreso", 1, 20, 3, help="3 = año 2")
    imp = st.number_input("Impuesto sobre el ingreso", 0.0, 1.0, 0.20, 0.01, format="%.4f")
    uteq = st.number_input("UTEQUIS anuales", 1, value=157_126_576, step=1)
sup = Supuestos(tasa, crec, int(inicio), imp, float(uteq))
 
# ---------------------------- Obras -------------------------------------- #
st.subheader("1. Obras: monto, % por semestre y corrimiento")
st.caption("`adelanto` = semestres que se adelanta cada obra en la propuesta (negativo = se posterga). "
           "Los % de s1..s16 son los del contrato.")
if "obras" not in st.session_state:
    st.session_state.obras = obras_default()
cfg = {
    "monto": st.column_config.NumberColumn("monto ($)", format="%,.0f"),
    "adelanto": st.column_config.NumberColumn("adelanto (sem.)", step=1),
    **{c: st.column_config.NumberColumn(c, format="%.2f", min_value=0.0, max_value=1.0) for c in COLS_SEM},
}
obras = st.data_editor(st.session_state.obras, column_config=cfg, num_rows="dynamic",
                       use_container_width=True, hide_index=True)
obras = obras.dropna(subset=["obra"]).fillna(0)
 
sumas = obras[COLS_SEM].sum(axis=1)
if ((sumas - 1).abs() > 1e-9).any():
    st.warning("Algunas obras no suman 100% en el contrato: " + ", ".join(obras.loc[(sumas - 1).abs() > 1e-9, "obra"]))
 
# ---------------------------- Correr ------------------------------------- #
if st.button("Correr", type="primary"):
    try:
        st.session_state.res = calcular(obras.astype({"adelanto": int}), sup)
    except ValueError as e:
        st.error(str(e))
        st.session_state.pop("res", None)
 
res = st.session_state.get("res")
if res is None:
    st.info("Cargá los montos, definí el corrimiento y apretá **Correr**.")
    st.stop()
 
fmt = lambda df: df.style.format("{:,.0f}", na_rep="")
ind = res.indicadores
c = st.columns(4)
c[0].metric("Costo financiero (VAN)", f"${ind['Costo financiero (VAN)']:,.0f}")
c[1].metric("TIR anual", f"{ind['TIR anual']:.2%}")
c[2].metric("Delta tarifario ($/UTEQUI)", f"{ind['Delta tarifario ($/UTEQUI)']:,.2f}")
c[3].metric("Costo fin. / obras", f"{ind['Costo financiero / obras']:.2%}")
 
st.subheader("2. Flujos")
t1, t2, t3, t4 = st.tabs(["Contrato vs. propuesta", "Flujo semestral", "Flujo anual", "Gráfico"])
with t1:
    st.markdown("**Contrato**"); st.dataframe(fmt(res.contrato.assign(TOTAL=res.contrato.sum(axis=1))), use_container_width=True)
    st.markdown("**Propuesta**"); st.dataframe(fmt(res.propuesta.assign(TOTAL=res.propuesta.sum(axis=1))), use_container_width=True)
    st.markdown("**Corrimiento (contrato − propuesta)**")
    st.dataframe(fmt(res.corrimiento.to_frame("corrimiento").T), use_container_width=True)
with t2:
    st.dataframe(fmt(res.semestral), use_container_width=True)
with t3:
    st.dataframe(fmt(res.anual), use_container_width=True)
with t4:
    st.line_chart(res.anual.drop(columns="TOTAL").loc[["egreso", "ingreso", "resultado"]].T)
    st.bar_chart(res.anual.drop(columns="TOTAL").loc["saldo obra adelantada"])
 
st.caption(f"Controles: VAN del resultado = {ind['Control VAN resultado (=0)']:.4f} (debe ser ~0) · "
           f"VAN costo fin. − C48 = {ind['Control VAN costo fin. − C48']:.4f}")
 
try:
    buf = io.BytesIO()
    exportar_excel(res, buf)
    st.download_button("Descargar Excel", buf.getvalue(), "flujo_obras.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
except ModuleNotFoundError:
    st.info("Para descargar el Excel agregá `openpyxl` al requirements.txt.")

