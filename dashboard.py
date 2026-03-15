import streamlit as st
import pandas as pd
import json
from streamlit_autorefresh import st_autorefresh

# refrescar cada 10 segundos
st_autorefresh(interval=10000, key="datarefresh")

st.title("🎬 Ocupación Kinepolis")

# ======================
# METADATA
# ======================

with open("metadata.json", "r", encoding="utf-8") as f:
    metadata = json.load(f)

st.subheader("Último scrape")

col1, col2, col3 = st.columns(3)

col1.metric("Inicio informe", metadata["inicio_informe"])
col2.metric("Duración (s)", metadata["duracion_segundos"])
col3.metric("Sesiones analizadas", metadata["sesiones_analizadas"])

# ======================
# DATOS
# ======================

df = pd.read_csv("ocupacion_kinepolis.csv")

st.subheader("Datos por sesión")

st.dataframe(df)

# ======================
# GRÁFICO
# ======================

st.subheader("Ocupación por sesión")

st.bar_chart(df.set_index("hora")["ocupacion"])