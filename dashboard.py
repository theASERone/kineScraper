import streamlit as st
import pandas as pd
import json
from streamlit_autorefresh import st_autorefresh
from datetime import datetime
from zoneinfo import ZoneInfo

st.set_page_config(layout="wide")

st_autorefresh(interval=10000, key="datarefresh")

st.title("🎬 Ocupación Kinepolis")

# ======================
# CARGAR DATOS
# ======================

df = pd.read_csv("ocupacion_kinepolis.csv")

with open("metadata.json", "r", encoding="utf-8") as f:
    metadata = json.load(f)
    
    # convertir hora a Madrid
    inicio_utc = datetime.strptime(metadata["inicio_informe"], "%Y-%m-%d %H:%M:%S")

    inicio_madrid = inicio_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(
        ZoneInfo("Europe/Madrid")
    )

    inicio_formateado = inicio_madrid.strftime("%d/%m/%Y %H:%M:%S")

# ======================
# MÉTRICAS
# ======================

col1, col2, col3, col4 = st.columns(4)

col1.metric("Inicio informe", inicio_formateado)
col2.metric("Duración (s)", metadata["duracion_segundos"])
col3.metric("Sesiones", metadata["sesiones_analizadas"])
col4.metric("Películas", df["pelicula"].nunique())

# ======================
# TABLA
# ======================

st.subheader("Datos por sesión")

st.dataframe(df)

# ======================
# GRÁFICO
# ======================

resumen = df.groupby("hora")[["ocupadas","total"]].sum().reset_index()

st.subheader("Butacas ocupadas por hora")

st.bar_chart(resumen.set_index("hora")["ocupadas"])