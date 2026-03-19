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


def formatear_timestamp_metadata(timestamp: str) -> str:
    instante = datetime.fromisoformat(timestamp)

    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=ZoneInfo("UTC"))

    return instante.astimezone(ZoneInfo("Europe/Madrid")).strftime("%d/%m/%Y %H:%M:%S")


inicio_formateado = formatear_timestamp_metadata(metadata["inicio_informe"])

# ======================
# PREPARAR DATOS
# ======================

if "fecha" not in df.columns:
    df["fecha"] = datetime.now(ZoneInfo("Europe/Madrid")).strftime("%Y-%m-%d")

df["fecha"] = df["fecha"].astype(str)
if "sala" not in df.columns:
    df["sala"] = ""
else:
    df["sala"] = df["sala"].fillna("").astype(str)

columnas_deduplicacion = ["fecha", "pelicula", "hora", "sala"]
df = df.drop_duplicates(subset=columnas_deduplicacion, keep="last")

df["fecha_hora_original"] = pd.to_datetime(
    df["fecha"] + " " + df["hora"],
    errors="coerce",
)
df["fecha_hora_dashboard"] = df["fecha_hora_original"] + pd.Timedelta(hours=1)

df["fecha_dashboard"] = df["fecha_hora_dashboard"].dt.strftime("%Y-%m-%d")
df["hora_dashboard"] = df["fecha_hora_dashboard"].dt.strftime("%H:%M")

df.loc[df["fecha_hora_dashboard"].isna(), "fecha_dashboard"] = df.loc[
    df["fecha_hora_dashboard"].isna(), "fecha"
]
df.loc[df["fecha_hora_dashboard"].isna(), "hora_dashboard"] = df.loc[
    df["fecha_hora_dashboard"].isna(), "hora"
]

df["ocupacion_pct"] = (df["ocupadas"] / df["total"]) * 100

df = df.sort_values(["fecha_dashboard", "hora_dashboard", "pelicula", "sala"])

hoy_madrid = datetime.now(ZoneInfo("Europe/Madrid")).strftime("%Y-%m-%d")
fechas_disponibles = sorted(df["fecha_dashboard"].dropna().unique(), reverse=True)

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

df_filtrado = df[df["fecha_dashboard"] == fecha_seleccionada].copy()

if df_filtrado.empty:
    st.warning(
        f"No hay datos guardados para {formatear_fecha(fecha_seleccionada)}. "
        "Selecciona un día anterior para ver sesiones históricas."
    )

st.caption(f"Datos capturados por última vez: {inicio_formateado} (hora de Madrid)")

# ======================
# DEMANDA POR HORA
# ======================

st.subheader("📈 Demanda por horario")

demanda = df_filtrado.groupby("hora_dashboard")["ocupadas"].sum().sort_index().reset_index()

st.bar_chart(
    demanda.set_index("hora_dashboard")
)

# ======================
# TOP SESIONES
# ======================

st.subheader("🔥 Sesiones con mayor ocupación")

top_sesiones = df_filtrado.assign(
    fecha=df_filtrado["fecha_dashboard"],
    hora=df_filtrado["hora_dashboard"],
).sort_values("ocupacion_pct", ascending=False).head(10)

st.dataframe(
    top_sesiones[
        [
            "pelicula",
            "fecha",
            "hora",
            "sala",
            "ocupadas",
            "total",
            "libres",
            "ocupacion_pct",
        ]
    ]
)

# ======================
# TABLA COMPLETA
# ======================

st.subheader("📋 Datos completos")

tabla_completa = df_filtrado.assign(
    fecha=df_filtrado["fecha_dashboard"],
    hora=df_filtrado["hora_dashboard"],
)[
    [
        "pelicula",
        "fecha",
        "hora",
        "sala",
        "ocupadas",
        "total",
        "libres",
        "ocupacion_pct",
    ]
]

st.dataframe(tabla_completa)

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
