import streamlit as st
import pandas as pd
import json
from streamlit_autorefresh import st_autorefresh
from datetime import datetime
from zoneinfo import ZoneInfo

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
    df["fecha"] = datetime.now().strftime("%Y-%m-%d")

df["fecha_hora"] = df["fecha"] + " " + df["hora"]

df["ocupacion_pct"] = (df["ocupadas"] / df["total"]) * 100

df = df.sort_values(["fecha", "hora"])

fechas_disponibles = sorted(df["fecha"].dropna().unique())
hoy = datetime.now().strftime("%Y-%m-%d")

if hoy in fechas_disponibles:
    fecha_por_defecto = hoy
else:
    fecha_por_defecto = fechas_disponibles[-1]

fecha_seleccionada = st.selectbox(
    "📅 Selecciona el día",
    options=list(reversed(fechas_disponibles)),
    index=list(reversed(fechas_disponibles)).index(fecha_por_defecto),
    help="Por defecto se muestra el día de hoy, pero puedes consultar días anteriores."
)

df_filtrado = df[df["fecha"] == fecha_seleccionada].copy()

# ======================
# PANEL MÉTRICAS
# ======================

st.subheader("📊 Indicadores")

col1, col2, col3, col4, col5 = st.columns(5)

col1.metric("Inicio informe", inicio_formateado)

col2.metric(
    "Duración scrape (s)",
    metadata["duracion_segundos"]
)

col3.metric(
    "Películas",
    df_filtrado["pelicula"].nunique()
)

col4.metric(
    "Sesiones",
    len(df_filtrado)
)

col5.metric(
    "Butacas ocupadas",
    int(df_filtrado["ocupadas"].sum())
)

# ======================
# RANKING SESIONES
# ======================

st.subheader("🔥 Sesiones con mayor ocupación")

top_sesiones = df_filtrado.sort_values(
    "ocupacion_pct",
    ascending=False
).head(10)

st.dataframe(
    top_sesiones[
        [
            "pelicula",
            "fecha",
            "hora",
            "ocupadas",
            "total",
            "ocupacion_pct"
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
    aggfunc="mean"
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
