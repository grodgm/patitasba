"""
PatitasBA — Scraper de Instagram
=================================
Extrae posts de adopción de los perfiles configurados,
parsea la información del animal y genera pets.json
para que el sitio web lo muestre automáticamente.

Uso:
    pip install instaloader
    python scraper.py                    # sin login (limitado)
    python scraper.py --login TU_USUARIO # con login (más posts)
    python scraper.py --max-posts 20     # cambiar cantidad de posts
"""

import instaloader
import json
import re
import os
import sys
import time
import argparse
import hashlib
import urllib.request
import ssl
from datetime import datetime
from pathlib import Path

IMAGES_DIR = Path("images")

# ─────────────────────────────────────────
#  CONFIGURACIÓN
# ─────────────────────────────────────────

PERFILES = [
    "zaguatesrefugio",
    "refugioelcampito",
    "adoptaungalgo",
    "mascotasenadopcion",
    "proyecto4patas",
]

MAX_POSTS_POR_PERFIL = 15   # cuántos posts recientes revisar por perfil
PAUSA_ENTRE_PERFILES = 4    # segundos de pausa (evita rate limit)
OUTPUT_FILE = "pets.json"

# ─────────────────────────────────────────
#  PARSER DE CAPTIONS
# ─────────────────────────────────────────

ADOPTADO_KW = [
    "ya tiene hogar", "adoptado", "adoptada", "encontró familia",
    "encontro familia", "fue adoptado", "fue adoptada", "tiene familia",
    "¡adoptado!", "¡adoptada!", "hogar encontrado", "ya fue adoptado",
    "feliz en su hogar", "ya está en su hogar", "su historia terminó bien",
]

def es_post_de_adopcion(caption: str) -> bool:
    """Detecta si el post es sobre un animal en adopción (disponible o ya adoptado)."""
    if not caption:
        return False
    lower = caption.lower()
    keywords = [
        "adopci", "adoptar", "buscamos hogar", "busca hogar",
        "en adopción", "en adopcion", "necesita hogar", "hogar buscado",
        "darlo en adopción", "darlo en adopcion", "está en adopción",
    ]
    return any(kw in lower for kw in keywords)

def esta_adoptado(caption: str) -> bool:
    """Detecta si el animal ya fue adoptado."""
    lower = caption.lower()
    return any(kw in lower for kw in ADOPTADO_KW)


def detectar_tipo(caption: str) -> str:
    """Detecta si es perro o gato con scoring mejorado."""
    lower = caption.lower()

    # Indicadores de perro (peso 1)
    perro_kw = [
        "perro", "perra", "cachorro", "cachorrita", "cachorra",
        "can ", "canino", "canina",
        "labrador", "mestizo", "mestiza", "galgo", "chihuahua", "pitbull",
        "beagle", "rottweiler", "pastor", "husky", "golden", "boxer",
        "dálmata", "dalmata", "poodle", "caniche", "cocker", "dogo",
        "dachshund", "salchicha", "bulldog", "border collie",
    ]
    # Indicadores de gato (peso 1) — incluye jerga argentina
    gato_kw = [
        "gato", "gata", "gatito", "gatita", "gatún", "gatuna",
        "felino", "felina", "minino", "minina",
        "michi", "michito", "michita", "mish",      # jerga argentina
        "angora", "siamés", "siames", "persa",
        "maine coon", "bengalí", "bengali", "ragdoll",
        "doméstico", "domestico",
    ]
    # Emojis con peso 2 (son muy específicos)
    perro_emoji = ["🐕", "🐶", "🐩", "🦮", "🐕‍🦺"]
    gato_emoji  = ["🐈", "🐱", "🐈‍⬛", "😺", "😸"]

    score_perro  = sum(1 for kw in perro_kw    if kw in lower)
    score_gato   = sum(1 for kw in gato_kw     if kw in lower)
    score_perro += sum(2 for e  in perro_emoji  if e  in caption)
    score_gato  += sum(2 for e  in gato_emoji   if e  in caption)

    if score_gato > score_perro:
        return "gato"
    if score_perro > score_gato:
        return "perro"
    # Empate: si hay alguna señal de gato, preferimos gato (menos common-case)
    if score_gato > 0:
        return "gato"
    return "perro"  # default: la mayoría de las cuentas son de perros


