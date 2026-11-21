# Google Share Generator — Lovable Integration Package

**AI Share Manager v2.2** — Bare token generation system using FoxPhone Galaxy S21 via ADB over SSH.

## Quick Start for Lovable

### Base URLs
- **Production (HTTPS)**: `https://s7.scal7.com` (after CNAME configured)
- **Development (HTTP)**: `http://179.66.140.79:8000`

### Authentication
All endpoints except `/health` require the `X-API-Key` header:
```
X-API-Key: GSG-2026-secure-key-7x9m2p
```

---

## Complete TypeScript/JavaScript Integration

### 1. Core API Client (`src/lib/google-share-api.ts`)

```typescript
// src/lib/google-share-api.ts
const API_BASE = import.meta.env.VITE_GOOGLE_SHARE_API_URL || 'https://s7.scal7.com';
const API_KEY = import.meta.env.VITE_GOOGLE_SHARE_API_KEY || 'GSG-2026-secure-key-7x9m2p';

interface ApiHeaders extends HeadersInit {
  'Content-Type': 'application/json';
  'X-API-Key': string;
}

function getHeaders(): ApiHeaders {
  return {
    'Content-Type': 'application/json',
    'X-API-Key': API_KEY,
  };
}

async function fetchJson<T>(url: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(url, {
    ...options,
    headers: {
      ...getHeaders(),
      ...options.headers,
    },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: 'unknown_error' }));
    throw new Error(`API Error ${response.status}: ${JSON.stringify(error)}`);
  }

  return response.json();
}

// Types
export interface TokenEntry {
  code: string;
  link: string;
  nota: string;
  creado: number;
  verificado: {
    url_consulta: string;
    estado: 'vivo' | 'vivo_render_js' | 'muerto' | `error: ${string}`;
    destino: string | null;
  };
  ultima_verificacion: number;
  duplicado?: boolean;
}

export interface QueueResponse {
  ok: boolean;
  posicion: number;
}

export interface QueuePeekResponse {
  url: string | null;
  posicion?: number;
  total?: number;
  peek?: boolean;
}

export interface BareRegisterResponse {
  ok: boolean;
  duplicado: boolean;
  code: string;
  link: string;
  nota: string;
  creado: number;
  verificado: TokenEntry['verificado'];
  ultima_verificacion: number;
}

export interface HealthResponse {
  status: 'ok';
  message: string;
}

export interface ListResponse {
  total: number;
  links: TokenEntry[];
}

// API Functions

/** Health check (public, no API key needed) */
export async function healthCheck(): Promise<HealthResponse> {
  return fetchJson(`${API_BASE}/health`);
}

/** Enqueue a URL for automatic bare token generation */
export async function queueUrl(url: string): Promise<QueueResponse> {
  return fetchJson(`${API_BASE}/links/queue`, {
    method: 'POST',
    body: JSON.stringify({ url }),
  });
}

/** Peek at the queue without removing items */
export async function peekQueue(): Promise<QueuePeekResponse> {
  return fetchJson(`${API_BASE}/links/queue?peek=true`);
}

/** Register a bare token manually (if you already have one) */
export async function registerBareToken(code: string, nota = ''): Promise<BareRegisterResponse> {
  return fetchJson(`${API_BASE}/links/bare`, {
    method: 'POST',
    body: JSON.stringify({ code, nota }),
  });
}

/** List all registered tokens */
export async function listTokens(): Promise<ListResponse> {
  return fetchJson(`${API_BASE}/links/list`);
}

/** Re-validate a specific token */
export async function checkToken(code: string): Promise<TokenEntry> {
  return fetchJson(`${API_BASE}/links/check/${code}`);
}

/** Get worker logs for debugging */
export async function getWorkerLogs(last = 80): Promise<{ lines: string[] }> {
  return fetchJson(`${API_BASE}/debug/workerlog?last=${last}`);
}
```

### 2. React Hook (`src/hooks/useGoogleShare.ts`)

