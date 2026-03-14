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
