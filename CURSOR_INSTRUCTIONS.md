# Google Share Generator — Instrucciones Completas para Cursor

## 🎯 Objetivo
Completar el despliegue del **Google Share Generator v2.2** en VPS Hostinger (srv2148909) para generar **tokens bare** `https://www.google.com/share.google?q=CODE` usando **FoxPhone Galaxy S21** vía ADB/SSH, con API protegida por **X-API-Key** y HTTPS vía **Cloudflare Tunnel**.

---

## ✅ Estado Actual (Ya Desplegado y Funcionando)

| Componente | Estado | Detalle |
|------------|--------|---------|
| **API (ai-share-manager)** | ✅ Running | Puerto 8000, health checks 200 OK desde Cloudflare |
| **Worker (ai-share-worker)** | ✅ Running | Polling cola FIFO cada 10s, logs activos |
| **Cloudflare Tunnel (cloudflared-s7)** | ✅ Running | Tunnel ID `07a68ea7-75f9-4b96-b7fa-d85e3865a51e`, 4 conexiones healthy |
| **X-API-Key Auth** | ✅ Enabled | `GSG-2026-secure-key-7x9m2p` en todos los endpoints excepto `/health` |
| **Health Endpoint** | ✅ Correcto | `{"status":"ok","message":"Google Share Generator operativo"}` |
| **Formato Token** | ✅ Estandarizado | `https://www.google.com/share.google?q=CODE` (sin referencias AKR) |
| **Estrategias Tiered** | ✅ Implementadas | S2-autocomplete → S3-organic → S1-direct con fallback automático |
| **Integración Lovable** | ✅ Documentada | `lovable-integration.md` con cliente TS, hook React, componente |

---

## ⚠️ Dos Acciones Manuales Pendientes (Solo Operador)

### 1. Añadir CNAME en Cloudflare Dashboard (Requerido para HTTPS)

