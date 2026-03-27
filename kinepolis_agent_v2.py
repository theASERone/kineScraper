import os
import json
import re
import subprocess
import time
from datetime import datetime, timedelta
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import pandas as pd
from playwright.sync_api import sync_playwright

URL = "https://kinepolis.es/?complex=KVAL&main_section=hoy"

MAX_PAGES = 12
DEBUG_DURACION = os.getenv("DEBUG_DURACION", "0").strip().lower() in {"1", "true", "yes", "si"}

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

COLUMNAS_RESULTADO = [
    "fecha",
    "pelicula",
    "hora",
    "hora_fin",
    "duracion_minutos",
    "sala",
    "total",
    "ocupadas",
    "libres",
    "ocupacion",
]


def asegurar_columnas_resultado(df):
    if df is None:
        df = pd.DataFrame()

    df = df.copy()

    for columna in COLUMNAS_RESULTADO:
         if columna not in df.columns:
            df[columna] = "" if columna in {"fecha", "pelicula", "hora", "hora_fin", "sala"} else 0
    return df[COLUMNAS_RESULTADO]


def cargar_csv_existente(ruta_csv):
    if not os.path.exists(ruta_csv) or os.path.getsize(ruta_csv) == 0:
        return asegurar_columnas_resultado(pd.DataFrame())

    try:
        df_existente = pd.read_csv(ruta_csv)
    except pd.errors.EmptyDataError:
        return asegurar_columnas_resultado(pd.DataFrame())

    return asegurar_columnas_resultado(df_existente)

# ======================
# TIEMPO DE INICIO
# ======================

MADRID_TZ = ZoneInfo("Europe/Madrid")
UTC_TZ = ZoneInfo("UTC")

inicio_script = time.time()  # NUEVO
hora_inicio = datetime.now(UTC_TZ) # NUEVO
hora_referencia_madrid = hora_inicio.astimezone(MADRID_TZ)

print("\n==============================")
print("INFORME KINEPOLIS")
print("Inicio del informe:", hora_referencia_madrid.strftime("%Y-%m-%d %H:%M:%S"))
print("==============================\n")


def normalizar_texto(texto):
    return " ".join(texto.replace("\xa0", " ").split())


def normalizar_clave_pelicula(titulo):
    return normalizar_texto(titulo).strip().lower()


def cargar_cache_duraciones(ruta_cache):
    if not os.path.exists(ruta_cache) or os.path.getsize(ruta_cache) == 0:
        return {}

    try:
        with open(ruta_cache, "r", encoding="utf-8") as f:
            contenido = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}

    if not isinstance(contenido, dict):
        return {}

    cache_limpio = {}
    for clave, valor in contenido.items():
        try:
            minutos = int(valor)
            if minutos > 0:
                cache_limpio[str(clave)] = minutos
        except (ValueError, TypeError):
            continue

    return cache_limpio


def guardar_cache_duraciones(ruta_cache, cache_duraciones):
    with open(ruta_cache, "w", encoding="utf-8") as f:
        json.dump(cache_duraciones, f, indent=2, ensure_ascii=False, sort_keys=True)


def extraer_minutos_desde_texto(texto):
    if not texto:
        return None

    match = re.search(r"(\d{2,3})\s*(?:min|mins|minutos)\b", texto, re.IGNORECASE)
    if not match:
        match = re.search(r"\b(\d{1,2})\s*h(?:oras?)?\s*(\d{1,2})?\s*m?\b", texto, re.IGNORECASE)
        if match:
            horas = int(match.group(1))
            minutos_extra = int(match.group(2) or 0)
            total = horas * 60 + minutos_extra
            return total if total > 0 else None

    if not match:
        return None

    minutos = int(match.group(1))
    return minutos if minutos > 0 else None


def extraer_duracion_desde_bloques_label_value(page):
    bloques = page.locator("div.movie-duration-wrapper")

    try:
        total = bloques.count()
    except Exception as exc:
        debug_duracion(f"Bloques label/value no accesibles: {exc}")
        return None

    for i in range(total):
        bloque = bloques.nth(i)
        try:
            etiqueta = normalizar_texto(bloque.locator(".label-wrapper").inner_text())
            valor = normalizar_texto(bloque.locator(".value-wrapper").inner_text())
        except Exception as exc:
            debug_duracion(f"Bloque duration[{i}] no legible: {exc}")
            continue

        debug_duracion(f"Bloque duration[{i}] etiqueta={etiqueta!r} valor={valor!r}")

        if "duración" not in etiqueta.lower() and "duracion" not in etiqueta.lower():
            continue

        minutos = extraer_minutos_desde_texto(valor)
        if not minutos and valor.isdigit():
            minutos = int(valor)

        if minutos:
            return minutos

    return None


