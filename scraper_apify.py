"""
PatitasBA — Scraper vía Apify
==============================
Obtiene posts de Instagram usando el actor apify/instagram-scraper
(API administrada: sin cuentas propias, sin bans) y genera pets.json
con el mismo formato que scraper.py.

Reutiliza todo el parser de captions de scraper.py.

Uso:
    export APIFY_TOKEN=apify_api_xxx
    python3 scraper_apify.py
    python3 scraper_apify.py --max-posts 8

Costo: ~$1.50 por 1.000 posts → el plan gratuito de Apify ($5/mes) alcanza.
"""

from __future__ import annotations

import json
import os
import sys
import time
import random
import argparse
import urllib.request
import urllib.error
from datetime import datetime

# Parser y helpers existentes (no requiere instaloader)
from scraper import (
    PERFILES, MAX_POSTS_POR_PERFIL, OUTPUT_FILE,
    ORG_NOMBRES, EMOJIS_PERRO, EMOJIS_GATO, GRADIENTS,
    es_post_de_adopcion, es_campania, es_post_genuino,
    esta_adoptado, parsear_caption, descargar_imagen,
)

APIFY_ACTOR = "apify~instagram-scraper"
APIFY_BASE  = "https://api.apify.com/v2"
POLL_SECONDS = 15
MAX_WAIT_SECONDS = 15 * 60


def _http_json(url: str, payload: dict | None = None) -> dict | list:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def correr_apify(token: str, max_posts: int) -> list[dict]:
    """Lanza el actor de Apify y devuelve los items del dataset."""
    input_actor = {
        "directUrls": [f"https://www.instagram.com/{p}/" for p in PERFILES],
        "resultsType": "posts",
        "resultsLimit": max_posts,
        "addParentData": False,
    }

    print(f"🚀 Lanzando actor {APIFY_ACTOR} ({len(PERFILES)} perfiles × {max_posts} posts)...")
    run = _http_json(f"{APIFY_BASE}/acts/{APIFY_ACTOR}/runs?token={token}", input_actor)
    run_id = run["data"]["id"]
    dataset_id = run["data"]["defaultDatasetId"]

    inicio = time.time()
    status = run["data"]["status"]
    while status in ("READY", "RUNNING"):
        if time.time() - inicio > MAX_WAIT_SECONDS:
            raise TimeoutError(f"El run {run_id} no terminó en {MAX_WAIT_SECONDS//60} min")
        time.sleep(POLL_SECONDS)
        info = _http_json(f"{APIFY_BASE}/actor-runs/{run_id}?token={token}")
        status = info["data"]["status"]
        print(f"   ⏳ {status} ({int(time.time()-inicio)}s)")

    if status != "SUCCEEDED":
        raise RuntimeError(f"Run de Apify terminó con estado {status}")

    items = _http_json(f"{APIFY_BASE}/datasets/{dataset_id}/items?token={token}&format=json&clean=true")
    print(f"   ✅ {len(items)} posts recibidos de Apify")
    return items


def urls_de_imagenes(item: dict) -> list[str]:
    """Hasta 3 URLs de imagen del post (incluye carruseles)."""
    urls = []
    for child in (item.get("childPosts") or [])[:3]:
        u = child.get("displayUrl")
        if u:
            urls.append(u)
    if not urls:
        u = item.get("displayUrl") or (item.get("images") or [None])[0]
        if u:
            urls.append(u)
    return urls[:3]


