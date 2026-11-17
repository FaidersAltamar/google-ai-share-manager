# AI Share Manager — Despliegue en VPS Hostinger

Gestor self-hosted de enlaces públicos de compartir (`share.google`) para conversaciones de Google AI Mode, corriendo en Docker sobre el VPS de Hostinger.

## Estado del despliegue (17-nov-2026)

| Componente | Estado |
|---|---|
| Repo GitHub | https://github.com/FaidersAltamar/google-ai-share-manager (público, branch `main`) |
| VPS | srv2148909 (ID Hostinger `2148909`, IP `179.66.140.79`, Ubuntu 24.04 + Docker) |
| Proyecto Docker | `ai-share-manager`, desplegado vía MCP de Hostinger (`vps_docker_create`) |
| Ruta en VPS | `/docker/ai-share-manager/docker-compose.yml` |
| Contenedor | `ai-share-manager` (imagen `mcr.microsoft.com/playwright/python:v1.48.0-jammy`) |
| Puerto | `8000` publicado en 0.0.0.0 |
| Red Docker | `ai-share-net` (aislada; no toca el proyecto `thumbs` que usa 80/443) |
| Volumen de sesiones | volumen nombrado `ai-share-sessions` → montado en `/app/sessions` |
| API | ✅ VIVA: `http://179.66.140.79:8000/health` responde `{"status":"ok",...}` |
| `/generate` | ✅ Validado end-to-end hasta detección de sesión (falla controlada `no session` sin sesión) |
| `/session/upload` | ✅ Disponible para activar cuentas sin SSH |
| Sesión de Google | ⏳ **PENDIENTE — requiere login manual del operador (único paso que no se puede automatizar)** |

## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/health` | Estado + lista de sesiones cargadas |
| POST | `/generate` | `{"prompt": "...", "account": "primary"}` → genera el enlace de compartir |
| POST | `/session/upload` | `{"account": "primary", "storage_state": {...}}` → activa una cuenta |

## Activar la sesión de Google (una sola vez) — 2 vías

### VÍA A: Login asistido (crear_sesion.py)
```bash
cd "D:\Proyectos\Hacking etico\google-share-generator"
python crear_sesion.py
```
Se abre Chrome → inicias sesión (2FA) → el script detecta las cookies de sesión y
guarda `app/sessions/primary.json` → sube solo con:
```bash
python agregar_cookies.py --file app/sessions/primary.json --tipo storage_state
```

### VÍA B: Pegar cookies capturadas de tu navegador (agregar_cookies.py)
Sin instalar nada de Playwright: capturas cookies desde tu Chrome logueado y las subes.

**Cómo capturarlas (Método DevTools, sin extensiones):**
1. Abre `https://www.google.com` logueado
2. `F12` → pestaña **Network** → recarga (`F5`)
3. Clic en la primera petición → **Request Headers** → copia el valor completo de `cookie:`
4. Pégalo en un archivo `cookies.txt` (una sola línea larga `SID=...; HSID=...; ...`)

**Subir:**
```bash
python agregar_cookies.py --file cookies.txt            # detecta formato solo
python agregar_cookies.py --stdin                        # pegar directo en consola
python agregar_cookies.py --file cookies.json --tipo json   # array de EditThisCookie/Cookie-Editor
```
El API valida que contengan cookies de sesión de Google (`SAPISID`/`HSID`/`SSID`...) y las guarda.

### Verificación y uso (ambas vías)
```bash
curl http://179.66.140.79:8000/health          # → "sessions":["primary"] + estado keep-alive
curl http://179.66.140.79:8000/session/list    # detalle por sesión
curl -X POST http://179.66.140.79:8000/generate -H "Content-Type: application/json" \
     -d '{"prompt":"Resumen de novedades de Python 3.13"}'
```

### Keep-alive automático (anti-caducidad)
El contenedor refresca cada sesión cada **48h** (navega a Google con las cookies y
re-guarda el estado fresco). El resultado queda visible en `/health` → `keepalive`.
Variable `KEEPALIVE_INTERVAL` (segundos) configurable en el compose si se quiere otro ritmo.

## Cómo actualizar el sistema

1. Edita el código local → `git commit` → `git push origin main`
2. Recrea el contenedor vía MCP Hostinger: operación `vps_docker_update` (projectName `ai-share-manager`, virtualMachineId `2148909`). El bootstrap re-descarga el repo al arrancar.

## Arquitectura del bootstrap

El contenedor arranca con un `command` que:
1. Descarga el tarball del repo (`github.com/FaidersAltamar/google-ai-share-manager/archive/refs/heads/main.tar.gz`)
2. `pip install -r requirements.txt`
3. `playwright install --with-deps chromium`
4. `cd app && uvicorn api:app --host 0.0.0.0 --port 8000`

Esto evita depender de build contexts del MCP (que solo acepta compose YAML o URL de repo).

## Notas operativas

- `delay_between_actions` en `app/config.json` controla el ritmo del flujo (1.5–3s recomendado).
- Los selectores del script (`textarea[aria-label*='Pregunta']`, `Compartir`, `Crear enlace público`) pueden requerir ajuste si Google cambia su UI; el endpoint `/generate` devuelve el error de Playwright con el locator fallido para diagnosticar.
- Si Google muestra verificación adicional desde la IP del datacenter al usar la sesión, crea la sesión desde tu PC y súbela; si persiste el bloqueo de datacenter, evalúa proxy corporativo en `config.json`.
