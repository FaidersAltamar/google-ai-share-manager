# Google Share Generator — API Documentation

**AI Share Manager v2.2** — Bare token generation system using FoxPhone Galaxy S21 via ADB over SSH.

**Base URL:** `http://179.66.140.79:8000` (VPS Hostinger srv2148909) → `https://s7.scal7.com` (tras CNAME Cloudflare)

---

## Authentication

**X-API-Key header required on all endpoints except `/health`.**

```http
X-API-Key: your-api-key-here
```

Configure `API_KEY` environment variable on the server (docker-compose.yml passes `${API_KEY}`). If `API_KEY` is not set, authentication is disabled (dev mode).

The `/exec/sh` endpoint uses a separate token mechanism (operator-only diagnostic).

---

## Endpoints

### 1. Health Check
```http
GET /health
```

**Response:**
```json
{
  "status": "ok",
  "message": "Google Share Generator operativo"
}
```

---

### 2. Queue URL for Token Generation
```http
POST /links/queue
Content-Type: application/json

{
  "url": "https://example.com/page"
}
```

**Response:**
```json
{
  "ok": true,
  "posicion": 1
}
```

**Description:** Adds a URL to the processing queue. The worker polls this endpoint FIFO and generates a bare share token using the FoxPhone device.

---

### 3. Inspect Queue (Non-destructive)
```http
GET /links/queue?peek=true
```

**Response:**
```json
{
  "url": "https://example.com/page",
  "posicion": 1,
  "total": 3,
  "peek": true
}
```

**Response (empty queue):**
```json
{ "url": null }
```

---

### 4. Register Bare Token (Manual)
```http
POST /links/bare
Content-Type: application/json

{
  "code": "https://www.google.com/share.google?q=WMyKWC62Q2npk4RvQ",
  "nota": "campaña verano 2024"
}
```

**Accepted `code` formats:**
- `https://www.google.com/share.google?q=CODE`
- `https://share.google/CODE`
- `CODE` (bare code only)

**Response (new):**
```json
{
  "ok": true,
  "duplicado": false,
  "code": "WMyKWC62Q2npk4RvQ",
  "link": "https://www.google.com/share.google?q=WMyKWC62Q2npk4RvQ",
  "nota": "campaña verano 2024",
  "creado": 1795210818,
  "verificado": {
    "url_consulta": "https://www.google.com/share.google?q=WMyKWC62Q2npk4RvQ",
    "estado": "vivo",
    "destino": "https://example.com/page"
  },
  "ultima_verificacion": 1795210818
}
```

**Response (duplicate):**
```json
{
  "ok": true,
  "duplicado": true,
  "code": "WMyKWC62Q2npk4RvQ",
  "link": "https://www.google.com/share.google?q=WMyKWC62Q2npk4RvQ",
  "nota": "campaña verano 2024",
  "creado": 1795210818,
  "verificado": { ... },
  "ultima_verificacion": 1795214400
}
```

**Validation states (`verificado.estado`):**
| Estado | Significado |
|--------|-------------|
| `vivo` | Token redirige a destino final (fuera de google.com) |
| `vivo_render_js` | Token vivo pero requiere JS para redirigir |
| `muerto` | "Something went wrong" / "no está disponible" |
| `error: ...` | Error de red/timeout al validar |

---

### 5. List Catalog
```http
GET /links/list
```

**Response:**
```json
{
  "total": 2,
  "links": [
    {
      "code": "WMyKWC62Q2npk4RvQ",
      "link": "https://www.google.com/share.google?q=WMyKWC62Q2npk4RvQ",
      "nota": "campaña verano 2024",
      "creado": 1795210818,
      "verificado": {
        "url_consulta": "https://www.google.com/share.google?q=WMyKWC62Q2npk4RvQ",
        "estado": "vivo",
        "destino": "https://example.com/page"
      },
      "ultima_verificacion": 1795214400
    }
  ]
}
```

---

### 6. Re-validate Token
```http
GET /links/check/{code}
```

**Response:** Same as single entry in `/links/list`, with updated `verificado` and `ultima_verificacion`.

---

### 7. Upload SSH Credentials (Operator → Worker)
```http
POST /adb-creds
Content-Type: application/json

{
  "user": "7709363018911996714_1795206609",
  "host": "adb.foxphone.com",
  "port": 1824,
  "lport": 9536,
  "rhost": "foxphone",
  "rport": 100,
  "pass_": "base64_encoded_password..."
}
```

**Response:**
```json
{
  "ok": true,
  "file": "/app/sessions/ssh_creds.json",
  "cred": {
    "user": "7709363018911996714_1795206609",
    "host": "adb.foxphone.com",
    "port": 1824,
    "lport": 9536,
    "rhost": "foxphone",
    "rport": 100,
    "pass": "VXhpkxjt+jTc..."
  }
}
```

**Source:** Run locally on operator PC: `python fox_creds_refresh.py` (logs into console.foxphone.com, extracts SSH creds from "ADB Info" modal, uploads here).

---

### 8. Get SSH Credentials (Worker → API)
```http
GET /adb-creds
```

**Response:** Same JSON as uploaded (used by worker to establish SSH tunnel).

---

### 9. Debug: Worker Logs
```http
GET /debug/workerlog?last=80
```

**Response:**
```json
{
  "lines": [
    "[21:30:15] FoxWorkerLOG: Processing: https://example.com",
    "[21:30:20] FoxWorkerLOG: Attempting S2-autocomplete...",
    "[21:30:45] FoxWorkerLOG: Success with S3-organic: https://www.google.com/share.google?q=WMyKWC62Q2npk4RvQ"
  ]
}
```