```typescript
// src/hooks/useGoogleShare.ts
import { useState, useCallback, useEffect } from 'react';
import {
  healthCheck,
  queueUrl,
  listTokens,
  registerBareToken,
  checkToken,
  getWorkerLogs,
  TokenEntry,
  QueueResponse,
  ListResponse,
  BareRegisterResponse,
} from '@/lib/google-share-api';

export function useGoogleShare() {
  const [tokens, setTokens] = useState<TokenEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [workerLogs, setWorkerLogs] = useState<string[]>([]);
  const [healthy, setHealthy] = useState(false);

  const refreshTokens = useCallback(async () => {
    try {
      const response: ListResponse = await listTokens();
      setTokens(response.links);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load tokens');
    }
  }, []);

  const checkHealth = useCallback(async () => {
    try {
      await healthCheck();
      setHealthy(true);
    } catch {
      setHealthy(false);
    }
  }, []);

  const enqueueUrl = useCallback(async (url: string): Promise<QueueResponse | null> => {
    setLoading(true);
    setError(null);
    try {
      const result = await queueUrl(url);
      // Poll for completion
      const pollInterval = setInterval(async () => {
        const logs = await getWorkerLogs(5);
        setWorkerLogs(logs.lines);
        const list = await listTokens();
        setTokens(list.links);
        // Check if our URL was processed
        const found = list.links.find(t => t.nota.includes(url) || t.link.includes(url));
        if (found) {
          clearInterval(pollInterval);
        }
      }, 5000);
      
      // Stop polling after 2 minutes
      setTimeout(() => clearInterval(pollInterval), 120000);
      
      return result;
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to enqueue URL');
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  const addManualToken = useCallback(async (code: string, nota = ''): Promise<BareRegisterResponse | null> => {
    setLoading(true);
    setError(null);
    try {
      const result = await registerBareToken(code, nota);
      await refreshTokens();
      return result;
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to register token');
      return null;
    } finally {
      setLoading(false);
    }
  }, [refreshTokens]);

  const revalidateToken = useCallback(async (code: string): Promise<TokenEntry | null> => {
    try {
      const result = await checkToken(code);
      setTokens(prev => prev.map(t => t.code === code ? result : t));
      return result;
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to revalidate token');
      return null;
    }
  }, []);

  const fetchLogs = useCallback(async () => {
    try {
      const logs = await getWorkerLogs(100);
      setWorkerLogs(logs.lines);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to fetch logs');
    }
  }, []);

  // Initial load
  useEffect(() => {
    checkHealth();
    refreshTokens();
  }, [checkHealth, refreshTokens]);

  return {
    tokens,
    loading,
    error,
    workerLogs,
    healthy,
    refreshTokens,
    checkHealth,
    enqueueUrl,
    addManualToken,
    revalidateToken,
    fetchLogs,
  };
}
```

### 3. Lovable Component Example (`src/components/GoogleShareGenerator.tsx`)

