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

from __future__ import annotations

try:
    import instaloader  # opcional: solo necesario para scrape() con instaloader
except ImportError:
    instaloader = None  # scraper_apify.py importa los parsers sin necesitarlo
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
    "rescataditosenadopcionn",
    "hogardeproteccionlourdes",
    "gatitos_parque_chacabuco",
]

MAX_POSTS_POR_PERFIL = 6    # cuántos posts recientes revisar (los refugios publican 1-2/día)
PAUSA_ENTRE_PERFILES = 20   # segundos de pausa entre perfiles (simula humano)
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
        "buscan familia", "busca familia", "buscando familia",
        "buscando hogar", "necesitan hogar", "necesitan familia",
    ]
    if any(kw in lower for kw in keywords):
        return True
    # Algunos posts de refugios son implícitamente de adopción
    adoptado_check = any(kw in lower for kw in ADOPTADO_KW)
    return adoptado_check

def es_campania(caption: str) -> bool:
    """Detecta si el post es una campaña general, no de un animal específico."""
    lower = caption.lower()
    campania_kw = [
        "jornada de adopción", "jornada de adopcion", "evento de adopción",
        "evento de adopcion", "feria de adopción", "feria de adopcion",
        "campaña de", "campaña", "jornada", "evento", "feria",
        "vení a conocer", "veni a conocer", "te esperamos",
        "este sábado", "este sabado", "este domingo",
        "los esperamos en", "nos vemos en",
        "charla", "voluntarios", "voluntariado",
        "sorteo", "rifa", "bono contribución",
    ]
    # Si tiene muchas de estas keywords, probablemente es campaña
    hits = sum(1 for kw in campania_kw if kw in lower)
    if hits >= 2:
        return True
    # Si NO menciona ningún animal individual (sin nombre propio, sin "busca hogar")
    animal_individual_kw = [
        "se llama", "nombre:", "busca hogar", "necesita hogar",
        "busca familia", "en adopción responsable",
    ]
    tiene_animal = any(kw in lower for kw in animal_individual_kw)
    # Si tiene keywords de campaña pero no de animal individual
    if hits >= 1 and not tiene_animal:
        return True
    return False

def esta_adoptado(caption: str) -> bool:
    """
    Detecta si el animal ya fue adoptado.

    Lógica:
    - Si la keyword de adoptado aparece en los PRIMEROS 150 caracteres
      (el refugio editó el post y agregó "ADOPTADO" arriba) → adoptado definitivo.
    - Si aparece más adelante Y también hay keywords de búsqueda activa
      → probablemente solo algunos fueron adoptados → NO marcar como adoptado.
    """
    lower = caption.lower()

    # ¿Hay alguna mención de adoptado en algún lado?
    tiene_adoptado = any(kw in lower for kw in ADOPTADO_KW)
    if not tiene_adoptado:
        return False

    # Si la keyword está al PRINCIPIO del caption (patrón "ADOPTADO\n\n[post original]")
    # → definitivamente adoptado, ignorar el resto del texto
    inicio = lower[:150]
    if any(kw in inicio for kw in ADOPTADO_KW):
        return True

    # Está más adelante → verificar si quedan animales disponibles en el mismo post
    sigue_disponible_kw = [
        "busca hogar", "buscamos hogar", "en adopción", "en adopcion",
        "necesita hogar", "buscando hogar", "siguen buscando", "sigue buscando",
        "todavía busca", "todavia busca", "aún busca", "aun busca",
        "quedan", "todavía disponible", "todavia disponible",
        "sigue en adopción", "sigue en adopcion",
        "los demás", "los demas", "sus hermanos", "sus hermanitos",
        "el resto", "los otros",
    ]
    sigue_disponible = any(kw in lower for kw in sigue_disponible_kw)
    return not sigue_disponible


