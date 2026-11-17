"""Captura cookies de tu navegador (donde ya estás logueado en Google) y las sube al VPS.

TRES formas de obtener las cookies (elige la que te resulte más fácil):

MÉTODO A — DevTools (sin extensiones):
  1. Abre https://www.google.com en Chrome, logueado.
  2. F12 → pestaña Network → recarga la página (F5).
  3. Clic en la primera petición (el documento de google.com).
  4. En 'Request Headers', copia TODO el valor de 'cookie:' (clic derecho → Copy value).

MÉTODO B — Extensiones (más cómodo):
  - Instala 'EditThisCookie' o 'Cookie-Editor' en Chrome.
  - En google.com logueado: abre la extensión → exporta (JSON).
  - Guarda el JSON en un archivo y pásalo a este script con --file.

MÉTODO C — storage_state completo de Playwright:
  - Ejecuta primero: python crear_sesion.py
  - Luego: python agregar_cookies.py --file app/sessions/primary.json --tipo storage_state
"""
import argparse
import json
import sys
import urllib.request

VPS = "http://179.66.140.79:8000"


def subir(url: str, body: dict) -> None:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        print(r.status, r.read().decode("utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="Archivo con las cookies (JSON array, header string o storage_state)")
    ap.add_argument("--tipo", choices=["auto", "header", "json", "storage_state"], default="auto",
                    help="Formato de entrada (auto lo detecta)")
    ap.add_argument("--account", default="primary")
    ap.add_argument("--stdin", action="store_true", help="Pegar las cookies por consola")
    args = ap.parse_args()

    if args.file:
        raw = open(args.file, encoding="utf-8").read().strip()
    elif args.stdin:
        print("Pega las cookies y termina con ENTER en una línea vacía (Ctrl+Z luego Enter en Windows si es necesario):")
        lines = []
        while True:
            try:
                line = input()
            except EOFError:
                break
            if line.strip() == "" and lines:
                break
            lines.append(line)
        raw = "\n".join(lines).strip()
    else:
        print(__doc__)
        sys.exit(1)

    tipo = args.tipo
    if tipo == "auto":
        if raw.startswith("{") and '"cookies"' in raw and '"origins"' in raw:
            tipo = "storage_state"
        elif raw.startswith("["):
            tipo = "json"
        else:
            tipo = "header"

    if tipo == "storage_state":
        state = json.loads(raw)
        body = {"account": args.account, "storage_state": state}
        url = f"{VPS}/session/storage-state"
    else:
        if tipo == "json":
            cookies = json.loads(raw)
        else:
            cookies = raw  # string header; el API lo parsea
        body = {"account": args.account, "cookies": cookies}
        url = f"{VPS}/session/cookies"

    print(f"Subiendo ({tipo}) a {url} ...")
    subir(url, body)
    print("\nVerifica con: curl http://179.66.140.79:8000/session/list")


if __name__ == "__main__":
    main()