```tsx
// src/components/GoogleShareGenerator.tsx
import React, { useState } from 'react';
import { useGoogleShare } from '@/hooks/useGoogleShare';

export function GoogleShareGenerator() {
  const {
    tokens,
    loading,
    error,
    healthy,
    enqueueUrl,
    addManualToken,
    revalidateToken,
    refreshTokens,
  } = useGoogleShare();

  const [urlInput, setUrlInput] = useState('');
  const [manualCode, setManualCode] = useState('');
  const [manualNota, setManualNota] = useState('');

  const handleEnqueue = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!urlInput.trim()) return;
    await enqueueUrl(urlInput.trim());
    setUrlInput('');
  };

  const handleManualRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!manualCode.trim()) return;
    await addManualToken(manualCode.trim(), manualNota.trim());
    setManualCode('');
    setManualNota('');
  };

  const formatDate = (ts: number) => new Date(ts * 1000).toLocaleString();

  const getStatusColor = (estado: string) => {
    if (estado === 'vivo') return 'text-green-400';
    if (estado === 'vivo_render_js') return 'text-yellow-400';
    if (estado === 'muerto') return 'text-red-400';
    return 'text-gray-400';
  };

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-8">
      {/* Health Status */}
      <div className="flex items-center gap-4 p-4 bg-gray-900 rounded-lg border border-gray-700">
        <div className={`w-3 h-3 rounded-full ${healthy ? 'bg-green-500' : 'bg-red-500'}`} />
        <span className="text-lg font-medium">
          {healthy ? 'Google Share Generator: Online' : 'Google Share Generator: Offline'}
        </span>
        <button
          onClick={refreshTokens}
          disabled={loading}
          className="ml-auto px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg text-white disabled:opacity-50"
        >
          {loading ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      {/* Error Display */}
      {error && (
        <div className="p-4 bg-red-900/30 border border-red-700 rounded-lg text-red-300">
          {error}
        </div>
      )}

      {/* Enqueue URL Form */}
      <div className="bg-gray-900 rounded-lg border border-gray-700 p-6">
        <h3 className="text-xl font-semibold mb-4">Generate Bare Token (Auto)</h3>
        <form onSubmit={handleEnqueue} className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-2">URL to share</label>
            <input
              type="url"
              value={urlInput}
              onChange={e => setUrlInput(e.target.value)}
              placeholder="https://example.com/campaign"
              className="w-full px-4 py-3 bg-gray-800 border border-gray-600 rounded-lg text-white placeholder-gray-500 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              required
            />
          </div>
          <button
            type="submit"
            disabled={loading || !urlInput.trim()}
            className="w-full py-3 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded-lg font-medium text-white"
          >
            {loading ? 'Processing...' : 'Generate & Queue Token'}
          </button>
        </form>
        <p className="text-sm text-gray-500 mt-2">
          The worker will process this URL using the FoxPhone Galaxy S21 and generate a bare share token.
          Processing takes ~30-60 seconds. Check the token list below for results.
        </p>
      </div>

      {/* Manual Token Registration */}
      <div className="bg-gray-900 rounded-lg border border-gray-700 p-6">
        <h3 className="text-xl font-semibold mb-4">Register Token Manually</h3>
        <form onSubmit={handleManualRegister} className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-2">Bare Code or Full URL</label>
            <input
              type="text"
              value={manualCode}
              onChange={e => setManualCode(e.target.value)}
              placeholder="WMyKWC62Q2npk4RvQ or https://www.google.com/share.google?q=WMyKWC62Q2npk4RvQ"
              className="w-full px-4 py-3 bg-gray-800 border border-gray-600 rounded-lg text-white placeholder-gray-500 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-2">Note (optional)</label>
            <input
              type="text"
              value={manualNota}
              onChange={e => setManualNota(e.target.value)}
              placeholder="campaign name, source, etc."
              className="w-full px-4 py-3 bg-gray-800 border border-gray-600 rounded-lg text-white placeholder-gray-500 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>
          <button
            type="submit"
            disabled={loading || !manualCode.trim()}
            className="w-full py-3 bg-green-600 hover:bg-green-700 disabled:opacity-50 rounded-lg font-medium text-white"
          >
            Register Token
          </button>
        </form>
      </div>

      {/* Token Catalog */}
      <div className="bg-gray-900 rounded-lg border border-gray-700 overflow-hidden">
        <div className="p-4 border-b border-gray-700 flex justify-between items-center">
          <h3 className="text-xl font-semibold">Token Catalog ({tokens.length})</h3>
          <button
            onClick={refreshTokens}
            disabled={loading}
            className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-white disabled:opacity-50 text-sm"
          >
            Refresh
          </button>
        </div>

        {tokens.length === 0 ? (
          <div className="p-8 text-center text-gray-500">
            No tokens yet. Generate one above or register manually.
          </div>
        ) : (
          <div className="divide-y divide-gray-700">
            {tokens.map((token) => (
              <div key={token.code} className="p-4 hover:bg-gray-800/50">
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-3 flex-wrap">
                      <a
                        href={token.link}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="font-mono text-blue-400 hover:text-blue-300 break-all"
                      >
                        {token.link}
                      </a>
                      <span className={`px-2 py-1 text-xs rounded ${getStatusColor(token.verificado.estado)}`}>
                        {token.verificado.estado}
                      </span>
                      {token.duplicado && (
                        <span className="px-2 py-1 text-xs rounded bg-gray-700 text-gray-300">Duplicate</span>
                      )}
                    </div>
                    <div className="mt-2 text-sm text-gray-400 space-y-1">
                      <p><strong>Note:</strong> {token.nota || '—'}</p>
                      <p><strong>Created:</strong> {formatDate(token.creado)}</p>
                      <p><strong>Last verified:</strong> {formatDate(token.ultima_verificacion)}</p>
                      {token.verificado.destino && (
                        <p>
                          <strong>Destination:</strong>{' '}
                          <a href={token.verificado.destino} target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:underline">
                            {token.verificado.destino}
                          </a>
                        </p>
                      )}
                    </div>
                  </div>
                  <button
                    onClick={() => revalidateToken(token.code)}
                    disabled={loading}
                    className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-white disabled:opacity-50 text-sm whitespace-nowrap"
                  >
                    Re-validate
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
```