def extraer_nombre(caption: str) -> str | None:
    """Intenta extraer el nombre del animal del caption."""
    # Palabras que no son nombres de animales
    STOP = {
        "Busca", "Está", "Este", "Esta", "Tiene", "Gran", "Muy", "Para",
        "Hola", "Por", "Les", "Nos", "Sus", "Con", "Sin", "Que", "Del",
        "Una", "Uno", "Los", "Las", "Pueden", "Tienen", "Queremos",
        "Buscamos", "Necesita", "Necesitamos", "Urgente", "Hoy",
        "Ayer", "Hace", "Desde", "Hasta", "Zona", "Barrio", "Caba",
        "Buenos", "Aires", "Hogar", "Adopcion", "Adopción", "Casa",
        "Familia", "Perro", "Perra", "Gato", "Gata", "Cachorro",
        "Cachorra", "Animal", "Mascota", "Rescate", "Rescatado",
    }
    patterns = [
        # Patrones explícitos con etiqueta "Nombre:"
        r"(?:nombre|se llama|llamamos?|llama|su nombre es)\s*[:\-]?\s*([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,14})\b",
        # Animal con nombre en mayúsculas destacado: "MOCHI busca hogar"
        r"\b([A-ZÁÉÍÓÚÑ]{3,12})\s+(?:busca|necesita|está en|en adopción|busca hogar)",
        # Emojis seguidos de nombre
        r"(?:🐾|🐕|🐕‍🦺|🦮|🐩|🐶|🐈|🐈‍⬛|🐱)\s*([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,14})\b",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, caption, re.IGNORECASE | re.MULTILINE):
            nombre = match.group(1).strip().capitalize()
            if nombre not in STOP and len(nombre) >= 3:
                return nombre
    return None