def sumar_minutos_a_hora(hora, minutos):
    if not hora or not isinstance(minutos, int) or minutos <= 0:
        return ""

    try:
        inicio = datetime.strptime(hora, "%H:%M")
    except ValueError:
        return ""

    return (inicio + timedelta(minutes=minutos)).strftime("%H:%M")


def debug_duracion(mensaje):
    if DEBUG_DURACION:
        print(f"[DEBUG DURACION] {mensaje}")


def extraer_duracion_desde_detalle(page, contexto="detalle"):
    selectores_duracion = [
        "div.movie-duration-wrapper",
        "[class*='duration']",
        "[class*='runtime']",
        "[data-testid*='duration']",
        "[data-testid*='runtime']",
        "time",
    ]

    debug_duracion(f"Contexto: {contexto} | URL: {page.url}")

    try:
        page.wait_for_selector("div.movie-duration-wrapper, [class*='duration'], [class*='runtime']", timeout=5000)
    except Exception as exc:
        debug_duracion(f"No apareció selector de duración tras espera inicial: {exc}")

    minutos_bloque = extraer_duracion_desde_bloques_label_value(page)
    if minutos_bloque:
        debug_duracion(f"Duración obtenida desde bloque label/value: {minutos_bloque}")
        return minutos_bloque

    for selector in selectores_duracion:
        locator = page.locator(selector)
        try:
            total = locator.count()
        except Exception as exc:
            debug_duracion(f"Selector {selector!r} fallo al contar: {exc}")
            continue

        debug_duracion(f"Selector {selector!r} -> {total} coincidencias")

        if total == 0:
            continue

        limite = min(total, 3)
        for i in range(limite):
            try:
                texto_duracion = normalizar_texto(locator.nth(i).inner_text())
            except Exception as exc:
                debug_duracion(f"Selector {selector!r}[{i}] fallo al leer texto: {exc}")
                continue

            minutos = extraer_minutos_desde_texto(texto_duracion)
            debug_duracion(
                f"Selector {selector!r}[{i}] texto={texto_duracion!r} -> minutos={minutos}"
            )
            if minutos:
                return minutos

    try:
        texto_pagina = normalizar_texto(page.locator("body").inner_text())
    except Exception as exc:
        debug_duracion(f"No se pudo leer el texto del body: {exc}")
        return None

    minutos = extraer_minutos_desde_texto(texto_pagina)
    debug_duracion(
        f"Fallback body -> minutos={minutos} | muestra={texto_pagina[:400]!r}"
    )
    return minutos


def extraer_enlaces_peliculas_desde_cartelera(page):
    peliculas = page.evaluate(
        """
        () => {
          const resultados = [];
          const sesiones = Array.from(document.querySelectorAll("[data-vsessionid]"));
          for (const sesion of sesiones) {
            const card = sesion.closest("article, li, .movie, .movie-item, .session, .grid-item, .agenda-film, .showtimes-film");
            const scope = card || sesion.parentElement || sesion;
            const enlace = scope.querySelector("a[href]:not([href^='javascript'])");
            if (!enlace) continue;

            const tituloEl = scope.querySelector("h1, h2, h3, h4, .movie-title, .title");
            const titulo = (tituloEl?.textContent || enlace.getAttribute("title") || enlace.textContent || "").trim();
            const href = enlace.getAttribute("href");
            if (!href || !titulo) continue;

            resultados.push({ titulo, href });
          }
          return resultados;
        }
        """
    )

    peliculas_unicas = {}
    for pelicula in peliculas:
        titulo = normalizar_texto(str(pelicula.get("titulo", "")))
        href = str(pelicula.get("href", "")).strip()
        if not titulo or not href:
            continue

        clave = normalizar_clave_pelicula(titulo)
        if clave not in peliculas_unicas:
            peliculas_unicas[clave] = {
                "titulo": titulo,
                "url": urljoin(URL, href),
            }

    return peliculas_unicas