def detectar_tipo(caption: str, ig: str = "") -> str:
    """Detecta si es perro o gato con scoring mejorado."""

    # Perfiles 100% de gatos → siempre gato
    PERFILES_GATOS = {"gatitos_parque_chacabuco"}
    if ig in PERFILES_GATOS:
        return "gato"

    # Perfiles 100% de perros → siempre perro
    PERFILES_PERROS = {"adoptaungalgo"}
    if ig in PERFILES_PERROS:
        return "perro"

    # Perfiles mixtos con tendencia a gatos → bonus gato
    PERFILES_MIXTOS_GATOS = {"hogardeproteccionlourdes", "rescataditosenadopcionn"}

    lower = caption.lower()

    # Indicadores de perro (peso 1)
    perro_kw = [
        "perro", "perra", "perrito", "perrita",
        "cachorro", "cachorrita", "cachorra",
        "can ", "canino", "canina",
        "labrador", "mestizo", "mestiza", "galgo", "chihuahua", "pitbull",
        "beagle", "rottweiler", "pastor", "husky", "golden", "boxer",
        "dálmata", "dalmata", "poodle", "caniche", "cocker", "dogo",
        "dachshund", "salchicha", "bulldog", "border collie",
        "ladra", "paseo", "correa", "collar",
    ]
    # Indicadores de gato (peso 1) — incluye jerga argentina
    gato_kw = [
        "gato", "gata", "gatito", "gatita", "gatitos", "gatitas",
        "gatún", "gatuna", "gatunas", "gatunos",
        "felino", "felina", "felinos", "felinas",
        "minino", "minina", "mininos", "mininas",
        "michi", "michis", "michito", "michita", "michitos", "michitas", "mish",
        "micho", "micha",
        "angora", "siamés", "siames", "persa",
        "maine coon", "bengalí", "bengali", "ragdoll",
        "ronronea", "ronroneo", "maulla", "maúlla", "arenero",
        "bigotes", "patitas suaves",
    ]
    # Emojis con peso 3 (son muy específicos)
    perro_emoji = ["🐕", "🐶", "🐩", "🦮", "🐕‍🦺"]
    gato_emoji  = ["🐈", "🐱", "🐈‍⬛", "😺", "😸", "🙀", "😻", "😿", "😾"]

    # Contar ocurrencias (no solo presencia) para palabras clave frecuentes
    score_perro  = sum(lower.count(kw) for kw in perro_kw)
    score_gato   = sum(lower.count(kw) for kw in gato_kw)
    score_perro += sum(3 for e in perro_emoji if e in caption)
    score_gato  += sum(3 for e in gato_emoji  if e in caption)

    # Bonus para perfiles mixtos con tendencia a gatos
    if ig in PERFILES_MIXTOS_GATOS:
        score_gato += 1  # desempata hacia gato cuando no hay señales claras

    if score_gato > score_perro:
        return "gato"
    if score_perro > score_gato:
        return "perro"
    # Empate: si hay alguna señal de gato, preferimos gato (menos common-case)
    if score_gato > 0:
        return "gato"
    # Empate sin señales: en perfiles mixtos de gatos, default gato
    if ig in PERFILES_MIXTOS_GATOS:
        return "gato"
    return "perro"  # default: la mayoría de las cuentas son de perros


