import os
import json
import re
import subprocess
import time
from datetime import datetime, timedelta

import pandas as pd
from playwright.sync_api import sync_playwright

URL = "https://kinepolis.es/?complex=KVAL&main_section=hoy"

MAX_PAGES = 12

patron_hora = re.compile(r"\b([01]?\d|2[0-3]):[0-5]\d\b")
patron_fecha_iso = re.compile(r"(\d{4}-\d{2}-\d{2})")
patron_fecha_es = re.compile(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})")
patron_sala = re.compile(r"\b(?:sala|screen|auditorium)\s*[:\-]?\s*([A-Za-z0-9]+)\b", re.IGNORECASE)
patron_codigo_sala = re.compile(r"^[A-Za-z]?\d{1,3}[A-Za-z]?$")

MESES_ES = {
    "ene": 1,
    "enero": 1,
    "feb": 2,
    "febrero": 2,
    "mar": 3,
    "marzo": 3,
    "abr": 4,
    "abril": 4,
    "may": 5,
    "mayo": 5,
    "jun": 6,
    "junio": 6,
    "jul": 7,
    "julio": 7,
    "ago": 8,
    "agosto": 8,
    "sep": 9,
    "sept": 9,
    "septiembre": 9,
    "oct": 10,
    "octubre": 10,
    "nov": 11,
    "noviembre": 11,
    "dic": 12,
    "diciembre": 12,
}

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


def normalizar_texto(texto):
    return " ".join(texto.replace("\xa0", " ").split())


def extraer_fecha_desde_texto(texto, fecha_referencia):
    texto_normalizado = normalizar_texto(texto)

    match_iso = patron_fecha_iso.search(texto_normalizado)

    if match_iso:
        return match_iso.group(1)

    match_es = patron_fecha_es.search(texto_normalizado)

    if match_es:
        dia, mes, anio = match_es.groups()
        anio = int(anio)
        if anio < 100:
            anio += 2000
        return datetime(anio, int(mes), int(dia)).strftime("%Y-%m-%d")

    texto_limpio = re.sub(r"[.,]", " ", texto_normalizado.lower())
    tokens = texto_limpio.split()

    for i, token in enumerate(tokens[:-1]):
        if not token.isdigit():
            continue

        mes = MESES_ES.get(tokens[i + 1])

        if not mes:
            continue

        dia = int(token)
        anio = fecha_referencia.year

        if i + 2 < len(tokens) and tokens[i + 2].isdigit() and len(tokens[i + 2]) == 4:
            anio = int(tokens[i + 2])

        fecha = datetime(anio, mes, dia)

        if abs((fecha - fecha_referencia).days) > 330:
            fecha = datetime(anio + 1, mes, dia)

        return fecha.strftime("%Y-%m-%d")

    return fecha_referencia.strftime("%Y-%m-%d")


def extraer_sala_desde_texto(texto):
    texto_normalizado = normalizar_texto(texto)
    match_sala = patron_sala.search(texto_normalizado)

    if match_sala:
        return match_sala.group(1).upper()

    return ""


def extraer_sala_desde_order_list(page):
    items = page.locator("div.order-list-item")

    for i in range(items.count()):
        item = items.nth(i)
        texto_item = normalizar_texto(item.inner_text())

        if "sala" not in texto_item.lower():
            continue

        valores = item.locator("div.order-list-item-value")

        for j in range(valores.count()):
            valor = normalizar_texto(valores.nth(j).inner_text())

            if not valor:
                continue

            sala = extraer_sala_desde_texto(valor)

            if sala:
                return sala

            valor_limpio = valor.replace(" ", "")

            if patron_codigo_sala.fullmatch(valor_limpio):
                return valor_limpio.upper()

        sala = extraer_sala_desde_texto(texto_item)

        if sala:
            return sala

    return ""


def extraer_detalles_sesion(page, fecha_referencia):
    info_element = page.locator("div.order-additional-info")

    if info_element.count() == 0:
        return fecha_referencia.strftime("%Y-%m-%d"), extraer_sala_desde_order_list(page)

    texto_info = info_element.first.inner_text().strip()
    fecha_sesion = extraer_fecha_desde_texto(texto_info, fecha_referencia)
    sala = extraer_sala_desde_order_list(page)

    return fecha_sesion, sala


def analizar_sesion(page, sesion):

    hora = sesion["hora"]
    vsessionid = sesion["vsessionid"]
    fecha_referencia = sesion["fecha_referencia"]

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

        fecha_sesion, sala = extraer_detalles_sesion(page, fecha_referencia)

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
            fecha_sesion,
            "|",
            hora,
            "| sala:",
            sala or "N/D",
            "|",
            "| ocupadas:",
            ocupadas,
            "| ocupación:",
            ocupacion,
            "%"
        )
        return {
            "fecha": fecha_sesion,
            "pelicula": titulo,
            "hora": hora,
            "sala": sala,
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
                "vsessionid": vsessionid,
                "fecha_referencia": hora_inicio,
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

df_nuevo = asegurar_columnas_resultado(pd.DataFrame(resultados))

df_existente = cargar_csv_existente(archivo)

df_total = pd.concat([df_existente, df_nuevo], ignore_index=True)

columnas_deduplicacion = ["fecha", "pelicula", "hora"]

if "sala" in df_total.columns:
    df_total["sala"] = df_total["sala"].fillna("").astype(str)
    columnas_deduplicacion.append("sala")

df_total = df_total.drop_duplicates(
    subset=columnas_deduplicacion,
    keep="last"
)

# ======================
# FILTRAR ÚLTIMOS 15 DÍAS
# ======================

if not df_total.empty:

    df_total["fecha"] = pd.to_datetime(df_total["fecha"], errors="coerce")

    limite = datetime.now() - timedelta(days=15)

    df_total = df_total[df_total["fecha"].notna()]
    df_total = df_total[df_total["fecha"] >= limite]

    df_total["fecha"] = df_total["fecha"].dt.strftime("%Y-%m-%d")

df_total = asegurar_columnas_resultado(df_total)

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