def obtener_duracion_desde_ficha(context, titulo, url_detalle, cache_duraciones, cache_modificada):
    clave = normalizar_clave_pelicula(titulo)
    duracion_cache = cache_duraciones.get(clave, 0)

    if duracion_cache:
        debug_duracion(f"Cache hit para {titulo!r}: {duracion_cache} min")
        return duracion_cache

    if not url_detalle:
        debug_duracion(f"Sin URL de detalle para {titulo!r}")
        return 0

    page_detalle = context.new_page()

    try:
        debug_duracion(f"Abriendo ficha para {titulo!r}: {url_detalle}")
        page_detalle.goto(url_detalle, wait_until="domcontentloaded", timeout=15000)
        minutos = extraer_duracion_desde_detalle(page_detalle, contexto="ficha")
        if minutos:
            cache_duraciones[clave] = minutos
            cache_modificada["valor"] = True
            print(f"DuraciÃ³n guardada: {titulo} -> {minutos} min")
            return minutos

        debug_duracion(f"No se encontrÃ³ duraciÃ³n en la ficha de {titulo!r}")
        return 0
    except Exception as exc:
        debug_duracion(f"Fallo abriendo ficha de {titulo!r}: {exc}")
        return 0
    finally:
        page_detalle.close()


def extraer_sesiones_desde_cartelera(page, fecha_referencia):
    sesiones = page.evaluate(
        """
        () => {
          const resultados = [];
          const sesiones = Array.from(document.querySelectorAll("[data-vsessionid]"));

          const selectoresTitulo = [
            ".title-bar-wrapper .title a[href]:not([href^='javascript'])",
            ".title-wrapper .title a[href]:not([href^='javascript'])",
            ".movie-overview-title",
            "h1 a[href]:not([href^='javascript'])",
            "h2 a[href]:not([href^='javascript'])",
            "h3 a[href]:not([href^='javascript'])",
            "h4 a[href]:not([href^='javascript'])",
          ];

          const buscarContenedorPelicula = (sesion) => {
            let nodo = sesion;

            while (nodo && nodo !== document.body) {
              const tieneTitulo = selectoresTitulo.some((selector) => nodo.querySelector?.(selector));
              if (tieneTitulo) return nodo;
              nodo = nodo.parentElement;
            }

            return sesion.parentElement || sesion;
          };

          const buscarEnlaceDetalle = (scope) => {
            const candidatos = [
              scope.querySelector(".title-bar-wrapper .title a[href]:not([href^='javascript'])"),
              scope.querySelector(".title-wrapper .title a[href]:not([href^='javascript'])"),
              scope.querySelector(".movie-overview-title")?.closest("a[href]:not([href^='javascript'])"),
              scope.querySelector("h1 a[href]:not([href^='javascript'])"),
              scope.querySelector("h2 a[href]:not([href^='javascript'])"),
              scope.querySelector("h3 a[href]:not([href^='javascript'])"),
              scope.querySelector("h4 a[href]:not([href^='javascript'])"),
              scope.querySelector(".movie-title a[href]:not([href^='javascript'])"),
              scope.querySelector(".title a[href]:not([href^='javascript'])"),
              scope.querySelector("a.movie-title[href]:not([href^='javascript'])"),
              scope.querySelector("a.title[href]:not([href^='javascript'])"),
              scope.querySelector("a[href*='/films/']:not([href^='javascript'])"),
              scope.querySelector("a[href*='/peliculas/']:not([href^='javascript'])"),
              scope.querySelector("a[href*='/movie/']:not([href^='javascript'])"),
            ].filter(Boolean);

            if (candidatos.length > 0) return candidatos[0];

            return null;
          };

          for (const sesion of sesiones) {
            const textoHora = (sesion.textContent || "").trim();
            const vsessionid = sesion.getAttribute("data-vsessionid");
            const scope = buscarContenedorPelicula(sesion);
            const enlaceTitulo = buscarEnlaceDetalle(scope);
            const tituloEl =
              scope.querySelector(".movie-overview-title") ||
              scope.querySelector(".title-bar-wrapper .title") ||
              scope.querySelector(".title-wrapper .title") ||
              scope.querySelector("h1, h2, h3, h4, .movie-title");
            const titulo = (
              tituloEl?.textContent ||
              enlaceTitulo?.getAttribute("title") ||
              enlaceTitulo?.textContent ||
              ""
            ).trim();
            const href = enlaceTitulo?.getAttribute("href") || "";

            if (href === "#" || href === "#!") {
              continue;
            }

            resultados.push({
              hora: textoHora,
              vsessionid,
              titulo,
              href,
            });
          }

          return resultados;
        }
        """
    )

    sesiones_limpias = []
    for sesion in sesiones:
        hora = normalizar_texto(str(sesion.get("hora", "")))
        vsessionid = str(sesion.get("vsessionid", "")).strip()
        titulo = normalizar_texto(str(sesion.get("titulo", "")))
        href = str(sesion.get("href", "")).strip()

        if not vsessionid or not patron_hora.match(hora):
            continue

        url_detalle = urljoin(URL, href) if href else ""
        if DEBUG_DURACION and (not titulo or not url_detalle):
            print(
                f"[DEBUG DURACION] Sesion sin detalle completo | hora={hora!r} | "
                f"titulo={titulo!r} | href={href!r}"
            )

        sesiones_limpias.append({
            "hora": hora,
            "vsessionid": vsessionid,
            "fecha_referencia": fecha_referencia,
            "titulo": titulo,
            "url_detalle": url_detalle,
        })

    return sesiones_limpias


