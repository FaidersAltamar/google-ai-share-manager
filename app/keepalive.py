"""Keep-alive: refresca periódicamente las sesiones guardadas para que no caduquen
por inactividad. Cada ciclo navega a Google con las cookies y re-guarda el estado."""
import json
import os
import threading
import time
import traceback

SESSIONS_DIR = "/app/sessions"
STATE_FILE = os.path.join(SESSIONS_DIR, "_keepalive_state.json")
INTERVAL_SECONDS = int(os.environ.get("KEEPALIVE_INTERVAL", 48 * 3600))

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _load_state() -> dict:
    try:
        return json.load(open(STATE_FILE, encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        json.dump(state, open(STATE_FILE, "w", encoding="utf-8"), indent=2)
    except Exception:
        pass


def touch_session(session_path: str) -> dict:
    """Abre Google con la sesión guardada; si es válida, re-guarda el estado fresco."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            context = browser.new_context(user_agent=UA, storage_state=session_path)
            page = context.new_page()
            page.goto("https://www.google.com/", timeout=30000)
            time.sleep(3)
            cookies = {c["name"] for c in context.cookies()}
            viva = "SAPISID" in cookies or "__Secure-1PAPISID" in cookies
            if viva:
                context.storage_state(path=session_path)
            return {"ok": viva, "checked_at": int(time.time())}
        finally:
            browser.close()


def keepalive_loop() -> None:
    while True:
        try:
            os.makedirs(SESSIONS_DIR, exist_ok=True)
            state = _load_state()
            for fname in os.listdir(SESSIONS_DIR):
                if not fname.endswith(".json") or fname.startswith("_"):
                    continue
                path = os.path.join(SESSIONS_DIR, fname)
                account = fname[:-5]
                try:
                    result = touch_session(path)
                    state[account] = result
                    print(f"[keepalive] {account}: {'viva ✅' if result['ok'] else 'muerta ❌'}")
                except Exception as e:  # noqa: BLE001
                    state[account] = {"ok": False, "error": str(e), "checked_at": int(time.time())}
                    print(f"[keepalive] {account}: error {e}")
                    traceback.print_exc()
            _save_state(state)
        except Exception as e:  # noqa: BLE001
            print(f"[keepalive] ciclo fallido: {e}")
        time.sleep(INTERVAL_SECONDS)


def start_keepalive_thread() -> None:
    t = threading.Thread(target=keepalive_loop, daemon=True, name="keepalive")
    t.start()
