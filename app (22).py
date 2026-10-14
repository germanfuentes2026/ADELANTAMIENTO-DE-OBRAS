import io

import pandas as pd
import streamlit as st

from modelo import COLS_SEM, Supuestos, calcular, exportar_excel, obras_default

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
           "Los % de s1..s8 son los del contrato.")
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

buf = io.BytesIO()
exportar_excel(res, buf)
st.download_button("Descargar Excel", buf.getvalue(), "flujo_obras.xlsx",
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