def rellenar_cache_duraciones_desde_enlaces(context, peliculas_cartelera, cache_duraciones):
    nuevos_registros = 0
    page_detalle = context.new_page()

    try:
        for clave, datos in peliculas_cartelera.items():
            if clave in cache_duraciones:
                continue

            url_detalle = datos["url"]
            try:
                page_detalle.goto(url_detalle, wait_until="domcontentloaded", timeout=15000)
            except Exception:
                continue

            minutos = extraer_duracion_desde_detalle(page_detalle, contexto="cartelera")
            if minutos:
                cache_duraciones[clave] = minutos
                nuevos_registros += 1
                print(f"Duración guardada: {datos['titulo']} -> {minutos} min")
    finally:
        page_detalle.close()

    return nuevos_registros


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


def analizar_sesion(page, context, sesion, cache_duraciones, cache_modificada):

    hora = sesion["hora"]
    vsessionid = sesion["vsessionid"]
    fecha_referencia = sesion["fecha_referencia"]
    titulo_cartelera = normalizar_texto(sesion.get("titulo", ""))
    url_detalle = sesion.get("url_detalle", "")

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

        titulo = titulo_cartelera

        titulo_element = page.locator("h2.order-title")

        if not titulo and titulo_element.count() > 0:
            titulo = titulo_element.first.inner_text().strip()

        if not titulo:
            titulo = "Desconocido"

        fecha_sesion, sala = extraer_detalles_sesion(page, fecha_referencia)

        clave_pelicula = normalizar_clave_pelicula(titulo_cartelera or titulo)
        duracion_minutos = cache_duraciones.get(clave_pelicula, 0)

        if not duracion_minutos:
            duracion_minutos = obtener_duracion_desde_ficha(
                context,
                titulo_cartelera or titulo,
                url_detalle,
                cache_duraciones,
                cache_modificada,
            )

        hora_fin = sumar_minutos_a_hora(hora, int(duracion_minutos) if duracion_minutos else 0)

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
            "->",
            hora_fin or "N/D",
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
            "hora_fin": hora_fin,
            "duracion_minutos": int(duracion_minutos) if duracion_minutos else 0,
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

    ruta_cache_duraciones = "duraciones_peliculas.json"
    cache_duraciones = cargar_cache_duraciones(ruta_cache_duraciones)
    cache_modificada = {"valor": False}

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
    sesiones = extraer_sesiones_desde_cartelera(page, hora_inicio)
    # Duraciones: ahora se resuelven por sesion al abrir la ficha solo si faltan en cache.

    print("Sesiones encontradas:", len(sesiones))

    for i in range(0, len(sesiones), MAX_PAGES):

        lote = sesiones[i:i + MAX_PAGES]

        pages = [context.new_page() for _ in lote]

        for page_instance, sesion in zip(pages, lote):

            r = analizar_sesion(page_instance, context, sesion, cache_duraciones, cache_modificada)

            if r:
                resultados.append(r)

        for page_instance in pages:
            page_instance.close()

    browser.close()

if cache_modificada["valor"]:
    guardar_cache_duraciones(ruta_cache_duraciones, cache_duraciones)
    print("Cache de duraciones actualizada.")


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
    subprocess.run(["git", "add", "duraciones_peliculas.json"])

    subprocess.run([
        "git",
        "commit",
        "-m",
        "actualizacion automatica datos kinepolis"
    ])

    subprocess.run(["git", "push"])
    print("Subido a GitHub")
    
subir_a_github()
