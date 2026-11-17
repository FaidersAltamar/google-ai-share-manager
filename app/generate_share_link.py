"""Genera enlaces públicos de compartir (share.google) para contenido
de Google AI Mode, automatizando el flujo oficial de Compartir."""
import json
import os
import re
import time

from playwright.sync_api import BrowserContext, sync_playwright

CONFIG_PATH = os.environ.get(
    "CONFIG_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_account(config: dict, account_name: str | None) -> dict:
    wanted = account_name or config["default_account"]
    for acc in config["accounts"]:
        if acc["name"] == wanted:
            return acc
    return config["accounts"][0]


def save_user_session(context: BrowserContext, session_path: str) -> None:
    """Guarda el estado de la sesión para reutilizarla en ejecuciones futuras."""
    os.makedirs(os.path.dirname(session_path), exist_ok=True)
    context.storage_state(path=session_path)


def load_user_session(playwright, session_path: str, proxy: str | None):
    launch_args = {
        "headless": True,
        "args": [
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
        ],
    }
    if proxy:
        launch_args["proxy"] = {"server": proxy}

    browser = playwright.chromium.launch(**launch_args)

    context_kwargs = {"user_agent": UA, "viewport": {"width": 1366, "height": 768}}
    if os.path.exists(session_path):
        context_kwargs["storage_state"] = session_path

    context = browser.new_context(**context_kwargs)
    return browser, context


def _clickable_texts(page) -> list:
    """Textos visibles de todos los elementos clicables (para diagnóstico de UI)."""
    out = []
    try:
        for e in page.query_selector_all("button, [role='menuitem'], [role='button'], [role='option'], a"):
            try:
                t = (e.inner_text() or "").strip().replace("\n", " ")
                if t and len(t) < 70 and t not in out:
                    out.append(t)
            except Exception:
                pass
    except Exception:
        pass
    return out


def _debug_shot(page, tag: str) -> str:
    try:
        d = "/app/sessions/debug"
        os.makedirs(d, exist_ok=True)
        path = f"{d}/{tag}_{int(time.time())}.png"
        page.screenshot(path=path, full_page=False)
        return path
    except Exception:
        return ""


def generate_ai_share_link(prompt_content: str, account_name: str | None = None) -> dict:
    """Genera un enlace público share.google para una conversación de AI Mode."""
    config = load_config()
    account = get_account(config, account_name)
    proxy = config["proxy_url"] if config.get("use_corporate_proxy") else None
    delay = float(config.get("delay_between_actions", 1.5))
    max_retries = int(config.get("max_retries_per_link", 3))

    last_error = None
    for attempt in range(1, max_retries + 1):
        browser = None
        try:
            with sync_playwright() as p:
                browser, context = load_user_session(p, account["session_file"], proxy)
                try:
                    context.grant_permissions(["clipboard-read", "clipboard-write"], origin="https://www.google.com")
                except Exception:
                    pass
                page = context.new_page()

                # Captura de red: cualquier respuesta que contenga un enlace share.google
                captured: list = []

                def _on_response(resp):
                    try:
                        ct = (resp.headers or {}).get("content-type", "")
                        if "json" not in ct and "text" not in ct and "protobuf" not in ct:
                            return
                        body = resp.text()
                        if body and "share.google/" in body:
                            m = re.search(r"https://share\.google/[A-Za-z0-9_\-]+", body)
                            if m:
                                captured.append(m.group(0))
                    except Exception:
                        pass

                page.on("response", _on_response)

                page.goto(
                    "https://www.google.com/search?q=ai+mode&udm=50",
                    timeout=30000,
                )
                time.sleep(delay)

                # Acepta el banner de cookies si aparece
                try:
                    page.get_by_role("button", name="Accept all").click(timeout=4000)
                    time.sleep(delay)
                except Exception:
                    try:
                        page.get_by_role("button", name="Aceptar todo").click(timeout=3000)
                        time.sleep(delay)
                    except Exception:
                        pass

                # Verifica que exista sesión activa; si no, reporta que hay que crearla
                if page.get_by_role("button", name="Sign in").count() > 0 or "accounts.google.com" in page.url:
                    return {
                        "ok": False,
                        "error": "no_session",
                        "message": (
                            "No hay sesión activa de Google. Ejecuta el modo login "
                            "(headless=False) una vez para crearla."
                        ),
                        "account": account["name"],
                    }

                # Escribe la consulta en AI Mode
                input_box = page.locator(
                    "textarea[aria-label*='Pregunta'], textarea[aria-label*='Ask']"
                ).first
                input_box.fill(prompt_content)
                time.sleep(delay)
                input_box.press("Enter")
                time.sleep(delay * 4)  # espera la respuesta de AI Mode

                # Pulsa Compartir (estrategias múltiples)
                share_btn = None
                for strat in (
                    page.get_by_label("Compartir", exact=True),
                    page.get_by_label("Share", exact=True),
                    page.get_by_role("button", name=re.compile("compartir|share", re.I)),
                ):
                    try:
                        if strat.count() > 0:
                            share_btn = strat
                            break
                    except Exception:
                        continue
                if share_btn is None:
                    share_btn = page.get_by_label(re.compile("compartir|share", re.I))
                share_btn.first.click(timeout=10000)
                time.sleep(delay * 2)

                # La UI actual: botón "Copy link" copia el enlace al portapapeles
                share_link = ""
                clicked_copy = False
                for strat in (
                    page.get_by_role("button", name=re.compile(r"^copy link$|^copiar enlace$|^copiar link$", re.I)),
                    page.get_by_text(re.compile(r"^copy link$|^copiar enlace$|^copiar link$", re.I)),
                    page.get_by_role("button", name=re.compile("copy", re.I)),
                ):
                    try:
                        if strat.count() > 0:
                            strat.first.click(timeout=3000)
                            clicked_copy = True
                            break
                    except Exception:
                        continue

                if clicked_copy:
                    time.sleep(1.2)
                    try:
                        clip = page.evaluate("() => navigator.clipboard.readText()")
                        if clip and "share.google" in clip:
                            share_link = clip.strip()
                    except Exception:
                        pass

                # Fallback 1: enlace capturado del trafico de red
                if not share_link and captured:
                    share_link = captured[-1]

                # Fallback 2: polling de inputs (por si la UI vuelve a mostrar el input)
                if not share_link:
                    deadline = time.time() + 8
                    while time.time() < deadline and not share_link:
                        try:
                            for el in page.query_selector_all("input, textarea"):
                                try:
                                    v = (el.input_value() or el.get_attribute("value") or "").strip()
                                    if v and ("share.google" in v or "google.com/share" in v):
                                        share_link = v
                                        break
                                except Exception:
                                    continue
                        except Exception:
                            pass
                        if not share_link:
                            time.sleep(0.8)

                if not share_link:
                    input_vals = []
                    try:
                        for el in page.query_selector_all("input, textarea"):
                            try:
                                v = (el.input_value() or "").strip()
                                if v:
                                    input_vals.append(v[:120])
                            except Exception:
                                continue
                    except Exception:
                        pass
                    texts = _clickable_texts(page)
                    shot = _debug_shot(page, "modal")
                    return {
                        "ok": False,
                        "error": "modal_sin_enlace_share",
                        "input_values": input_vals[:10],
                        "ui_texts": texts,
                        "network_captured": captured[:5],
                        "screenshot": shot,
                        "content": prompt_content,
                    }

                save_user_session(context, account["session_file"])

                if "share.google" in share_link:
                    return {
                        "ok": True,
                        "share_url": share_link,
                        "content": prompt_content,
                        "account": account["name"],
                        "attempts": attempt,
                    }
                last_error = f"La respuesta no contenía un enlace share.google: {share_link[:120]}"

        except Exception as e:  # noqa: BLE001
            last_error = str(e)
            print(f"Intento {attempt} fallido: {last_error}")
            time.sleep(delay * 2)
        finally:
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass

    return {
        "ok": False,
        "error": f"No se pudo generar el enlace tras {max_retries} intentos",
        "detail": last_error,
        "content": prompt_content,
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Uso: python generate_share_link.py <contenido_de_la_consulta>")
        raise SystemExit(1)
    result = generate_ai_share_link(sys.argv[1])
    print(json.dumps(result, indent=2, ensure_ascii=False))
