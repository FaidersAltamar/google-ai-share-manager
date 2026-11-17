"""Genera enlaces share.google "bare" (proxy-render estilo google.com/share.google?q=TOKEN)
automatizando la app oficial de Google en un emulador Android via ADB.

Requisitos (en este PC):
  1. Emulador Android con Play Store (LDPlayer recomendado; tambien sirve Android Studio AVD
     con imagen "Google Play") y sesion iniciada con tu cuenta Google.
  2. ADB accesible en PATH o configurar ADB_PATH abajo.
     - LDPlayer: habilita "ADB" en ajustes; adb viene en el directorio de LDPlayer.
     - AVD: platform-tools de Android SDK.
  3. `pip install pure-python-adb` NO es necesario: usamos el binario adb directo.

Uso:
  python generar_linkcard.py https://www.youtube.com/watch?v=XXXX

Modo exploracion: guarda capturas UI (dumps + screenshots) en debug_adb/ tras cada paso,
para ajustar los taps exactos de tu emulador en la primera corrida.
"""
import os
import re
import subprocess
import sys
import time

ADB = os.environ.get("ADB_PATH", "adb")
DEBUG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_adb")


def sh(*args, timeout=30, binary=False):
    r = subprocess.run([ADB, *args], capture_output=True, timeout=timeout)
    return r.stdout if binary else (r.stdout.decode("utf-8", errors="ignore") + r.stderr.decode("utf-8", errors="ignore"))


def device_ready() -> bool:
    out = subprocess.run([ADB, "devices"], capture_output=True, text=True).stdout
    lines = [l for l in out.splitlines() if "\tdevice" in l]
    return bool(lines)


def ui_dump(tag: str) -> str:
    sh("shell", "uiautomator", "dump", "/sdcard/ui.xml", timeout=25)
    xml = sh("shell", "cat", "/sdcard/ui.xml", timeout=15)
    os.makedirs(DEBUG_DIR, exist_ok=True)
    with open(os.path.join(DEBUG_DIR, f"{tag}.xml"), "w", encoding="utf-8") as f:
        f.write(xml)
    return xml


def screenshot(tag: str) -> str:
    os.makedirs(DEBUG_DIR, exist_ok=True)
    path = os.path.join(DEBUG_DIR, f"{tag}.png")
    with open(path, "wb") as f:
        f.write(sh("exec-out", "screencap", "-p", timeout=25, binary=True))
    return path


def tap_text(xml: str, patterns) -> bool:
    """Toca el primer nodo cuyo text/content-desc coincida con alguno de los patrones."""
    for pat in patterns:
        m = re.search(
            rf'(?:text|content-desc)="[^"]*{pat}[^"]*"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
            xml, re.IGNORECASE,
        )
        if not m:
            # reintentar con orden invertido (bounds antes que text)
            m = re.search(
                rf'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*(?:text|content-desc)="[^"]*{pat}[^"]*"',
                xml, re.IGNORECASE,
            )
        if m:
            x1, y1, x2, y2 = map(int, m.groups())
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            sh("shell", "input", "tap", str(cx), str(cy))
            print(f"    tap ({cx},{cy}) sobre '{pat}'")
            return True
    return False


def generar_linkcard(url: str) -> str:
    if not device_ready():
        print("❌ No hay dispositivo ADB conectado. Abre el emulador y verifica `adb devices`.")
        sys.exit(1)
    print("✅ Emulador conectado")

    # 1. Envia la URL al share sheet de Android
    sh("shell", "am", "start", "-a", "android.intent.action.SEND",
       "-t", "text/plain", "--es", "android.intent.extra.TEXT", url, timeout=25)
    time.sleep(3)
    xml = ui_dump("01_chooser")
    screenshot("01_chooser")

    # 2. Toca el target "Google" (la app de Google) en el chooser/sheet
    if not tap_text(xml, [r"^Google$", r"^Google\b"]):
        print("❌ No encontre el target 'Google' en el share sheet. Mira debug_adb/01_chooser.png")
        sys.exit(2)

    # 3. Espera a que la app procese y muestre el enlace
    time.sleep(6)
    xml2 = ui_dump("02_after_google")
    screenshot("02_after_google")

    # 4. Busca el enlace en la UI (dialog/sheet)
    m = re.search(r"https://share\.google/[A-Za-z0-9_\-]+|https://www\.google\.com/share\.google\?q=[A-Za-z0-9_\-]+", xml2)
    if not m:
        # puede requerir un tap adicional (ej. boton de copiar)
        if tap_text(xml2, [r"copiar", r"copy", r"compartir", r"share"]):
            time.sleep(3)
            xml2 = ui_dump("03_after_copy")
            screenshot("03_after_copy")
            m = re.search(r"https://share\.google/[A-Za-z0-9_\-]+", xml2)

    if m:
        token = m.group(0)
        if token.startswith("https://share.google/"):
            token = token.split("/", 3)[-1]
        else:
            token = token.split("q=", 1)[-1]
        print(f"\n✅ TOKEN: {token}")
        print(f"✅ LINK:  https://www.google.com/share.google?q={token}")
        return token
    print("❌ No vi el enlace en la UI. Revisa debug_adb/02_after_google.png y 02_after_google.xml")
    sys.exit(3)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python generar_linkcard.py <url_destino>")
        sys.exit(1)
    generar_linkcard(sys.argv[1])
