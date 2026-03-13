#!/bin/bash
# ═══════════════════════════════════════════════════════
#  PatitasBA — Deploy automático a GitHub Pages
#  Corre el scraper y sube todo a GitHub Pages
#
#  CONFIGURACIÓN (editá esta línea con tu usuario de GitHub):
#  USO: bash deploy_a_github.sh
# ═══════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$SCRIPT_DIR/scraper.log"
PYTHON="$(which python3)"

echo ""
echo "🐾 PatitasBA — Actualizando y publicando..."
echo "📁 Carpeta: $SCRIPT_DIR"
echo ""

cd "$SCRIPT_DIR"

# ── Verificar que el repo de git está inicializado ──
if [ ! -d ".git" ]; then
    echo "❌ Esta carpeta no es un repositorio git todavía."
    echo "   Seguí los pasos de SETUP_GITHUB.md para configurarlo."
    exit 1
fi

# ── Correr el scraper ──
echo "📡 Scrapeando Instagram..."
echo "--- $(date) ---" >> "$LOG"
$PYTHON scraper.py >> "$LOG" 2>&1

if [ $? -ne 0 ]; then
    echo "⚠️  El scraper terminó con errores. Revisá scraper.log para más detalles."
    echo "   Igualmente subiendo lo que haya..."
fi

# ── Subir a GitHub ──
echo ""
echo "📤 Subiendo a GitHub Pages..."

# Agregar los archivos del sitio (acepta tanto index.html como patitasba.html)
git add pets.json images/ index.html patitasba.html 2>/dev/null || true
git add -A 2>/dev/null || true

# Verificar si hay cambios
if git diff --staged --quiet; then
    echo "✅ No hubo cambios nuevos desde la última actualización."
else
    FECHA=$(date '+%Y-%m-%d %H:%M')
    git commit -m "PatitasBA: actualización automática $FECHA" --quiet
    git push origin main --quiet

    if [ $? -eq 0 ]; then
        echo "✅ ¡Sitio actualizado en GitHub Pages!"
    else
        echo "❌ Error al subir. Revisá tu conexión o credenciales de GitHub."
    fi
fi

echo ""
echo "--- Completado $(date) ---" >> "$LOG"