# ─── Stop-words para extracción de nombres ─────────────────────────────
# Palabras que NO son nombres de animales (se descartan si matchean algún patrón).
_NOMBRE_STOP = {
    # Artículos / conectores
    "el", "la", "los", "las", "un", "una", "unos", "unas",
    "de", "del", "con", "sin", "por", "para", "que",
    "este", "esta", "estos", "estas", "ese", "esa", "esos", "esas",
    "y", "o", "e", "u", "pero", "aunque", "si", "ya", "no", "mas", "más",
    # Verbos conjugados (los que el scraper viejo tomaba como nombre)
    "busco", "buscas", "busca", "buscan", "buscamos", "buscando", "esperando", "necesitando",
    "hay", "fue", "fueron", "son", "era", "eran", "está", "estan", "están",
    "tiene", "tienen", "tenía", "tenían", "quiere", "quieren",
    "sigue", "siguen", "llegó", "llego", "llegaron", "lleva", "llevan", "llegan",
    "saben", "sabe", "puede", "pueden", "hace", "hacer", "ser", "estar",
    "vamos", "voy", "va", "van", "vino", "vienen", "viene",
    "seguimos", "somos", "tenemos", "estamos", "queremos", "querés", "queres",
    # Pronombres — NO son nombres de animales
    "él", "ella", "ellos", "ellas", "nosotros", "nosotras",
    "ustedes", "mío", "mía", "tuyo", "tuya", "suyo", "suya",
    "nuestro", "nuestra", "nuestros", "nuestras",
    # Palabras descriptivas frecuentes
    "camada", "camadita", "hermanitos", "hermanitas", "hermanos", "hermanas",
    "muchas", "muchos", "mucha", "mucho", "nadie", "todos", "todas",
    "algunos", "algunas", "alguno", "alguna", "cual", "cuál", "cuanto", "cuánto",
    "como", "cómo", "donde", "dónde", "cuando", "cuándo", "qué", "porque",
    "hola", "les", "nos", "sus", "su", "cada", "solo", "sola",
    # Adjetivos/adverbios que suelen empezar posts
    "importante", "importantes", "urgente", "urgentes",
    "necesitamos", "necesitan", "necesita", "necesito",
    "hoy", "mañana", "recientemente",
    "facha", "dulce", "dulcita",
    "estas", "estos", "esos", "esas",
    # Generales de refugio
    "hogar", "adopcion", "adopción", "casa", "familia", "refugio",
    "fundación", "fundacion", "proyecto", "campaña",
    "disponible", "disponibles", "transitando", "tránsito", "transito",
    "jornada", "evento", "feria", "charla",
    "info", "información", "consultas", "contacto", "datos", "informes",
    # Especies
    "perro", "perra", "perrito", "perrita", "gato", "gata", "gatito", "gatita",
    "cachorro", "cachorra", "cachorrito", "cachorrita",
    "animal", "mascota", "galgo", "galga", "galguito", "galguita",
    "mestizo", "mestiza",
    # Atributos
    "macho", "hembra", "castrado", "castrada", "esterilizada",
    "vacunado", "vacunada", "desparasitado", "desparasitada",
    "edad", "tamaño", "peso", "color", "raza", "mes", "meses", "años",
    "año", "dias", "día", "semanas", "semana",
    "hermoso", "hermosa", "lindo", "linda", "bello", "bella",
    "nuevo", "nueva", "bueno", "buena",
    "super", "súper", "mega", "bien", "mal", "mejor", "peor",
    "chico", "chica", "grande", "mediano", "mediana", "pequeño", "pequeña",
    "urgente", "hoy", "ayer", "ahora", "antes", "después", "despues",
    "siempre", "nunca", "recién", "recien",
    "zona", "barrio", "caba", "buenos", "aires",
    # Contexto de adopción
    "adopta", "adoptado", "adoptada", "adoptados", "adoptadas",
    "rescate", "rescatado", "rescatada", "rescatados", "rescatadas",
    # Adjetivos que aparecen como si fueran nombres
    "lourdesiano", "lourdesiana", "lourdesianos", "lourdesianas", "camperitos",
    # Números como palabra
    "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez",
    # Redes / CTAs
    "seguimos", "miralo", "mirala", "ayuda", "ayudanos", "compartí", "comparti",
    "gracias", "graciass", "thanks", "conoce", "conocé", "mirá", "mira", "aquí", "acá",
    "dale", "buenas", "tardes", "noches",
    # Términos que solo vi generar nombres basura
    "historia", "historias", "labor", "admiración", "admiracion", "respeto",
    "bomboncitos", "bombón", "bombon", "estrellita",
    "especias", "especiales", "especial",
    "bebé", "bebe", "bebés", "bebes", "bebita", "bebito",
    "panteritas", "atigrada", "atigrado",
    "resuelto", "resuelta",
    "gran", "muy",
}


def _colapsar_letras_espaciadas(texto: str) -> str:
    """'E S T R E L L A' → 'ESTRELLA' (cuando hay 4+ letras mayúsculas separadas por espacios)."""
    def repl(m):
        return m.group(0).replace(' ', '')
    return re.sub(r'\b(?:[A-ZÁÉÍÓÚÑ]\s){3,}[A-ZÁÉÍÓÚÑ]\b', repl, texto)


def _nombre_valido(nombre: str) -> bool:
    """Filtra stop-words, acrónimos raros y nombres fuera de rango."""
    if not nombre:
        return False
    if len(nombre) < 3 or len(nombre) > 15:
        return False
    if nombre.lower() in _NOMBRE_STOP:
        return False
    # Al menos una vocal (filtra acrónimos raros tipo "PSP")
    if not re.search(r'[aeiouáéíóúAEIOUÁÉÍÓÚ]', nombre):
        return False
    return True


