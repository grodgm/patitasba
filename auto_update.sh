#!/bin/bash
# PatitasBA — Script de actualización automática
# Se ejecuta via cron cada hora

cd /Users/gonzalorodriguez/Desktop/Patitas

PYTHON="/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
GIT="/usr/bin/git"
LOG="scraper_launchd.log"

echo "" >> $LOG
echo "========== $(date) ==========" >> $LOG

# 1. Correr scraper
echo "🐾 Corriendo scraper..." >> $LOG
$PYTHON scraper.py >> $LOG 2>&1

# 2. Correr donaciones
export SSL_CERT_FILE=$($PYTHON -c "import certifi; print(certifi.where())")
echo "💰 Actualizando donaciones..." >> $LOG
$PYTHON actualizar_donaciones.py >> $LOG 2>&1

# 3. Push datos (liviano, no falla)
$GIT add pets.json donaciones.json
if ! $GIT diff --staged --quiet; then
    $GIT commit -m "📊 Datos actualizados $(date +'%d/%m/%Y %H:%M')" >> $LOG 2>&1
    $GIT push >> $LOG 2>&1
    echo "✅ Datos pusheados" >> $LOG
fi

# 4. Push imágenes por separado (pesado)
$GIT add images/
if ! $GIT diff --staged --quiet; then
    $GIT commit -m "📸 Imágenes actualizadas $(date +'%d/%m/%Y %H:%M')" >> $LOG 2>&1
    $GIT push >> $LOG 2>&1
    if [ $? -ne 0 ]; then
        echo "⚠️ Push de imágenes falló, reintentando..." >> $LOG
        sleep 5
        $GIT push >> $LOG 2>&1
    fi
    echo "✅ Imágenes pusheadas" >> $LOG
fi

# 5. Limpiar log si pasa de 1000 líneas (para que no crezca infinito)
LINES=$(wc -l < $LOG)
if [ "$LINES" -gt 1000 ]; then
    tail -200 $LOG > ${LOG}.tmp && mv ${LOG}.tmp $LOG
    echo "🧹 Log recortado" >> $LOG
fi

echo "✅ Actualización completa" >> $LOG
