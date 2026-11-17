"""Automatización del Google App en redroid (Android del VPS) via adb para acuñar
tokens BARE (link cards) con el flujo oficial de compartir de la app.
"""
import os
import re
import subprocess
import time

ADB_HOST = os.environ.get("ADB_HOST", "redroid:5555")
ADB = "adb"


def _sh(*args, timeout=30, binary=False):
    r = subprocess.run([ADB, *args], capture_output=True, timeout=timeout)
    return r.stdout if binary else r.stdout.decode("utf-8", errors="ignore") + r.stderr.decode("utf-8", errors="ignore")


def conectado() -> bool:
    try:
        _sh("connect", ADB_HOST, timeout=10)
        out = subprocess.run([ADB, "devices"], capture_output=True, text=True, timeout=10).stdout
        return any(ADB_HOST.split(":")[0] in l and "device" in l for l in out.splitlines())
    except Exception:
        return False


def boot_completado() -> bool:
    try:
        return _sh("-s", ADB_HOST, "shell", "getprop", "sys.boot_completed").strip() == "1"
    except Exception:
        return False


def diagnostico() -> dict:
    if not conectado():
        return {"adb": False, "error": "no_conectado_a_redroid"}
    boot = boot_completado()
    pkgs = _sh("-s", ADB_HOST, "shell", "pm", "list", "packages", timeout=40)
    google_app = "googlequicksearchbox" in pkgs
    gms = "com.google.android.gms" in pkgs
    accounts = _sh("-s", ADB_HOST, "shell", "dumpsys", "account", timeout=40)
    cuenta_google = bool(re.search(r"Account \{name=[^}]*gmail[^}]*\}|Account \{name=[^}]*@gmail", accounts, re.I))
    return {
        "adb": True,
        "boot": boot,
        "google_app_instalada": google_app,
        "play_services": gms,
        "cuenta_google_logueada": cuenta_google,
    }


def _ui_dump(tag: str) -> str:
    _sh("-s", ADB_HOST, "shell", "uiautomator", "dump", "/sdcard/ui.xml", timeout=30)
    xml = _sh("-s", ADB_HOST, "shell", "cat", "/sdcard/ui.xml", timeout=15)
    d = "/app/sessions/debug"
    os.makedirs(d, exist_ok=True)
    try:
        open(os.path.join(d, f"adb_{tag}.xml"), "w", encoding="utf-8").write(xml)
    except Exception:
        pass
    return xml


def _tap_text(xml: str, patterns) -> bool:
    for pat in patterns:
        m = re.search(
            rf'(?:text|content-desc)="[^"]*{pat}[^"]*"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
            xml, re.IGNORECASE,
        )
        if not m:
            m = re.search(
                rf'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*?(?:text|content-desc)="[^"]*{pat}[^"]*"',
                xml, re.IGNORECASE,
            )
        if m:
            x1, y1, x2, y2 = map(int, m.groups())
            sh_tap = [ADB, "-s", ADB_HOST, "shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2)]
            subprocess.run(sh_tap, capture_output=True, timeout=15)
            return True
    return False


def generar_linkcard(url: str, timeout_total: int = 120) -> dict:
    """Comparte la URL hacia la Google App en redroid y extrae el token bare."""
    if not conectado():
        _sh("connect", ADB_HOST, timeout=10)
        time.sleep(2)
    if not boot_completado():
        deadline = time.time() + 90
        while time.time() < deadline and not boot_completado():
            time.sleep(3)
        if not boot_completado():
            return {"ok": False, "error": "android_boot_incompleto"}

    t0 = time.time()
    # 1. share sheet de Android con la URL
    _sh("-s", ADB_HOST, "shell", "am", "start", "-a", "android.intent.action.SEND",
        "-t", "text/plain", "--es", "android.intent.extra.TEXT", url, timeout=25)
    time.sleep(3)

    xml = _ui_dump("01_chooser")
    if not _tap_text(xml, [r"^Google$", r"^Google\b", r"googlequicksearchbox"]):
        _sh("-s", ADB_HOST, "shell", "input", "keyevent", "KEYCODE_BACK")
        return {
            "ok": False,
            "error": "no_target_google_en_share_sheet",
            "hint": "¿La app de Google está instalada y con cuenta? Ver /android/status",
        }

    # 2. espera y lee la card
    time.sleep(8)
    xml2 = _ui_dump("02_card")
    m = re.search(r"https://share\.google/[A-Za-z0-9_\-]+|https://www\.google\.com/share\.google\?q=[A-Za-z0-9_\-/]+", xml2)
    if not m and _tap_text(xml2, [r"copiar", r"copy", r"compartir", r"share", r"crear enlace", r"create link"]):
        time.sleep(4)
        xml2 = _ui_dump("03_after_copy")
        m = re.search(r"https://share\.google/[A-Za-z0-9_\-]+", xml2)

    if m:
        token = m.group(0)
        token = token.split("share.google/", 1)[-1] if "share.google/" in token else token.split("q=", 1)[-1]
        return {
            "ok": True,
            "share_url": f"https://www.google.com/share.google?q={token}",
            "token": token,
            "destination": url,
            "provider": "android_vps",
            "elapsed_s": round(time.time() - t0, 1),
        }

    _sh("-s", ADB_HOST, "shell", "input", "keyevent", "KEYCODE_BACK")
    return {"ok": False, "error": "token_no_visible_en_ui", "hint": "Ver /app/sessions/debug/adb_*.xml"}