def extraer_nombre(caption: str) -> str | None:
    """Extrae el nombre del animal del caption. Retorna None si no encuentra uno válido."""
    if not caption:
        return None

    # Pre-procesar: colapsar "E S T R E L L A" → "ESTRELLA"
    texto = _colapsar_letras_espaciadas(caption)

    def _match(pattern: str, scope: str = texto, flags=re.MULTILINE) -> str | None:
        for m in re.finditer(pattern, scope, flags):
            n = m.group(1).strip().capitalize()
            if _nombre_valido(n):
                return n
        return None

    # Ronda 1 — patrones de ALTA confianza (etiquetas explícitas "Me llamo X", etc.)
    high_conf = [
        r"(?i)\bme llamo\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,14})\b",
        r"(?i)\bmi nombre es\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,14})\b",
        r"(?i)\bnombre\s*[:\-]\s*([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,14})\b",
        r"(?i)\b(?:se llama|lo llamamos|la llamamos|llamamos)\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,14})\b",
        r"(?i)\b(?:te presentamos a|les presentamos a|conocé a|conoce a|conozcan a)\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,14})\b",
        r"(?i)\b(?:él es|ella es|ella es la dulce|es la dulce|es el dulce)\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,14})\b",
        r"(?i)\b(?:adoptá a|adoptar a|adopta a)\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,14})\b",
        # Hashtag-nombre: #PIPE, #EROS, #XUL, #UMA (lo que hace zaguates, gatitos_parque_chacabuco)
        r"#([A-ZÁÉÍÓÚÑ]{3,14})\b",
    ]
    for p in high_conf:
        n = _match(p, texto, re.MULTILINE)
        if n:
            return n

    primera_linea = texto.split('\n')[0]

    # Ronda 2 — NOMBRE EN MAYÚSCULAS al principio de la primera línea
    # Captura "JULY ADOPTADA", "PIPO ADOPTADO", "BENJA🐕💖", "PONCHO EN ADOPCIÓN"
    m = re.match(r'^[^A-Za-zÁÉÍÓÚÑáéíóúñ]*([A-ZÁÉÍÓÚÑ]{3,14})\b', primera_linea)
    if m:
        n = m.group(1).capitalize()
        if _nombre_valido(n):
            return n

    # Ronda 3 — primera palabra Capitalizada al inicio de la primera línea
    # Captura "Mara Adoptada!", "Dulcinea 💚🐾", "Pandora tiene...", "Lilo en adopción"
    primera_limpia = re.sub(r'^[^\w]+', '', primera_linea, flags=re.UNICODE)
    m = re.match(r'^([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,14})\b', primera_limpia)
    if m:
        n = m.group(1).capitalize()
        if _nombre_valido(n):
            return n

    # Ronda 4 — NOMBRE seguido de contexto de adopción/verbo (cualquier parte del caption)
    context = [
        # mayúsculas + cualquier cosa no-letra + "en adopción" (ej "RAYO⚡️ en adopcion")
        r'\b([A-ZÁÉÍÓÚÑ]{3,14})[^A-Za-zÁÉÍÓÚÑáéíóúñ]*?\s+(?:en adopción|en adopcion|busca|necesita|adoptado|adoptada)',
        # Capitalizada + verbo (ej "Xion tiene once meses", "Pandy y Ámbar fueron...")
        # Incluye "está en adopción" sin guión bajo
        r'\b([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,14})\s+(?:tiene|es un|es una|busca|necesita|está en|esta en|llegó|llego|fueron|fue|se presenta|ya está|y )',
        # "si NOMBRE está en adopción" o "si NOMBRE busca hogar" (Simona)
        r'\bsi\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,14})\s+(?:está|esta|busca|tiene)',
        # "Hoy NOMBRE se presenta" / "Hoy NOMBRE..."
        r'\bHoy\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,14})\b',
        # Lista de cachorros: "- Pimienta, hembra" / "Pimienta, hembra 🐶"
        r'(?:^|\n)\s*[-•·*]?\s*([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,14})\s*,\s*(?:hembra|macho)',
        # Emoji de corazón/flor + nombre capitalizado
        r'(?:🐾|🐕|🐕‍🦺|🦮|🐩|🐶|🐈|🐈‍⬛|🐱|❤️|🤎|🩷|🩵|💚|💕|✨|⭐️|🌟|🌺|🌸|🌹|🖤|💖|💘|💫|🔥|🔴|🟢|🟡)\s*([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,14})\b',
    ]
    for p in context:
        n = _match(p, texto, re.MULTILINE)
        if n:
            return n

    return None


