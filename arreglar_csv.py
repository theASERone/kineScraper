import pandas as pd

# leer el archivo ignorando bytes corruptos
with open("ocupacion_kinepolis.csv", "r", encoding="latin-1", errors="ignore") as f:
    df = pd.read_csv(f)

# volver a guardar en UTF-8 limpio
df.to_csv(
    "ocupacion_kinepolis.csv",
    index=False,
    encoding="utf-8-sig"
)

print("CSV reparado y convertido a UTF-8")