def extraer_edad(caption: str) -> tuple[str, str]:
    """
    Retorna (edad_texto, categoria).
    categoria: 'cachorro' | 'adulto' | 'senior'
    """
    lower = caption.lower()

    # Patrones explícitos
    patterns = [
        r"(\d+)\s*(?:años?|anos?)",
        r"(\d+)\s*(?:meses?)",
        r"edad\s*[:\-]?\s*(\d+\s*(?:años?|meses?))",
        r"tiene\s+(\d+)\s*(?:años?|meses?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, lower)
        if match:
            texto = match.group(0).strip()
            # Clasificar
            if "mes" in texto:
                num = int(re.search(r"\d+", texto).group())
                cat = "cachorro" if num <= 12 else "adulto"
                return f"{num} meses", cat
            else:
                num = int(re.search(r"\d+", texto).group())
                if num <= 1:
                    cat = "cachorro"
                elif num >= 8:
                    cat = "senior"
                else:
                    cat = "adulto"
                return f"{num} años", cat

    # Palabras clave sin número
    if any(w in lower for w in ["cachorro", "cachorrita", "cachorra", "bebé", "bebe",
                                 "recién nacido", "joven", "gatito", "gatita", "michito", "michita"]):
        return "Cachorro", "cachorro"
    if any(w in lower for w in ["senior", "mayor", "anciano", "anciana", "vejez", "viejito", "viejita"]):
        return "Senior", "senior"

    return "Adulto", "adulto"


def extraer_tamanio(caption: str, tipo: str, ig: str) -> tuple[str, str]:
    """
    Retorna (tamaño_texto, categoria).
    categoria: 'chico' | 'mediano' | 'grande'
    """
    lower = caption.lower()

    grandes = ["grande", "grand", "talla grande", "tamaño grande", "raza grande",
               "labrador", "galgo", "pastor", "husky", "dóberman", "doberman",
               "rottweiler", "golden", "dogo", "fila"]
    chicos  = ["chico", "pequeño", "pequeña", "chiquito", "chiquita", "mini",
               "chihuahua", "yorkshire", "poodle", "toy", "talla chica",
               "tamaño chico", "tamaño pequeño"]
    medianos = ["mediano", "mediana", "talla mediana", "tamaño mediano"]

    # Galgos son siempre grandes
    if "galgo" in ig.lower() or "galgo" in lower:
        return "Grande", "grande"

    # Gatos son generalmente chicos/medianos
    if tipo == "gato":
        if any(w in lower for w in medianos):
            return "Mediano", "mediano"
        return "Chico", "chico"

    for w in grandes:
        if w in lower:
            return "Grande", "grande"
    for w in chicos:
        if w in lower:
            return "Chico", "chico"
    for w in medianos:
        if w in lower:
            return "Mediano", "mediano"

    return "Mediano", "mediano"  # default


def extraer_raza(caption: str, tipo: str) -> str:
    """Intenta detectar la raza, sino 'Mestizo/a'."""
    lower = caption.lower()
    razas_perro = [
        "labrador", "golden retriever", "golden", "galgo", "pitbull",
        "mestizo", "mestiza", "chihuahua", "beagle", "poodle", "caniche",
        "yorkshire", "husky", "pastor alemán", "pastor", "rottweiler",
        "dóberman", "doberman", "cocker", "dachshund", "salchicha",
        "boxer", "bulldog", "border collie", "collie", "dogo",
    ]
    razas_gato = [
        "angora", "siamés", "siames", "persa", "maine coon",
        "bengalí", "bengali", "ragdoll", "doméstico", "domestico",
    ]
    razas = razas_perro if tipo == "perro" else razas_gato

    for raza in razas:
        if raza in lower:
            return raza.capitalize()

    return "Mestizo/a" if tipo == "perro" else "Doméstico/a"


def extraer_genero(caption: str, tipo: str) -> str:
    lower = caption.lower()
    macho_kw  = ["macho", " él ", "el perro", "el gato", "el cachorro",
                 "el gatito", "el michito", "castrado", "el michi"]
    hembra_kw = ["hembra", " ella ", "la perra", "la gata", "la cachorra",
                 "la gatita", "la michita", "esterilizada", "la michi"]
    if any(w in lower for w in macho_kw):
        return "♂"
    if any(w in lower for w in hembra_kw):
        return "♀"
    return "♀" if tipo == "gato" else "♂"  # default


def generar_descripcion_corta(caption: str) -> str:
    """Extrae las primeras 2 oraciones útiles del caption."""
    # Limpiar emojis y hashtags al final
    texto = re.sub(r'#\S+', '', caption)
    texto = re.sub(r'\n\n+', '\n', texto).strip()

    # Tomar las primeras 2 oraciones
    oraciones = re.split(r'[.!?\n]', texto)
    oraciones = [o.strip() for o in oraciones if len(o.strip()) > 15][:2]
    resultado = '. '.join(oraciones)

    if len(resultado) > 180:
        resultado = resultado[:177] + "…"
    return resultado or "Animal en búsqueda de hogar."


def parsear_caption(caption: str, ig: str) -> dict:
    """Parsea el caption y retorna un dict con los datos del animal."""
    tipo        = detectar_tipo(caption)
    nombre      = extraer_nombre(caption)
    edad, ecat  = extraer_edad(caption)
    tam, tcat   = extraer_tamanio(caption, tipo, ig)
    raza        = extraer_raza(caption, tipo)
    genero      = extraer_genero(caption, tipo)
    desc        = generar_descripcion_corta(caption)

    return {
        "tipo":       tipo,
        "nombre":     nombre,
        "raza":       raza,
        "genero":     genero,
        "edad":       edad,
        "edadCat":    ecat,
        "tamanio":    tam,
        "tamanioCat": tcat,
        "desc":       desc,
    }


# ─────────────────────────────────────────
#  NOMBRES DE REFUGIOS (display)
# ─────────────────────────────────────────

ORG_NOMBRES = {
    "zaguatesrefugio":    "Zaguates Refugio",
    "refugioelcampito":   "Refugio El Campito",
    "adoptaungalgo":      "Adopta un Galgo",
    "mascotasenadopcion": "Mascotas en Adopción",
    "proyecto4patas":     "Proyecto 4 Patas",
}

EMOJIS_PERRO = ["🐕", "🐶", "🐕‍🦺", "🦮"]
EMOJIS_GATO  = ["🐈", "🐱", "🐈‍⬛"]

GRADIENTS = [
    "linear-gradient(135deg, #FF9A9E, #FAD0C4)",
    "linear-gradient(135deg, #A18CD1, #FBC2EB)",
    "linear-gradient(135deg, #FFECD2, #FCB69F)",
    "linear-gradient(135deg, #D4FC79, #96E6A1)",
    "linear-gradient(135deg, #84FAB0, #8FD3F4)",
    "linear-gradient(135deg, #F093FB, #F5576C)",
    "linear-gradient(135deg, #667EEA, #764BA2)",
    "linear-gradient(135deg, #FDB99B, #F48FB1)",
    "linear-gradient(135deg, #4E54C8, #8F94FB)",
    "linear-gradient(135deg, #FDDB92, #D1FDFF)",
    "linear-gradient(135deg, #F9D423, #FF4E50)",
    "linear-gradient(135deg, #a8edea, #fed6e3)",
]


def descargar_imagen(url: str, shortcode: str) -> str | None:
    """Descarga la imagen del post y la guarda localmente. Retorna la ruta relativa."""
    try:
        IMAGES_DIR.mkdir(exist_ok=True)
        dest = IMAGES_DIR / f"{shortcode}.jpg"
        if dest.exists():
            return f"images/{shortcode}.jpg"  # ya descargada
        # Ignorar verificación SSL (necesario en Mac con Python sin certificados)
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            dest.write_bytes(resp.read())
        return f"images/{shortcode}.jpg"
    except Exception as e:
        print(f"      ⚠️  No se pudo descargar imagen: {e}")
        return None


def descargar_fotos_post(post, shortcode: str) -> list[str]:
    """Descarga hasta 3 fotos del post (incluye carruseles). Retorna lista de rutas."""
    rutas = []
    try:
        # Intentar carrusel primero
        if hasattr(post, 'typename') and post.typename == "GraphSidecar":
            for i, node in enumerate(post.get_sidecar_nodes()):
                if i >= 3:
                    break
                ruta = descargar_imagen(node.display_url, f"{shortcode}_{i}")
                if ruta:
                    rutas.append(ruta)
    except Exception:
        pass

    # Si no hay carrusel o falló, usar imagen principal
    if not rutas:
        ruta = descargar_imagen(post.url, shortcode)
        if ruta:
            rutas.append(ruta)

    return rutas


def post_a_mascota(post, ig: str, idx: int) -> dict | None:
    """Convierte un post de Instagram en un dict de mascota."""
    caption = post.caption or ""

    if not es_post_de_adopcion(caption):
        return None

    datos      = parsear_caption(caption, ig)
    adoptado   = esta_adoptado(caption)
    disponible = not adoptado

    # Generar nombre fallback
    if not datos["nombre"]:
        datos["nombre"] = f"Sin nombre #{idx}"

    import random
    rng = random.Random(post.shortcode)
    emoji = rng.choice(EMOJIS_PERRO if datos["tipo"] == "perro" else EMOJIS_GATO)
    gradient = GRADIENTS[idx % len(GRADIENTS)]

    # Descargar hasta 3 fotos
    img_paths = descargar_fotos_post(post, post.shortcode)

    return {
        "id":         post.shortcode,
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
        "bg":         gradient,
        "postUrl":    f"https://www.instagram.com/p/{post.shortcode}/",
        "imgUrls":    img_paths,           # hasta 3 fotos
        "disponible": disponible,          # False si ya fue adoptado
        "fecha":      post.date_local.strftime("%Y-%m-%d"),
        "caption":    caption[:500],
    }


# ─────────────────────────────────────────
#  SCRAPER PRINCIPAL
# ─────────────────────────────────────────

def scrape(login_user: str | None = None, max_posts: int = MAX_POSTS_POR_PERFIL):
    L = instaloader.Instaloader(
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        post_metadata_txt_pattern="",
        quiet=True,
        request_timeout=30,
    )

    # Login opcional (permite ver más posts)
    if login_user:
        print(f"🔑 Iniciando sesión como @{login_user}...")
        try:
            L.load_session_from_file(login_user)
            print("   Sesión cargada desde archivo.")
        except FileNotFoundError:
            import getpass
            password = getpass.getpass(f"   Contraseña para @{login_user}: ")
            L.login(login_user, password)
            L.save_session_to_file()
            print("   ✅ Login exitoso. Sesión guardada para próxima vez.")

    todas_las_mascotas = []
    total_posts_revisados = 0
    total_adopciones = 0

    for ig in PERFILES:
        print(f"\n📱 Scrapeando @{ig}...")
        try:
            profile = instaloader.Profile.from_username(L.context, ig)
            print(f"   {profile.followers:,} seguidores · {profile.mediacount} posts")

            mascotas_perfil = 0
            for i, post in enumerate(profile.get_posts()):
                if i >= max_posts:
                    break
                total_posts_revisados += 1

                mascota = post_a_mascota(post, ig, len(todas_las_mascotas))
                if mascota:
                    todas_las_mascotas.append(mascota)
                    mascotas_perfil += 1
                    total_adopciones += 1
                    estado = "🏠 adoptado" if not mascota["disponible"] else f"📸 {len(mascota['imgUrls'])} foto(s)"
                    print(f"   ✅ [{mascotas_perfil}] {mascota['nombre']} — {mascota['tipo']} {mascota['edad']} {mascota['tamanio']} · {estado}")

                # Pausa corta entre requests
                time.sleep(0.5)

            if mascotas_perfil == 0:
                print(f"   ⚠️  No se encontraron posts de adopción en los últimos {max_posts} posts.")

            # Pausa entre perfiles
            if ig != PERFILES[-1]:
                print(f"   ⏳ Esperando {PAUSA_ENTRE_PERFILES}s antes del próximo perfil...")
                time.sleep(PAUSA_ENTRE_PERFILES)

        except instaloader.exceptions.ProfileNotExistsException:
            print(f"   ❌ Perfil @{ig} no existe o es privado.")
        except instaloader.exceptions.LoginRequiredException:
            print(f"   ❌ @{ig} requiere login para ver sus posts. Usá --login TU_USUARIO")
        except Exception as e:
            print(f"   ❌ Error inesperado: {e}")

    # Guardar resultado
    output = {
        "generado": datetime.now().isoformat(),
        "total": len(todas_las_mascotas),
        "posts_revisados": total_posts_revisados,
        "mascotas": todas_las_mascotas,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*50}")
    print(f"✅ Scraping completado!")
    print(f"   Posts revisados:  {total_posts_revisados}")
    print(f"   Mascotas encontradas: {len(todas_las_mascotas)}")
    print(f"   Guardado en: {OUTPUT_FILE}")
    print(f"{'='*50}")
    print(f"\n💡 Ahora abrí patitasba.html en tu browser — ya va a mostrar los datos reales!")


# ─────────────────────────────────────────
#  DEMO (sin conexión a Instagram)
# ─────────────────────────────────────────

def generar_demo():
    """Genera un pets.json de demo para testear el HTML sin Instagram."""
    print("🎭 Generando datos de demo...")
    demo_captions = [
        ("🐶 ¡MOCHI busca hogar! Esta hermosa perra mestiza de 2 años está en adopción. "
         "Nombre: Mochi. Edad: 2 años. Tamaño mediano. Hembra. "
         "Muy cariñosa, se lleva bien con niños y otros perros. 🐾 #adopción #perros #CABA",
         "zaguatesrefugio"),
        ("🐕 RAMÓN necesita hogar urgente. Cachorro labrador de 1 año, macho, tamaño grande. "
         "Joven y energético, busca familia activa con espacio. En adopción. #adopcion",
         "zaguatesrefugio"),
        ("🐱 LUNA en adopción. Gatita de 6 meses, hembra, tamaño chico. "
         "Super sociable y juguetona, viene con vacunas. ¡Damos en adopción! #gatos",
         "refugioelcampito"),
        ("🐕‍🦺 TITO busca hogar. Perro mestizo de 3 años, macho, grande. "
         "Tranquilo y leal, ideal para familia con patio. Está en adopción responsable. #perros",
         "refugioelcampito"),
        ("🐩 FRIDA — galga preciosa en adopción. 2 años, hembra, talla grande. "
         "Muy tranquila, ideal para departamento. ¡Buscamos hogar! #adoptaungalgo",
         "adoptaungalgo"),
        ("🐕 APOLO galgo español, 4 años, macho, grande. Rescatado. Noble y afectuoso. "
         "En adopción responsable. #galgo #adopcion",
         "adoptaungalgo"),
        ("🐈 NUBE necesita hogar. Gatita de 4 meses, hembra, chica. "
         "Muy activa y curiosa. La damos en adopción con vacuna. #gatos #adopción",
         "mascotasenadopcion"),
        ("🐕 COCO en adopción. Chihuahua mix, macho, 5 años, tamaño chico. "
         "Cariñoso, ideal para departamento. Busca hogar responsable. #perros #CABA",
         "mascotasenadopcion"),
        ("🐈‍⬛ BETO busca hogar. Gato negro doméstico de 1 año, macho, mediano. "
         "Castrado y vacunado. Independiente pero cariñoso. En adopción. #gatos",
         "mascotasenadopcion"),
        ("🐶 LILA en adopción. Cachorra mestiza de 8 meses, hembra, mediana. "
         "Juguetona e inteligente, aprende rápido. ¡Buscamos familia! #adopcion #perros",
         "proyecto4patas"),
        ("🐕 RUSO busca hogar. Labrador mix de 2 años, macho, grande. "
         "Ideal para familia con niños, conoce comandos básicos. En adopción. #adopcion",
         "proyecto4patas"),
        ("🐈 MIA necesita hogar tranquilo. Gata angora mix, 7 años, hembra, mediana. "
         "Senior muy cariñosa. Los adultos también merecen una familia. En adopción. #gatos",
         "proyecto4patas"),
    ]

    mascotas = []
    for i, (caption, ig) in enumerate(demo_captions):
        import random
        rng = random.Random(i)
        datos = parsear_caption(caption, ig)
        if datos["tipo"] == "perro":
            emoji = rng.choice(EMOJIS_PERRO)
        else:
            emoji = rng.choice(EMOJIS_GATO)

        mascota = {
            "id":         f"demo_{i}",
            "nombre":     datos["nombre"] or f"Sin nombre #{i}",
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
            "bg":         GRADIENTS[i % len(GRADIENTS)],
            "postUrl":    f"https://www.instagram.com/{ig}/",
            "imgUrl":     None,
            "fecha":      datetime.now().strftime("%Y-%m-%d"),
            "caption":    caption,
        }
        mascotas.append(mascota)
        print(f"  ✅ {mascota['nombre']} — {mascota['tipo']} {mascota['edad']} ({ig})")

    output = {
        "generado": datetime.now().isoformat(),
        "total": len(mascotas),
        "posts_revisados": len(demo_captions),
        "mascotas": mascotas,
        "demo": True,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Demo generado: {OUTPUT_FILE} ({len(mascotas)} mascotas)")


# ─────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="PatitasBA — Scraper de Instagram para adopción de mascotas"
    )
    parser.add_argument("--login",     metavar="USUARIO", help="Usuario de Instagram para login")
    parser.add_argument("--max-posts", type=int, default=MAX_POSTS_POR_PERFIL,
                        help=f"Posts a revisar por perfil (default: {MAX_POSTS_POR_PERFIL})")
    parser.add_argument("--demo",      action="store_true",
                        help="Generar datos de demo sin conectarse a Instagram")
    args = parser.parse_args()

    print("🐾 PatitasBA Scraper")
    print("=" * 50)

    if args.demo:
        generar_demo()
    else:
        print(f"📋 Perfiles a scrapear: {', '.join('@' + p for p in PERFILES)}")
        print(f"📊 Máximo {args.max_posts} posts por perfil")
        if args.login:
            print(f"🔑 Login: @{args.login}")
        else:
            print("👤 Sin login (acceso anónimo — puede ser limitado)")
        print()
        scrape(login_user=args.login, max_posts=args.max_posts)