def item_a_mascota(item: dict, idx: int) -> dict | None:
    """Convierte un item de Apify en un dict de mascota (mismo formato que scraper.py)."""
    caption = item.get("caption") or ""
    ig = (item.get("ownerUsername") or "").lower()
    shortcode = item.get("shortCode") or item.get("id") or ""

    if not shortcode:
        return None

    if not es_post_de_adopcion(caption):
        return None
    if es_campania(caption):
        print(f"      ⏭️  Saltando campaña/evento")
        return None
    if not es_post_genuino(caption):
        print(f"      ⏭️  Saltando post genérico/reflexivo")
        return None

    datos = parsear_caption(caption, ig)
    adoptado = esta_adoptado(caption)
    if not datos["nombre"]:
        datos["nombre"] = "Sin nombre"

    rng = random.Random(shortcode)
    emoji = rng.choice(EMOJIS_PERRO if datos["tipo"] == "perro" else EMOJIS_GATO)

    # Descargar hasta 3 fotos
    img_paths = []
    urls = urls_de_imagenes(item)
    for i, u in enumerate(urls):
        suffix = f"{shortcode}_{i}" if len(urls) > 1 else shortcode
        ruta = descargar_imagen(u, suffix)
        if ruta:
            img_paths.append(ruta)

    fecha = (item.get("timestamp") or "")[:10] or datetime.now().strftime("%Y-%m-%d")

    return {
        "id":         shortcode,
        "nombre":     datos["nombre"],
        "tipo":       datos["tipo"],
        "raza":       datos["raza"],
        "genero":     datos["genero"],
        "edad":       datos["edad"],
        "edadCat":    datos["edadCat"],
        "tamanio":    datos["tamanio"],
        "tamanioCat": datos["tamanioCat"],
        "desc":       datos["desc"],
        "org":        ORG_NOMBRES.get(ig, ig),
        "ig":         ig,
        "emoji":      emoji,
        "bg":         GRADIENTS[idx % len(GRADIENTS)],
        "postUrl":    f"https://www.instagram.com/p/{shortcode}/",
        "imgUrls":    img_paths,
        "disponible": not adoptado,
        "fecha":      fecha,
        "caption":    caption[:500],
    }


def main():
    parser = argparse.ArgumentParser(description="PatitasBA — Scraper vía Apify")
    parser.add_argument("--max-posts", type=int, default=MAX_POSTS_POR_PERFIL)
    parser.add_argument("--input-json", help="(test) usar un JSON local en vez de llamar a Apify")
    args = parser.parse_args()

    print("🐾 PatitasBA Scraper (Apify)")
    print("=" * 50)

    if args.input_json:
        items = json.load(open(args.input_json, encoding="utf-8"))
        print(f"🧪 Modo test: {len(items)} items desde {args.input_json}")
    else:
        token = os.environ.get("APIFY_TOKEN", "").strip()
        if not token:
            print("❌ Falta APIFY_TOKEN. Crealo en https://console.apify.com/account/integrations")
            sys.exit(1)
        items = correr_apify(token, args.max_posts)

    mascotas, vistos = [], set()
    posts_revisados = 0
    for item in items:
        # Items de error del actor (perfil privado/inexistente) no tienen shortCode
        if item.get("error"):
            print(f"   ⚠️  {item.get('url', '?')}: {item['error']}")
            continue
        posts_revisados += 1
        m = item_a_mascota(item, len(mascotas))
        if m and m["id"] not in vistos:
            vistos.add(m["id"])
            mascotas.append(m)
            estado = "🏠 adoptado" if not m["disponible"] else f"📸 {len(m['imgUrls'])} foto(s)"
            print(f"   ✅ {m['nombre']} (@{m['ig']}) — {m['tipo']} {m['edad']} · {estado}")

    if not mascotas:
        print("\n⚠️  0 mascotas encontradas — se conserva el pets.json anterior.")
        sys.exit(1)  # exit 1 para que GitHub Actions avise del fallo

    # Más nuevas primero
    mascotas.sort(key=lambda m: m["fecha"], reverse=True)

    output = {
        "generado": datetime.now().isoformat(),
        "total": len(mascotas),
        "posts_revisados": posts_revisados,
        "mascotas": mascotas,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*50}")
    print(f"✅ Listo: {len(mascotas)} mascotas de {posts_revisados} posts → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
