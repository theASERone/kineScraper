from playwright.sync_api import sync_playwright
import re
import csv
import json
import time                # NUEVO
from datetime import datetime, timedelta   # NUEVO
import pandas as pd
import os

fecha_hoy = datetime.now().strftime("%Y-%m-%d")

URL = "https://kinepolis.es/?complex=KVAL&main_section=hoy"

MAX_PAGES = 12

patron_hora = re.compile(r"\b([01]?\d|2[0-3]):[0-5]\d\b")

resultados = []

# ======================
# TIEMPO DE INICIO
# ======================

inicio_script = time.time()  # NUEVO
hora_inicio = datetime.now() # NUEVO

print("\n==============================")
print("INFORME KINEPOLIS")
print("Inicio del informe:", hora_inicio.strftime("%Y-%m-%d %H:%M:%S"))
print("==============================\n")


def analizar_sesion(page, sesion):

    hora = sesion["hora"]
    vsessionid = sesion["vsessionid"]

    try:

        seat_url = f"https://kinepolis.es/direct-vista-redirect/{vsessionid}/0/KVAL/0"

        page.goto(seat_url, wait_until="domcontentloaded")

        page.wait_for_selector("select", timeout=8000)

        selects = page.locator("select")

        for i in range(selects.count()):

            select = selects.nth(i)

            try:

                opciones = select.locator("option").all_inner_texts()

                if "1" in opciones:

                    select.select_option("1")
                    break

            except:
                pass

        botones = page.locator("button")

        for i in range(botones.count()):

            texto = botones.nth(i).inner_text().lower()

            if "continuar" in texto or "continue" in texto:

                botones.nth(i).click()
                break

        page.wait_for_selector(
            "label[data-seats-status]",
            timeout=10000
        )

        titulo = "Desconocido"

        titulo_element = page.locator("h2.order-title")

        if titulo_element.count() > 0:
            titulo = titulo_element.first.inner_text().strip()

        ocupadas = page.locator(
            'label[data-seats-status="1"]'
        ).count()

        total = page.locator(
            "label[data-seats-status]"
        ).count()

        ocupacion = round((ocupadas / total) * 100, 2) if total else 0

        print(
            titulo,
            "|",
            hora,
            "| ocupadas:",
            ocupadas,
            "| ocupación:",
            ocupacion,
            "%"
        )

        return {
            "fecha": fecha_hoy,
            "pelicula": titulo,
            "hora": hora,
            "total": total,
            "ocupadas": ocupadas,
            "libres": total - ocupadas,
            "ocupacion": ocupacion
        }

    except Exception as e:

        print("Sesión omitida:", hora, "| error:", e)

        return None


