#!/bin/bash
# PatitasBA — Configurar actualización automática con launchd
# launchd es mejor que cron en Mac: ejecuta tareas pendientes al despertar

PATITAS_DIR="$HOME/Desktop/Patitas"
PLIST_NAME="com.patitasba.scraper"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"

echo "🐾 PatitasBA — Configurando actualización automática"
echo "=================================================="

# 1. Crear el script que corre el scraper + deploy
SCRIPT_PATH="${PATITAS_DIR}/auto_update.sh"
cat > "$SCRIPT_PATH" << 'SCRIPT'
#!/bin/bash
cd "$(dirname "$0")"
LOG="scraper.log"

echo "$(date): Iniciando actualización automática..." >> "$LOG"

# Correr scraper
python3 scraper.py >> "$LOG" 2>&1

# Si hay cambios, commitear y pushear
if ! git diff --quiet pets.json images/ 2>/dev/null; then
    git add pets.json images/ donaciones.json 2>/dev/null
    git commit -m "🐾 Actualización automática $(date +'%d/%m/%Y %H:%M')" >> "$LOG" 2>&1
    git push >> "$LOG" 2>&1
    echo "$(date): Push realizado." >> "$LOG"
else
    echo "$(date): Sin cambios nuevos." >> "$LOG"
fi

echo "$(date): Listo." >> "$LOG"
echo "---" >> "$LOG"
SCRIPT
chmod +x "$SCRIPT_PATH"
echo "✅ Script creado: $SCRIPT_PATH"

# 2. Desactivar cron anterior si existe
crontab -l 2>/dev/null | grep -v "PatitasBA\|run_scraper\|patitas" | crontab - 2>/dev/null
echo "✅ Cron anterior desactivado"

# 3. Crear el plist de launchd
cat > "$PLIST_PATH" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_NAME}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${SCRIPT_PATH}</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>8</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>${PATITAS_DIR}/scraper_launchd.log</string>
    <key>StandardErrorPath</key>
    <string>${PATITAS_DIR}/scraper_launchd.log</string>
</dict>
</plist>
PLIST
echo "✅ Plist creado: $PLIST_PATH"

# 4. Cargar el servicio
launchctl unload "$PLIST_PATH" 2>/dev/null
launchctl load "$PLIST_PATH"
echo "✅ Servicio activado"

echo ""
echo "=================================================="
echo "🎉 ¡Listo! El scraper va a correr todos los días a las 8 AM."
echo "   Si la Mac estaba dormida, corre apenas la abras."
echo ""
echo "   Para ver logs: cat $PATITAS_DIR/scraper.log"
echo "   Para desactivar: launchctl unload $PLIST_PATH"
echo "=================================================="
