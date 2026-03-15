from playwright.sync_api import sync_playwright
import re
import csv
import random
import time
import json
from datetime import datetime

start_time = time.time()

URL = "https://kinepolis.es/?complex=KVAL&main_section=hoy"

resultados = []


# =============================
# Contar butacas con JS
# =============================
def contar_butacas(page):

    data = page.evaluate("""
    () => {

        const seats = document.querySelectorAll("label[data-seats-status]");

        let occupied = 0;

        for (let i = 0; i < seats.length; i++) {

            if (seats[i].dataset.seatsStatus === "1") {
                occupied++;
            }

        }

        return {
            total: seats.length,
            occupied: occupied
        };
    }
    """)

    return data["total"], data["occupied"]


# =============================
# Abrir sesión inicial
# =============================
def abrir_sesion(page, vsessionid):

    url = f"https://kinepolis.es/direct-vista-redirect/{vsessionid}/0/KVAL/0"

    page.goto(url)

    page.wait_for_selector("select")

    try:
        page.select_option("select", "1")
    except:
        pass

    page.get_by_role("button", name=re.compile("continuar|continue", re.I)).click()

    page.wait_for_selector("label[data-seats-status]")


# =============================
# Cargar nuevas sesiones
# =============================
def cargar_sesion(page, vsessionid):

    url = f"https://kinepolis.es/direct-vista-redirect/{vsessionid}/0/KVAL/0"

    page.goto(url)

    page.wait_for_selector("label[data-seats-status]")


# =============================
# SCRAPER
# =============================
with sync_playwright() as p:

    # Chrome real con perfil persistente
    context = p.chromium.launch_persistent_context(
        user_data_dir="kinepolis_profile",
        channel="chrome",
        headless=False,
        viewport={"width": 1920, "height": 1080}
    )

    page = context.new_page()

    print("Abriendo cartelera...")

    page.goto(URL)

    # esperar carga
    page.wait_for_timeout(random.randint(4000,6000))

    # aceptar cookies si aparecen
    try:
        page.locator("button:has-text('Aceptar')").click(timeout=3000)
    except:
        pass

    # esperar sesiones
    page.wait_for_selector("a.megatix-click-handler")

    # =============================
    # EXTRAER SESIONES
    # =============================

    sesiones = page.evaluate("""
    () => {

        const sesiones = [];

        const elementos = document.querySelectorAll("a.megatix-click-handler");

        for (const el of elementos) {

            const vsessionid = el.dataset.vsessionid;

            const timeBlock = el.querySelector(".time-block");

            if (!timeBlock) continue;

            const hora = timeBlock.innerText.trim();

            sesiones.push({
                hora: hora,
                vsessionid: vsessionid
            });

        }

        return sesiones;
    }
    """)

    print("Sesiones encontradas:", len(sesiones))

    # =============================
    # ANALIZAR OCUPACIÓN
    # =============================

    seat_page = context.new_page()

    print("\nAnalizando ocupación...\n")

    abrir_sesion(seat_page, sesiones[0]["vsessionid"])

    total, ocupadas = contar_butacas(seat_page)

    resultados.append({
        "hora": sesiones[0]["hora"],
        "total": total,
        "ocupadas": ocupadas,
        "libres": total - ocupadas,
        "ocupacion": round((ocupadas / total) * 100, 2)
    })

    # resto de sesiones
    for sesion in sesiones[1:]:

        time.sleep(random.uniform(1.0, 2.5))

        cargar_sesion(seat_page, sesion["vsessionid"])

        total, ocupadas = contar_butacas(seat_page)

        ocupacion = round((ocupadas / total) * 100, 2)

        print(sesion["hora"], "| ocupación:", ocupacion, "%")

        resultados.append({
            "hora": sesion["hora"],
            "total": total,
            "ocupadas": ocupadas,
            "libres": total - ocupadas,
            "ocupacion": ocupacion
        })

    context.close()


# =============================
# GUARDAR CSV
# =============================

with open(
    "ocupacion_kinepolis.csv",
    "w",
    newline="",
    encoding="utf-8"
) as f:

    writer = csv.DictWriter(
        f,
        fieldnames=[
            "hora",
            "total",
            "ocupadas",
            "libres",
            "ocupacion"
        ]
    )

    writer.writeheader()

    writer.writerows(resultados)

print("\nDatos guardados en ocupacion_kinepolis.csv")

end_time = time.time()

metadata = {
    "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "scrape_duration_seconds": round(end_time - start_time, 2)
}

with open("metadata.json", "w") as f:
    json.dump(metadata, f)

print("Metadata guardada")