**Pasos:**
1. Entrar a [dash.cloudflare.com](https://dash.cloudflare.com) → Dominio `scal7.com`
2. DNS → Records → **Add Record**
3. Configurar:
   ```
   Type: CNAME
   Name: s7
   Target: 07a68ea7-75f9-4b96-b7fa-d85e3865a51e.cfargotunnel.com
   Proxy status: Proxied (nube naranja)
   TTL: Auto
   ```
4. Save

**Verificación:** Esperar 1-2 min propagación, luego:
```bash
curl https://s7.scal7.com/health
# Debe responder: {"status":"ok","message":"Google Share Generator operativo"}
```

> **Nota:** El token del tunnel no tiene permisos DNS Write/Read, por eso debe hacerse manualmente.

---

### 2. Refrescar Credenciales SSH del FoxPhone (Requerido para Worker)

**Ejecutar LOCALMENTE en tu PC (tiene Playwright + cookies de sesión):**

```bash
cd D:\Proyectos\Hacking etico\google-share-generator
python fox_creds_refresh.py
```

**Qué hace el script:**
1. Abre `console.foxphone.com` con Playwright (usa cookies guardadas)
2. Navega al pod `7709363018911996714` (Galaxy S21)
3. Abre modal **"ADB Info"** → extrae: `user`, `host`, `port`, `lport`, `rhost`, `rport`, `pass`
4. Sube credenciales vía `POST /adb-creds` al VPS (con X-API-Key)
5. Guarda localmente en `debug_fox/ssh_creds.json`

**Evidencia de fallo actual:** Logs del worker muestran:
```
FoxWorkerLOG: SSHConnect failed: Authentication failed.
FoxWorkerLOG: Token obtained: {'ok': False, 'error': 'SSH connection failed'}
```
Las credenciales expiran ~24-48h. El script las renueva.

---

## 🔧 Verificación End-to-End (Tras completar lo anterior)

```bash
# 1. Health público (HTTPS)
curl https://s7.scal7.com/health

# 2. Encolar URL para generación automática (requiere API Key)
curl -X POST https://s7.scal7.com/links/queue \
  -H "Content-Type: application/json" \
  -H "X-API-Key: GSG-2026-secure-key-7x9m2p" \
  -d '{"url": "https://www.youtube.com/shorts/DRZWWZppkAI"}'

# 3. Verificar cola (peek, no consume)
curl -H "X-API-Key: GSG-2026-secure-key-7x9m2p" \
  "https://s7.scal7.com/links/queue?peek=true"

# 4. Esperar 30-60s (worker procesa: SSH → ADB → Google → Share → Token)
# 5. Consultar catálogo
curl -H "X-API-Key: GSG-2026-secure-key-7x9m2p" \
  https://s7.scal7.com/links/list

# Respuesta esperada:
# {
#   "total": 1,
#   "links": [{
#     "code": "WMyKWC62Q2npk4RvQ",
#     "link": "https://www.google.com/share.google?q=WMyKWC62Q2npk4RvQ",
#     "nota": "auto:https://www.youtube.com/shorts/DRZWWZppkAI",
#     "creado": 1795210818,
#     "verificado": {
#       "url_consulta": "https://www.google.com/share.google?q=WMyKWC62Q2npk4RvQ",
#       "estado": "vivo",
#       "destino": "https://www.youtube.com/shorts/DRZWWZppkAI"
#     },
#     "ultima_verificacion": 1795214400
#   }]
# }
```

---

## 📁 Archivos Clave (Local ↔ VPS Sincronizados)

```
google-share-generator/
├── docker-compose.yml          # 3 servicios: api, worker, cloudflared
├── Dockerfile                  # Playwright Python + adb (platform-tools)
├── requirements.txt            # deps Python
├── fox_creds_refresh.py        # Script LOCAL para refrescar SSH creds
├── app/
│   ├── api.py                  # FastAPI + X-API-Key + 11 endpoints
│   └── worker_fox.py           # FoxWorker + estrategias S2→S3→S1
├── API_DOCS.md                 # Documentación completa API + JS examples
├── lovable-integration.md      # Cliente TS, hook React, componente Lovable
└── debug_fox/                  # Credenciales SSH, logs, screenshots
    ├── ssh_creds.json          # Credenciales actuales (expiradas)
    ├── fox_session.json        # Cookies sesión FoxPhone
    └── panel_html.txt          # HTML debug panel
```

---

## 🐳 Docker Compose (Configuración VPS)

```yaml
services:
  ai-share-manager:
    build: .
    container_name: ai-share-manager
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - ./app/sessions:/app/sessions
    networks:
      - ai-share-net
    environment:
      - TZ=America/Bogota
      - VPS_API=http://ai-share-manager:8000
      - ADB_BIN=/opt/platform-tools/platform-tools/adb
      - DIAG_PORT=19536
      - API_KEY=GSG-2026-secure-key-7x9m2p

  ai-share-worker:
    build: .
    container_name: ai-share-worker
    restart: unless-stopped
    volumes:
      - ./app/sessions:/app/sessions
    networks:
      - ai-share-net
    environment:
      - TZ=America/Bogota
      - VPS_API=http://ai-share-manager:8000
      - ADB_BIN=/opt/platform-tools/platform-tools/adb
      - DIAG_PORT=19537
      - API_KEY=GSG-2026-secure-key-7x9m2p
    command: python -u /app/worker_fox.py

  cloudflared-s7:
    image: cloudflare/cloudflared:latest
    container_name: cloudflared-s7
    restart: unless-stopped
    network_mode: host
    command: tunnel --no-autoupdate run --token eyJhIjoiZWRhNTZjYzA3Y2UzZWMwZmIwODdlOTQzNzRhZjRjNDQiLCJ0IjoiMDdhNjhlYTctNzVmOS00Yjk2LWI3ZmEtZDg1ZTM4NjVhNTFlIiwicyI6Im04UmVVcUtqa0xtcjVwcmVzTWY1d3hBenRjelczYnJ1ZlZxNndJRFBPK1E3OG9XSUlhSUdMajdJWEZvZ2d5bzFXL0R3QWdlV2sxQTFIZHNkQnlzOHF3PT0ifQ==
    environment:
      - TZ=America/Bogota

networks:
  ai-share-net:
    name: ai-share-net
    driver: bridge
```

---

## 🔑 Variables de Entorno Críticas

| Variable | Valor | Dónde |
|----------|-------|-------|
| `API_KEY` | `GSG-2026-secure-key-7x9m2p` | docker-compose.yml (ambos servicios) |
| `VPS_API` | `http://ai-share-manager:8000` | docker-compose.yml (ambos servicios) |
| `ADB_BIN` | `/opt/platform-tools/platform-tools/adb` | docker-compose.yml (ambos servicios) |
| `DIAG_PORT` | `19536` (api) / `19537` (worker) | docker-compose.yml |

---

## 📡 Endpoints API (Resumen)

| Método | Endpoint | Auth | Descripción |
|--------|----------|------|-------------|
| GET | `/health` | ❌ Público | Estado del servicio |
| POST | `/links/queue` | ✅ X-API-Key | Encolar URL para worker |
| GET | `/links/queue?peek=true` | ✅ X-API-Key | Inspeccionar cola (no consume) |
| POST | `/links/bare` | ✅ X-API-Key | Registrar token manual |
| GET | `/links/list` | ✅ X-API-Key | Catálogo completo |
| GET | `/links/check/{code}` | ✅ X-API-Key | Revalidar token |
| POST | `/adb-creds` | ✅ X-API-Key | Subir credenciales SSH (operador) |
| GET | `/adb-creds` | ✅ X-API-Key | Worker consulta credenciales |
| GET | `/debug/workerlog?last=80` | ✅ X-API-Key | Logs del worker |
| GET | `/debug/source/worker_fox.py` | ✅ X-API-Key | Source para bootstrap |
| POST | `/exec/sh` | 🔐 Token exec | Diagnóstico remoto (operador) |

---

## 🧪 Integración Lovable (Para tu App Web)

**Archivo:** `lovable-integration.md` contiene:

1. **TypeScript API Client** (`GoogleShareAPI` class)
2. **React Hook** (`useGoogleShare`) con métodos:
   - `queueUrl(url)` → encola y espera token
   - `listTokens()` → catálogo
   - `registerToken(code, nota)` → registro manual
   - `checkToken(code)` → revalidar
   - `health()` → health check
3. **Componente React** (`GoogleShareGenerator`) UI lista
4. **Variables de entorno** para `.env.local`:
   ```env
   VITE_GOOGLE_SHARE_API=https://s7.scal7.com
   VITE_GOOGLE_SHARE_API_KEY=GSG-2026-secure-key-7x9m2p
   ```

---

## 🚀 Comandos Útiles VPS (Hostinger MCP)

```bash
# Ver logs en tiempo real
# (usar mcp__hostinger__execute con vps_docker_logs)

# Reiniciar servicios si hay cambios de código
docker compose -f /docker/google-share-generator/docker-compose.yml restart

# Rebuild completo (tras cambios en Dockerfile/requirements)
docker compose -f /docker/google-share-generator/docker-compose.yml build --no-cache
docker compose -f /docker/google-share-generator/docker-compose.yml up -d

# Ver estado contenedores
docker ps --filter "name=ai-share" --filter "name=cloudflared"
```

---

## ✅ Checklist Final para Cursor

- [ ] **CNAME añadido** en Cloudflare Dashboard (`s7.scal7.com` → tunnel)
- [ ] **fox_creds_refresh.py ejecutado** localmente (credenciales SSH frescas)
- [ ] **Health HTTPS responde** `curl https://s7.scal7.com/health`
- [ ] **Queue URL** → worker procesa → token aparece en `/links/list`
- [ ] **Token formato correcto** `https://www.google.com/share.google?q=CODE`
- [ ] **Validación token** muestra `estado: "vivo"` y `destino: URL original`
- [ ] **Lovable integration** probada con API key desde app web

---

## 🆘 Troubleshooting Rápido

| Síntoma | Causa | Solución |
|---------|-------|----------|
| `Authentication failed` en worker logs | SSH creds expiradas | Ejecutar `python fox_creds_refresh.py` |
| `401 invalid_api_key` | Header faltante/incorrecto | Enviar `X-API-Key: GSG-2026-secure-key-7x9m2p` |
| `404 no_creds` en `/adb-creds` | No hay credenciales subidas | Ejecutar `fox_creds_refresh.py` |
| HTTPS `522/523` | CNAME no propagado / tunnel down | Verificar CNAME en CF + `cloudflared-s7` running |
| Worker no procesa cola | SSH falla / ADB disconnect | Revisar `/debug/workerlog`, refrescar creds |
| Token `estado: "muerto"` | Google rechazó share | Reintentar (worker reintenta S2→S3→S1) |

---

## 📞 Contacto / Referencias

- **VPS:** Hostinger srv2148909 (root@179.66.140.79)
- **SSH Key:** `~/.ssh/blazme_thumbs`
- **FoxPhone Pod:** `7709363018911996714` (Galaxy S21, expira 2026-12-18)
- **Cloudflare Tunnel:** `07a68ea7-75f9-4b96-b7fa-d85e3865a51e` (s7.scal7.com)
- **Repo:** `FaidersAltamar/google-ai-share-manager` (público)
- **API Key:** `GSG-2026-secure-key-7x9m2p`

---

**Cursor: Ejecuta las dos acciones manuales arriba, verifica end-to-end, y el sistema quedará 100% operativo para tu app Lovable.**