### 4. Environment Variables (`.env.local`)

```bash
# Lovable / Vite environment variables
VITE_GOOGLE_SHARE_API_URL=https://s7.scal7.com
VITE_GOOGLE_SHARE_API_KEY=GSG-2026-secure-key-7x9m2p
```

### 5. Usage in Lovable Page

```tsx
// src/pages/GoogleSharePage.tsx (or wherever you want to use it)
import { GoogleShareGenerator } from '@/components/GoogleShareGenerator';

export default function GoogleSharePage() {
  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <GoogleShareGenerator />
    </div>
  );
}
```

---

## API Endpoint Reference

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/health` | No | Health check |
| POST | `/links/queue` | Yes | Enqueue URL for auto-generation |
| GET | `/links/queue?peek=true` | Yes | Inspect queue (non-destructive) |
| POST | `/links/bare` | Yes | Register bare token manually |
| GET | `/links/list` | Yes | List all tokens |
| GET | `/links/check/{code}` | Yes | Re-validate specific token |
| POST | `/adb-creds` | Yes | Upload SSH credentials (operator only) |
| GET | `/adb-creds` | Yes | Get SSH credentials (worker) |
| GET | `/debug/workerlog?last=80` | Yes | Get worker logs |
| POST | `/exec/sh` | Token | Execute shell (operator diagnostic) |

---

## Token Format

All tokens are stored and returned in this format:
```
https://www.google.com/share.google?q=CODE
```

Where `CODE` is the alphanumeric token (8-40 chars).

The API accepts these formats on input:
- `https://www.google.com/share.google?q=CODE`
- `https://share.google/CODE`
- `CODE` (bare code only)

---

## Validation States

| Estado | Meaning |
|--------|---------|
| `vivo` | Token redirects to final destination (outside google.com) |
| `vivo_render_js` | Token alive but requires JS to redirect |
| `muerto` | "Something went wrong" / "not available" |
| `error: ...` | Network/timeout error during validation |

---

## Worker Processing Details

- **Device**: FoxPhone Galaxy S21 (pod 7709363018911996714)
- **Strategy**: S2-autocomplete → S3-organic → S1-direct (automatic fallback)
- **Throughput**: ~1 token per 30-60 seconds
- **Queue**: FIFO, persistent in `/app/sessions/queue.json`
- **SSH Credentials**: Expire ~24-48h, must be refreshed via `fox_creds_refresh.py`

### Refreshing SSH Credentials (Operator Task)

Run locally on your PC (residential IP, no captcha):
```bash
cd google-share-generator
python fox_creds_refresh.py
```

This logs into `console.foxphone.com`, extracts fresh SSH credentials from the "ADB Info" modal, and uploads them to the API automatically.

---

## Production Checklist

- [ ] CNAME record added in Cloudflare Dashboard:
  - Name: `s7`
  - Target: `07a68ea7-75f9-4b96-b7fa-d85e3865a51e.cfargotunnel.com`
  - Proxy: **Proxied** (orange cloud)
- [ ] API_KEY set in docker-compose.yml (done: `GSG-2026-secure-key-7x9m2p`)
- [ ] SSH credentials refreshed (run `python fox_creds_refresh.py`)
- [ ] Health check passes: `https://s7.scal7.com/health`
- [ ] Test token generation works end-to-end

---

## Support

- Worker logs: `GET /debug/workerlog?last=100`
- Debug source: `GET /debug/source/worker_fox.py`
- Queue inspection: `GET /links/queue?peek=true`