---

### 10. Debug: Source Code (Bootstrap)
```http
GET /debug/source/worker_fox.py
```

**Response:** Plain text content of `worker_fox.py` (for worker self-update/bootstrap).

---

### 11. Diagnostic: Execute Shell (Operator Only)
```http
POST /exec/sh
Content-Type: application/json

{
  "cmd": "ls -la /app/sessions",
  "token": "exec_token_from_local_storage"
}
```

**Response:**
```json
{
  "code": 0,
  "stdout": "total 12\n-rw-r--r-- 1 root root  456 Nov 20 21:30 links_bare.json\n...",
  "stderr": ""
}
```

**Token:** Generated locally, stored in `/app/sessions/exec_token.json` (cookie `exec`). Never exposed publicly.

---

## Worker Token Generation Strategy (S2 → S3 → S1)

| Estrategia | Descripción |
|------------|-------------|
| **S2-autocomplete** | Escribe dominio[:15] → ENTER → click sugerencia exacta / ENTER en primera |
| **S3-organic** | Escribe dominio → ENTER → busca resultado orgánico en Chrome → click |
| **S1-direct** | Escribe URL completa → ENTER directo |

El worker intenta en orden hasta obtener token. Cada estrategia: wipe app state → launch Google → type → enter → wait → tap "Compartir" → extract token from share sheet.

---

## Integration Example (JavaScript)

```javascript
const API = 'https://s7.scal7.com';  // o http://179.66.140.79:8000 en dev
const API_KEY = 'tu-api-key-aqui';   // configurado en el servidor vía variable de entorno API_KEY

function headers() {
  return {
    'Content-Type': 'application/json',
    'X-API-Key': API_KEY
  };
}

// 1. Encolar URL para generación automática
async function queueUrl(url) {
  const res = await fetch(`${API}/links/queue`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({ url })
  });
  return res.json();
}

// 2. Consultar catálogo
async function listTokens() {
  const res = await fetch(`${API}/links/list`, { headers: headers() });
  return res.json();
}

// 3. Registrar token manual (si ya lo tienes)
async function registerToken(code, nota = '') {
  const res = await fetch(`${API}/links/bare`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({ code, nota })
  });
  return res.json();
}

// 4. Revalidar token existente
async function checkToken(code) {
  const res = await fetch(`${API}/links/check/${code}`, { headers: headers() });
  return res.json();
}

// 5. Health check (público, sin API key)
async function health() {
  const res = await fetch(`${API}/health`);
  return res.json();
}

// Uso típico:
await queueUrl('https://mi-campania.com/landing');
setTimeout(async () => {
  const { links } = await listTokens();
  const last = links[links.length - 1];
  console.log('Token generado:', last.link); // https://www.google.com/share.google?q=CODE
  console.log('Destino validado:', last.verificado.destino);
}, 30000); // esperar ~30s por procesamiento
```

---

## Rate Limits & Considerations

- **FoxPhone pod**: 1 dispositivo, 1 sesión ADB concurrente
- **Worker throughput**: ~1 token cada 30-60s (depende de estrategia exitosa)
- **Queue**: FIFO, persistente en `/app/sessions/queue.json`
- **Token validity**: Validado al registrar + revalidación on-demand via `/links/check/{code}`
- **Credenciales SSH**: Expiran ~24-48h (sesión FoxPhone). Renovar con `fox_creds_refresh.py`

---

## Error Codes

| HTTP | Endpoint | Causa |
|------|----------|-------|
| 400 | `/links/bare` | Código inválido (regex no matchea) |
| 404 | `/links/check/{code}` | Token no existe en catálogo |
| 404 | `/adb-creds` | No hay credenciales subidas |
| 403 | `/exec/sh` | Token inválido/ausente |
| 500 | Cualquiera | Error interno (ver logs worker) |

---

## Files & Persistence (Docker Volume)

```
/app/sessions/
├── links_bare.json      # Catálogo de tokens
├── queue.json           # Cola de URLs pendientes
├── workerlog.txt        # Logs del worker
├── ssh_creds.json       # Credenciales SSH ADB (subidas por operador)
└── exec_token.json      # Token para /exec/sh (generado localmente)
```

Volume: `./app/sessions:/app/sessions` en `docker-compose.yml`

---

## Deployment

```bash
# En VPS - configurar API_KEY antes de deploy
cd /docker/google-share-generator
export API_KEY="tu-api-key-secreta-aqui"  # o añadir a .env / bashrc
docker compose build --no-cache
docker compose up -d

# Verificar health (público)
curl https://s7.scal7.com/health

# En PC operador (para subir credenciales SSH)
cd google-share-generator
python fox_creds_refresh.py

# Encolar URLs (requiere X-API-Key)
curl -X POST https://s7.scal7.com/links/queue \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: tu-api-key-secreta-aqui' \
  -d '{"url": "https://tudominio.com"}'
```

---

## Changelog v2.2

- Worker devuelve tokens en formato `https://www.google.com/share.google?q=CODE`
- API valida y cataloga en mismo formato
- Estrategias S2→S3→S1 con fallback automático
- Health check, queue peek, revalidación on-demand
- Debug endpoints para observabilidad remota
- Eliminadas referencias legacy "AKR" (solo nomenclatura, sin dependencia técnica)