def es_post_genuino(caption: str) -> bool:
    """Descarta posts que son reflexiones genéricas o shoutouts a otros refugios."""
    if not caption:
        return False
    lower = caption.lower()
    primera_linea = lower.split('\n')[0].strip()

    # Posts reflexivos/genéricos — empiezan con estas frases
    generic_starters = [
        "hay historias", "cada vez ", "todos los años",
        "cuando pensamos", "queremos contarles",
        "gracias a ", "feliz día", "felicidades",
        "algunos perros", "algunos gatos", "algunas perras", "algunas gatas",
        "cuánto más", "cuanto más", "cuál es",
        "la facha", "todos adoptados", "lourdesian",
    ]
    if any(primera_linea.startswith(s) for s in generic_starters):
        return False

    # Shoutout a otro perfil: "@algo" + palabras reflexivas → homenaje genérico
    shoutout_indicators = ["labor", "admiración", "admiracion", "respeto",
                           "retrato", "homenaje", "gracias por ",
                           "apoyando a", "colaborando con"]
    if '@' in caption and any(ind in lower for ind in shoutout_indicators):
        return False

    return True


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
                    return f"{num} años (Adulto+)", cat
                else:
                    cat = "adulto"
                return f"{num} años", cat

    # Palabras clave sin número
    if any(w in lower for w in ["cachorro", "cachorrita", "cachorra", "bebé", "bebe",
                                 "recién nacido", "joven", "gatito", "gatita", "michito", "michita"]):
        return "Cachorro", "cachorro"
    if any(w in lower for w in ["senior", "mayor", "anciano", "anciana", "vejez", "viejito", "viejita"]):
        return "Adulto+", "senior"

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
    tipo        = detectar_tipo(caption, ig)
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
    "zaguatesrefugio":          "Zaguates Refugio",
    "refugioelcampito":         "Refugio El Campito",
    "adoptaungalgo":            "Adopta un Galgo",
    "mascotasenadopcion":       "Mascotas en Adopción",
    "proyecto4patas":           "Proyecto 4 Patas",
    "rescataditosenadopcionn":  "Rescataditos en Adopción",
    "hogardeproteccionlourdes": "Hogar de Protección Lourdes",
    "gatitos_parque_chacabuco": "Gatitos Parque Chacabuco",
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

    if es_campania(caption):
        print(f"      ⏭️  Saltando campaña/evento (no es animal individual)")
        return None

    if not es_post_genuino(caption):
        print(f"      ⏭️  Saltando post genérico/reflexivo/shoutout")
        return None

    datos      = parsear_caption(caption, ig)
    adoptado   = esta_adoptado(caption)
    disponible = not adoptado

    # Fallback cuando no encontramos un nombre válido
    if not datos["nombre"]:
        datos["nombre"] = "Sin nombre"

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
    import random

    L = instaloader.Instaloader(
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        post_metadata_txt_pattern="",
        quiet=True,
        request_timeout=15,
        max_connection_attempts=1,  # NO reintentar (evita acumular 401s)
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
    errores_consecutivos = 0  # si falla 2 seguidos, parar

    # Mezclar orden de perfiles (evita patrón predecible)
    perfiles_shuffled = PERFILES.copy()
    random.shuffle(perfiles_shuffled)

    for ig in perfiles_shuffled:
        # Si ya fallaron 2 perfiles seguidos, Instagram nos bloqueó → parar
        if errores_consecutivos >= 2:
            print(f"\n   🛑 2 perfiles seguidos bloqueados — parando para no empeorar.")
            break

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

                # Pausa humana entre posts (1-3 segundos random)
                time.sleep(random.uniform(1.0, 3.0))

            if mascotas_perfil == 0:
                print(f"   ⚠️  No se encontraron posts de adopción en los últimos {max_posts} posts.")

            errores_consecutivos = 0  # reset si este perfil anduvo bien

            # Pausa larga entre perfiles (15-30 segundos random)
            if ig != perfiles_shuffled[-1]:
                pausa = random.uniform(PAUSA_ENTRE_PERFILES * 0.75, PAUSA_ENTRE_PERFILES * 1.5)
                print(f"   ⏳ Esperando {pausa:.0f}s antes del próximo perfil...")
                time.sleep(pausa)

        except instaloader.exceptions.ProfileNotExistsException:
            print(f"   ❌ Perfil @{ig} no existe o es privado.")
        except instaloader.exceptions.LoginRequiredException:
            print(f"   ❌ @{ig} requiere login para ver sus posts. Usá --login TU_USUARIO")
            errores_consecutivos += 1
        except Exception as e:
            print(f"   ❌ Error inesperado: {e}")
            errores_consecutivos += 1

    # No sobreescribir si no encontró nada (Instagram bloqueó)
    if len(todas_las_mascotas) == 0:
        print(f"\n{'='*50}")
        print(f"⚠️  No se encontraron mascotas — Instagram probablemente bloqueó.")
        print(f"   Se conserva el pets.json anterior.")
        print(f"{'='*50}")
        return

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
            "nombre":     datos["nombre"] or "Sin nombre",
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
