# AI Share Manager

Gestor self-hosted para generar enlaces públicos de compartir (`share.google`) de conversaciones de Google AI Mode de forma automatizada.

## Arquitectura

- **Playwright + Chromium headless** para el flujo de Compartir de AI Mode
- **FastAPI** expuesto en el puerto 8000 (`/health`, `/generate`)
- **Docker Compose** con red dedicada `ai-share-net` y volumen persistente para sesiones

## Uso

### 1. Primera vez: crear sesión de Google

La sesión se crea una sola vez ejecutando el navegador en modo visible dentro del contenedor:

```bash
# En el VPS
cd /opt/google-ai-share-manager
docker compose run --rm -e HEADLESS=false ai-share-manager \
  python -c "
from generate_share_link import load_config, generate_ai_share_link
import json
print(json.dumps(generate_ai_share_link('prueba inicial'), indent=2))
"
```

> Como el contenedor no tiene pantalla, la forma práctica de crear la sesión es generar
> `app/sessions/primary.json` en local (con `HEADLESS=false` en tu PC, iniciando sesión
> en Google en la ventana que se abre) y copiar ese archivo al VPS:
> `scp app/sessions/primary.json root@TU_VPS:/opt/google-ai-share-manager/app/sessions/`

### 2. Generar un enlace

```bash
curl -X POST http://TU_VPS:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Resumen de novedades de Python 3.13"}'
```

Respuesta:

```json
{
  "ok": true,
  "share_url": "https://share.google/abc123XYZ",
  "content": "Resumen de novedades de Python 3.13",
  "account": "primary",
  "attempts": 1
}
```

### 3. Estado del servicio

```bash
curl http://TU_VPS:8000/health
```

## Configuración (`app/config.json`)

| Clave | Descripción |
|---|---|
| `default_account` | Cuenta usada por defecto |
| `delay_between_actions` | Pausa entre acciones del flujo (segundos) |
| `max_retries_per_link` | Reintentos por enlace |
| `use_corporate_proxy` | Activa proxy (para redes corporativas) |
| `proxy_url` | URL del proxy |
| `accounts` | Lista de cuentas y sus archivos de sesión |

## Notas

- Los enlaces comparten el contenido de la conversación generada; úsalos solo con contenido propio o autorizado.
- Mantén `delay_between_actions` en 1.5–3s para un uso responsable dentro de los límites de la plataforma.
