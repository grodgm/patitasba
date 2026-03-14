"""
PatitasBA — Actualizador automático de donaciones
==================================================
Consulta la API de MercadoPago, suma los pagos aprobados
del mes actual y actualiza donaciones.json automáticamente.

Configuración (una sola vez):
    1. Creá tu access token en https://www.mercadopago.com.ar/developers
    2. Guardalo en un archivo llamado mp_token.txt en esta misma carpeta
    3. ¡Listo! El deploy lo llama automáticamente

Uso manual:
    python3 actualizar_donaciones.py
"""

import json
import urllib.request
import urllib.parse
import ssl
from datetime import datetime
from pathlib import Path

DONACIONES_FILE = Path("donaciones.json")
TOKEN_FILE      = Path("mp_token.txt")
OBJETIVO        = 200_000   # ARS — cambiá este número si cambia la meta
REFUGIOS        = 5         # cantidad de refugios entre los que se divide

def leer_token():
    """Lee el Access Token de MercadoPago desde mp_token.txt."""
    if TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text().strip()
        if token:
            return token
    return None

def obtener_pagos_del_mes(token):
    """
    Consulta la API de MP y devuelve el total recibido en el mes actual.
    Solo cuenta pagos con status=approved.
    """
    hoy    = datetime.now()
    inicio = hoy.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    desde  = inicio.strftime("%Y-%m-%dT00:00:00.000-03:00")
    hasta  = hoy.strftime("%Y-%m-%dT23:59:59.000-03:00")

    params = urllib.parse.urlencode({
        "sort":       "date_created",
        "criteria":   "desc",
        "limit":      100,
        "begin_date": desde,
        "end_date":   hasta,
    })
    url = f"https://api.mercadopago.com/v1/payments/search?{params}"

    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}"}
    )

    total = 0.0
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            for pago in data.get("results", []):
                if pago.get("status") == "approved":
                    total += pago.get("transaction_amount", 0)
        print(f"   💰 Total recibido en {hoy.strftime('%B %Y')}: ${total:,.0f} ARS")
        return total
    except Exception as e:
        print(f"   ⚠️  Error consultando MercadoPago: {e}")
        return None

def actualizar_donaciones(recaudado):
    """Actualiza donaciones.json con el monto recibido."""
    hoy = datetime.now()

    # Leer datos actuales o usar defaults
    if DONACIONES_FILE.exists():
        with open(DONACIONES_FILE, encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {}

    MESES = {
        1:"Enero", 2:"Febrero", 3:"Marzo", 4:"Abril",
        5:"Mayo", 6:"Junio", 7:"Julio", 8:"Agosto",
        9:"Septiembre", 10:"Octubre", 11:"Noviembre", 12:"Diciembre"
    }

    data["mes"]       = f"{MESES[hoy.month]} {hoy.year}"
    data["objetivo"]  = OBJETIVO
    data["recaudado"] = round(recaudado)

    if "alias" not in data:
        data["alias"] = "patitasba.mp"

    with open(DONACIONES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    pct = round((recaudado / OBJETIVO) * 100)
    por_refugio = round(recaudado / REFUGIOS)
    print(f"   📊 Meta: {pct}% ({pct}% de ${OBJETIVO:,})")
    print(f"   🏠 Corresponde ~${por_refugio:,} por refugio")
    print(f"   ✅ donaciones.json actualizado")


if __name__ == "__main__":
    print("💰 PatitasBA — Actualizando donaciones...")

    token = leer_token()

    if not token:
        print("")
        print("⚠️  No encontré el Access Token de MercadoPago.")
        print("   Para configurarlo:")
        print("   1. Andá a https://www.mercadopago.com.ar/developers/panel")
        print("   2. Creá una aplicación o usá una existente")
        print("   3. Copiá el 'Access Token de producción'")
        print("   4. Guardalo en un archivo llamado mp_token.txt en esta carpeta")
        print("")
        print("   Por ahora no se actualizó el monto.")
    else:
        recaudado = obtener_pagos_del_mes(token)
        if recaudado is not None:
            actualizar_donaciones(recaudado)
        else:
            print("   No se pudo obtener el monto. donaciones.json no fue modificado.")
