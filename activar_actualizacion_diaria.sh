#!/bin/bash
# ═══════════════════════════════════════════════════════
#  PatitasBA — Activar actualización diaria automática
#  Corre el scraper todos los días a las 8:00 AM
#  y sube los cambios a GitHub Pages automáticamente.
#
#  USO: Abrí Terminal, navegá a la carpeta Patitas, y corré:
#       bash activar_actualizacion_diaria.sh
# ═══════════════════════════════════════════════════════

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$SCRIPT_DIR/scraper.log"

echo "🐾 PatitasBA — Configurando actualización diaria..."
echo "📁 Carpeta: $SCRIPT_DIR"

# ── Crear el script que cron va a ejecutar ──
RUNNER="$SCRIPT_DIR/run_scraper.sh"
cat > "$RUNNER" <<EOF
#!/bin/bash
cd "$SCRIPT_DIR"
echo "--- \$(date) ---" >> "$LOG"
bash deploy_a_github.sh >> "$LOG" 2>&1
echo "Completado." >> "$LOG"
EOF
chmod +x "$RUNNER"

# ── Agregar al crontab (todos los días a las 8 AM) ──
CRON_LINE="0 8 * * * $RUNNER"

EXISTING=$(crontab -l 2>/dev/null || echo "")
if echo "$EXISTING" | grep -q "$RUNNER"; then
    echo ""
    echo "✅ La actualización diaria ya estaba activada."
else
    (echo "$EXISTING"; echo "$CRON_LINE") | crontab -
    echo ""
    echo "✅ ¡Listo! Cada día a las 8:00 AM va a:"
    echo "   1. Scrapear Instagram"
    echo "   2. Actualizar pets.json e imágenes"
    echo "   3. Subir todo a GitHub Pages automáticamente"
fi

echo ""
echo "📋 Tu crontab ahora:"
crontab -l
echo ""
echo "💡 Para desactivarlo: corré 'crontab -e' y borrá la línea de PatitasBA"
echo "📄 Los logs se guardan en: $LOG"
