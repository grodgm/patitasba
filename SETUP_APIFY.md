# Setup Apify — scraping sin bans

El scraping ahora usa la API de Apify (actor `apify/instagram-scraper`).
No hay cuenta propia de IG → no hay nada que bannear. Apify maneja proxies y cuentas.

**Costo:** ~$1.50 por 1.000 posts. Con 8 perfiles × 8 posts/día ≈ 1.900 posts/mes ≈ **$3/mes → entra en los $5 gratis** del plan free.

## Pasos (una sola vez)

1. Crear cuenta en https://console.apify.com/sign-up (no usar tu email personal si preferís, alcanza el plan Free).
2. Copiar el token: **Settings → API & Integrations → Personal API token**.
3. En GitHub: `grodgm/patitasba` → **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `APIFY_TOKEN`
   - Value: el token
4. Borrar los secrets viejos `INSTAGRAM_USERNAME` e `INSTAGRAM_SESSION_B64` (ya no se usan).
5. Probar: **Actions → Actualizar mascotas → Run workflow**.

## Probar localmente (opcional)

```bash
export APIFY_TOKEN=apify_api_xxx
python3 scraper_apify.py
```

## Apagar el cron viejo de la Mac

En la Mac vieja (donde corría launchd):

```bash
launchctl unload ~/Library/LaunchAgents/com.patitasba.scraper.plist 2>/dev/null
rm ~/Library/LaunchAgents/com.patitasba.scraper.plist
```

## Si falla

- El workflow corre 9:30 AM (ARG) diario. Si falla, GitHub te manda email.
- `scraper_apify.py` sale con error si encuentra 0 mascotas (conserva el pets.json anterior).
- Si Apify cambia el formato del actor, revisar `urls_de_imagenes()` y `item_a_mascota()` en `scraper_apify.py`.