with sync_playwright() as p:

    browser = p.chromium.launch(
    
        channel="chrome",
        headless=True,
        args=["--disable-blink-features=AutomationControlled"]
    )

    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        locale="es-ES",
    )
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined})
        """)
    context.route(
        "**/*",
        lambda route: route.abort()
        if route.request.resource_type in ["image", "stylesheet", "font", "media"]
        else route.continue_()
    )

    page = context.new_page()

    print("Abriendo cartelera...")

    page.goto(URL)
    print("altura pagina:", page.evaluate("document.body.scrollHeight"))
    print("html contiene sesiones:", "data-vsessionid" in page.content())

    try:
        page.locator("button:has-text('Aceptar')").click(timeout=3000)
    except:
        pass

    page.wait_for_timeout(3000)
    page.mouse.wheel(0, 3000)

    page.wait_for_selector("[data-vsessionid]", timeout=20000)

    enlaces = page.locator("[data-vsessionid]")

    sesiones = []

    for i in range(enlaces.count()):

        texto = enlaces.nth(i).inner_text().strip()

        if patron_hora.match(texto):

            vsessionid = enlaces.nth(i).get_attribute("data-vsessionid")

            sesiones.append({
                "hora": texto,
                "vsessionid": vsessionid
            })

    print("Sesiones encontradas:", len(sesiones))

    for i in range(0, len(sesiones), MAX_PAGES):

        lote = sesiones[i:i + MAX_PAGES]

        pages = [context.new_page() for _ in lote]

        for page_instance, sesion in zip(pages, lote):

            r = analizar_sesion(page_instance, sesion)

            if r:
                resultados.append(r)

        for page_instance in pages:
            page_instance.close()

    browser.close()


# ======================
# RESUMEN POR HORA
# ======================

resumen_horas = {}

for r in resultados:

    hora = r["hora"]

    if hora not in resumen_horas:

        resumen_horas[hora] = {
            "total": 0,
            "ocupadas": 0
        }

    resumen_horas[hora]["total"] += r["total"]
    resumen_horas[hora]["ocupadas"] += r["ocupadas"]

print("\nBUTACAS OCUPADAS POR HORA\n")

for hora, datos in sorted(resumen_horas.items()):

    print(
        hora,
        "| butacas ocupadas:",
        datos["ocupadas"],
        "| capacidad total:",
        datos["total"]
    )


# ======================
# CSV
# ======================

# with open(
    # "ocupacion_kinepolis.csv",
    # "w",
    # newline="",
    # encoding="utf-8"
# ) as f:

    # writer = csv.DictWriter(
        # f,
        # fieldnames=[
            # "pelicula",
            # "hora",
            # "total",
            # "ocupadas",
            # "libres",
            # "ocupacion"
        # ]
    # )

    # writer.writeheader()
    # writer.writerows(resultados)
archivo = "ocupacion_kinepolis.csv"

df_nuevo = pd.DataFrame(resultados)

if os.path.exists(archivo):

    df_existente = pd.read_csv(archivo)

    df_total = pd.concat([df_existente, df_nuevo])

    # eliminar duplicados
    df_total = df_total.drop_duplicates(
        subset=["fecha", "pelicula", "hora"],
        keep="last"
    )

else:

    df_total = df_nuevo

# ======================
# FILTRAR ÚLTIMOS 15 DÍAS
# ======================

df_total["fecha"] = pd.to_datetime(df_total["fecha"])

limite = datetime.now() - timedelta(days=15)

df_total = df_total[df_total["fecha"] >= limite]

df_total["fecha"] = df_total["fecha"].dt.strftime("%Y-%m-%d")

# ======================
# GUARDAR CSV
# ======================

df_total.to_csv(
    archivo,
    index=False,
    encoding="utf-8-sig"
)

print("\nDatos guardados en ocupacion_kinepolis.csv")



# ======================
# TIEMPO TOTAL
# ======================

fin_script = time.time()  # NUEVO
duracion = round(fin_script - inicio_script, 2)

print("\n==============================")
print("Informe generado:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
print("Tiempo total de ejecución:", duracion, "segundos")
print("==============================")

# ======================
# METADATA JSON
# ======================

fin_script = time.time()

hora_fin = datetime.now()

duracion = round(fin_script - inicio_script, 2)

metadata = {
    "inicio_informe": hora_inicio.strftime("%Y-%m-%d %H:%M:%S"),
    "fin_informe": hora_fin.strftime("%Y-%m-%d %H:%M:%S"),
    "duracion_segundos": duracion,
    "sesiones_analizadas": len(resultados)
}

with open("metadata.json", "w", encoding="utf-8") as f:
    json.dump(metadata, f, indent=4, ensure_ascii=False)

print("\nMetadata guardada en metadata.json")

import subprocess

def subir_a_github():

    subprocess.run(["git", "add", "ocupacion_kinepolis.csv"])
    subprocess.run(["git", "add", "metadata.json"])

    subprocess.run([
        "git",
        "commit",
        "-m",
        "actualizacion automatica datos kinepolis"
    ])

    subprocess.run(["git", "push"])
    print("Subido a GitHub")
    
subir_a_github()
