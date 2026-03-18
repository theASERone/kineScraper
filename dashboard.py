import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# ======================
# CONFIGURACIÓN
# ======================

st.set_page_config(layout="wide")

st_autorefresh(interval=10000, key="datarefresh")

st.title("🎬 Ocupación Kinepolis")

# ======================
# CARGAR DATOS
# ======================

df = pd.read_csv("ocupacion_kinepolis.csv")

with open("metadata.json", "r", encoding="utf-8") as f:
    metadata = json.load(f)

# ======================
# FORMATEAR HORA MADRID
# ======================

inicio_utc = datetime.strptime(metadata["inicio_informe"], "%Y-%m-%d %H:%M:%S")

inicio_madrid = inicio_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(
    ZoneInfo("Europe/Madrid")
)

inicio_formateado = inicio_madrid.strftime("%d/%m/%Y %H:%M:%S")

# ======================
# PREPARAR DATOS
# ======================

if "fecha" not in df.columns:
    df["fecha"] = datetime.now(ZoneInfo("Europe/Madrid")).strftime("%Y-%m-%d")

df["fecha"] = df["fecha"].astype(str)
df["fecha_hora"] = df["fecha"] + " " + df["hora"]

df["ocupacion_pct"] = (df["ocupadas"] / df["total"]) * 100

df = df.sort_values(["fecha", "hora"])

hoy_madrid = datetime.now(ZoneInfo("Europe/Madrid")).strftime("%Y-%m-%d")
fechas_disponibles = sorted(df["fecha"].dropna().unique(), reverse=True)

opciones_fecha = [hoy_madrid] + [f for f in fechas_disponibles if f != hoy_madrid]


def formatear_fecha(fecha_iso: str) -> str:
    fecha_dt = datetime.strptime(fecha_iso, "%Y-%m-%d")
    if fecha_iso == hoy_madrid:
        return f"{fecha_dt.strftime('%d/%m/%Y')} (hoy)"
    return fecha_dt.strftime("%d/%m/%Y")


fecha_seleccionada = st.selectbox(
    "📅 Selecciona el día",
    options=opciones_fecha,
    index=0,
    format_func=formatear_fecha,
    help="Por defecto se muestra hoy en horario de Madrid, pero puedes consultar días anteriores.",
)

df_filtrado = df[df["fecha"] == fecha_seleccionada].copy()

if df_filtrado.empty:
    st.warning(
        f"No hay datos guardados para {formatear_fecha(fecha_seleccionada)}. "
        "Selecciona un día anterior para ver sesiones históricas."
    )

st.caption(f"Datos capturados por última vez: {inicio_formateado} (hora de Madrid)")

# ======================
# PANEL MÉTRICAS
# ======================

st.subheader("📊 Indicadores")

col1, col2, col3, col4, col5 = st.columns(5)

col1.metric("Inicio informe", inicio_formateado)

col2.metric(
    "Duración scrape (s)",
    metadata["duracion_segundos"],
)

col3.metric(
    "Películas",
    df_filtrado["pelicula"].nunique(),
)

col4.metric(
    "Sesiones",
    len(df_filtrado),
)

col5.metric(
    "Butacas ocupadas",
    int(df_filtrado["ocupadas"].sum()),
)

# ======================
# RANKING SESIONES
# ======================

st.subheader("🔥 Sesiones con mayor ocupación")

top_sesiones = df_filtrado.sort_values(
    "ocupacion_pct",
    ascending=False,
).head(10)

st.dataframe(
    top_sesiones[
        [
            "pelicula",
            "fecha",
            "hora",
            "ocupadas",
            "total",
            "ocupacion_pct",
        ]
    ]
)

# ======================
# DEMANDA POR HORA
# ======================

st.subheader("📈 Demanda por horario")

demanda = df_filtrado.groupby("hora")["ocupadas"].sum().reset_index()

st.bar_chart(
    demanda.set_index("hora")
)

# ======================
# HEATMAP PELÍCULA / HORA
# ======================

st.subheader("🎬 Ocupación por película y horario")

pivot = df_filtrado.pivot_table(
    index="pelicula",
    columns="hora",
    values="ocupacion_pct",
    aggfunc="mean",
)

st.dataframe(
    pivot.style.background_gradient(cmap="Reds")
)

# ======================
# EVOLUCIÓN OCUPACIÓN
# ======================

st.subheader("📊 Evolución de ocupación")

evolucion = df_filtrado.groupby("hora")["ocupadas"].sum()

st.line_chart(evolucion)

# ======================
# TABLA COMPLETA
# ======================

st.subheader("📋 Datos completos")

st.dataframe(df_filtrado)
