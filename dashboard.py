import streamlit as st
import pandas as pd
import plotly.express as px
import json

with open("metadata.json") as f:
    metadata = json.load(f)

st.set_page_config(
    page_title="Ocupación Kinepolis",
    layout="wide"
)

st.markdown(
        f"""
    **🕒 Informe generado:** {metadata['generated_at']}  
    **⏱️ Duración del scraping:** {metadata['scrape_duration_seconds']} segundos
    """
    )

st.title("🎬 Ocupación de salas - Kinepolis")

df = pd.read_csv("ocupacion_kinepolis.csv")

# =========================
# Métricas rápidas
# =========================

col1, col2, col3 = st.columns(3)

col1.metric(
    "Sesiones analizadas",
    len(df)
)

col2.metric(
    "Butacas totales",
    df["total"].sum()
)

col3.metric(
    "Ocupación media",
    f"{df['ocupacion'].mean():.1f}%"
)

# =========================
# Gráfico de ocupación
# =========================

fig = px.bar(
    df,
    x="hora",
    y="ocupacion",
    title="Ocupación por sesión",
)

st.plotly_chart(fig, use_container_width=True)

# =========================
# Tabla interactiva
# =========================

st.subheader("Datos de sesiones")

st.dataframe(df)