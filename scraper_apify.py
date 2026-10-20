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
import re
from pathlib import Path
from datetime import datetime

try:
    from PIL import Image  # opcional: si no está, no se optimizan las fotos
except ImportError:
    Image = None

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


IMG_MAX_ANCHO = 900
IMG_CALIDAD = 78


def optimizar_imagenes(mascotas: list[dict]) -> None:
    """Pasa las fotos usadas a WebP (máx. 900 px de ancho) y borra de images/ las que ya no usa nadie."""
    if Image is None:
        print("ℹ️  Pillow no está instalado: se saltea la optimización de fotos")
        return
    convertidas = 0
    for m in mascotas:
        nuevas = []
        for ruta in m.get("imgUrls", []):
            p = Path(ruta)
            if p.suffix.lower() in (".jpg", ".jpeg", ".png") and p.exists():
                destino = p.with_suffix(".webp")
                try:
                    with Image.open(p) as im:
                        im = im.convert("RGB")
                        if im.width > IMG_MAX_ANCHO:
                            im = im.resize((IMG_MAX_ANCHO, round(im.height * IMG_MAX_ANCHO / im.width)), Image.LANCZOS)
                        im.save(destino, "WEBP", quality=IMG_CALIDAD, method=6)
                    p.unlink()
                    ruta = destino.as_posix()
                    convertidas += 1
                except Exception as e:
                    print(f"   ⚠️  No se pudo optimizar {p}: {e}")
            elif p.suffix.lower() in (".jpg", ".jpeg", ".png") and p.with_suffix(".webp").exists():
                ruta = p.with_suffix(".webp").as_posix()
            nuevas.append(ruta)
        m["imgUrls"] = nuevas

    en_uso = {Path(r).name for m in mascotas for r in m.get("imgUrls", [])}
    borradas = 0
    carpeta = Path("images")
    if carpeta.is_dir():
        for f in carpeta.iterdir():
            if f.is_file() and f.name not in en_uso:
                f.unlink()
                borradas += 1
    print(f"🖼️  Fotos: {convertidas} convertidas a WebP, {borradas} sin uso borradas, {len(en_uso)} en uso")


def actualizar_sitemap() -> None:
    """Pone la fecha de hoy como lastmod de la home en sitemap.xml."""
    try:
        s = Path("sitemap.xml").read_text(encoding="utf-8")
        hoy = datetime.now().strftime("%Y-%m-%d")
        s = re.sub(r"(<loc>https://patitasba\.com\.ar/</loc>\s*<lastmod>)[^<]*(</lastmod>)", rf"\g<1>{hoy}\g<2>", s, count=1)
        Path("sitemap.xml").write_text(s, encoding="utf-8")
    except OSError:
        pass


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
        if not any(it.get("shortCode") and not it.get("error") for it in items):
            print("\n🔁 Apify no devolvió ningún post válido (probable bloqueo de Instagram). Reintento en 2 min...")
            time.sleep(120)
            items = correr_apify(token, args.max_posts)

    mascotas, vistos = [], set()
    posts_revisados = 0
    perfiles_ok = set()
    for item in items:
        # Items de error del actor (perfil privado/inexistente) no tienen shortCode
        if item.get("error"):
            print(f"   ⚠️  {item.get('url', '?')}: {item['error']}")
            continue
        posts_revisados += 1
        if item.get("ownerUsername"):
            perfiles_ok.add(item["ownerUsername"].lower())
        m = item_a_mascota(item, len(mascotas))
        if m and m["id"] not in vistos:
            vistos.add(m["id"])
            mascotas.append(m)
            estado = "🏠 adoptado" if not m["disponible"] else f"📸 {len(m['imgUrls'])} foto(s)"
            print(f"   ✅ {m['nombre']} (@{m['ig']}) — {m['tipo']} {m['edad']} · {estado}")

    # Si Instagram bloqueó algunos perfiles hoy, conservamos sus mascotas del pets.json anterior
    # (así un bloqueo parcial no vacía el sitio).
    try:
        anteriores = json.load(open(OUTPUT_FILE, encoding="utf-8")).get("mascotas", [])
    except (OSError, ValueError):
        anteriores = []
    conservadas = 0
    for m in anteriores:
        if m.get("ig") in PERFILES and m.get("ig") not in perfiles_ok and m.get("id") not in vistos:
            vistos.add(m["id"])
            mascotas.append(m)
            conservadas += 1
    if conservadas:
        sin_respuesta = sorted({m["ig"] for m in anteriores if m.get("ig") in PERFILES and m.get("ig") not in perfiles_ok})
        print(f"\n♻️  {conservadas} mascotas conservadas de perfiles sin respuesta hoy: {', '.join(sin_respuesta)}")

    if not perfiles_ok:
        print("\n⚠️  Ningún perfil respondió — se conserva el pets.json anterior.")
        sys.exit(1)  # exit 1 para que GitHub Actions avise del fallo

    if not mascotas:
        print("\n⚠️  0 mascotas encontradas — se conserva el pets.json anterior.")
        sys.exit(1)  # exit 1 para que GitHub Actions avise del fallo

    optimizar_imagenes(mascotas)
    actualizar_sitemap()

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
