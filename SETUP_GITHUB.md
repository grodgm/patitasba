# 🐾 PatitasBA — Cómo publicar en GitHub Pages

GitHub Pages te permite publicar el sitio **gratis**, sin servidor, y que se actualice
solo cada vez que corra el scraper en tu Mac. El sitio va a estar disponible en:

```
https://TU-USUARIO.github.io/patitasba/
```

---

## Paso 1: Crear cuenta en GitHub (si no tenés)

Andá a **[github.com](https://github.com)** y creá una cuenta gratuita.

---

## Paso 2: Instalar Git en tu Mac

Abrí Terminal y corré:

```bash
git --version
```

Si aparece un número de versión, ya está instalado. Si no, instalalo con:

```bash
brew install git
```

*(Si no tenés Homebrew: `xcode-select --install` también lo instala)*

---

## Paso 3: Crear el repositorio en GitHub

1. En **github.com**, hacé click en el **+** (arriba a la derecha) → **New repository**
2. Nombre del repo: `patitasba`
3. Marcá: ✅ **Public**
4. Dejá todo lo demás como está y hacé click en **Create repository**
5. GitHub te va a mostrar una pantalla con comandos. **Copiá la URL del repo**, que va a ser algo como:
   ```
   https://github.com/TU-USUARIO/patitasba.git
   ```

---

## Paso 4: Configurar git en la carpeta PatitasBA

Abrí Terminal, navegá a la carpeta donde tenés los archivos y corré estos comandos
**uno por uno**:

```bash
# 1. Inicializar git
git init

# 2. Configurar tu identidad (una sola vez)
git config user.name "Tu Nombre"
git config user.email "tu@email.com"

# 3. Renombrar la rama principal
git branch -M main

# 4. Conectar con tu repo en GitHub (reemplazá TU-USUARIO)
git remote add origin https://github.com/TU-USUARIO/patitasba.git

# 5. Renombrar patitasba.html a index.html (necesario para GitHub Pages)
mv patitasba.html index.html

# 6. Agregar todos los archivos y hacer el primer commit
git add .
git commit -m "PatitasBA: primer deploy"

# 7. Subir a GitHub
git push -u origin main
```

> 💡 La primera vez que hagas `git push`, GitHub va a pedirte usuario y contraseña.
> Usá tu usuario de GitHub y un **Personal Access Token** (no tu contraseña de login).
> Para crear el token: github.com → Settings → Developer Settings → Personal access tokens → Generate new token → marcá "repo" → copiá el token y usalo como contraseña.

---

## Paso 5: Activar GitHub Pages

1. Andá a tu repo en github.com: `github.com/TU-USUARIO/patitasba`
2. Click en **Settings** (pestaña arriba a la derecha)
3. En el menú izquierdo, click en **Pages**
4. En "Source", elegí: **Deploy from a branch**
5. Branch: **main** / folder: **/ (root)**
6. Click en **Save**

En 1-2 minutos, el sitio va a estar vivo en:
```
https://TU-USUARIO.github.io/patitasba/
```

---

## Paso 6: Configurar actualización automática diaria

Para que el sitio se actualice solo cada día:

```bash
# Activar el cron (solo corré esto una vez)
bash activar_actualizacion_diaria.sh
```

Desde ese momento, cada día a las 8 AM tu Mac va a:
1. Correr el scraper (scrapea Instagram)
2. Actualizar `pets.json` y las imágenes
3. Hacer `git push` automáticamente
4. El sitio en GitHub Pages se actualiza solo

> ⚠️ **Importante**: La Mac tiene que estar encendida a las 8 AM para que corra el cron.
> Si está dormida, corre la próxima vez que la prendas.

---

## Notas finales

- **Dominio propio**: Si querés `patitasba.com.ar` en lugar de `github.io/patitasba`,
  comprás el dominio (~$5/año) y lo configurás en las mismas Settings de GitHub Pages.

- **Imágenes**: Las imágenes se guardan en la carpeta `images/` que se sube a GitHub.
  Con el tiempo puede crecer, pero tardan mucho en llegar al límite (1GB).

- **Costo total**: **$0** (salvo que quieras dominio propio).
