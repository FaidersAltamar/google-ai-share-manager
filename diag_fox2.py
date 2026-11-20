"""Diagnostico v2: flujo real con Chrome + taps por texto/content-desc.

Objetivo: descubrir la secuencia exacta que produce el token bare
(share.google?q=TOKEN) en este FoxPhone 1080x1920.

    python /tmp/diag2.py <url>
"""
import sys, os, json, time, socket, threading, select, subprocess, urllib.request, re

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
API = "http://ai-share-manager:8000"
ADB = "/opt/platform-tools/platform-tools/adb"
LP = 19536
OUT = "/tmp/diag2"

ssh = json.loads(urllib.request.urlopen(API + "/adb-creds", timeout=15).read().decode())
import paramiko
tr = paramiko.Transport((ssh["host"], ssh["port"]))
tr.connect(username=ssh["user"], password=ssh["pass"])
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", LP)); srv.listen(10)


def handle(cs):
    try:
        ch = tr.open_channel("direct-tcpip", (ssh["rhost"], ssh["rport"]), cs.getpeername())
    except Exception:
        cs.close(); return
    try:
        while True:
            r, _, _ = select.select([cs, ch], [], [], 60)
            if cs in r:
                d = cs.recv(4096)
                if not d: break
                ch.sendall(d)
            if ch in r:
                d = ch.recv(4096)
                if not d: break
                cs.sendall(d)
    except Exception:
        pass
    cs.close()


threading.Thread(target=lambda: [handle(c) for c, _ in iter(srv.accept, None)], daemon=True).start()
time.sleep(1)


def adb(*a, timeout=60):
    r = subprocess.run([ADB, "-s", f"127.0.0.1:{LP}", *a], capture_output=True, timeout=timeout)
    return (r.stdout + r.stderr).decode("utf-8", errors="ignore")


def dump(tag):
    adb("shell", "uiautomator", "dump", "/sdcard/ui.xml", timeout=50)
    xml = adb("shell", "cat", "/sdcard/ui.xml", timeout=30)
    open(os.path.join(OUT, f"{tag}.xml"), "w", encoding="utf-8").write(xml)
    nodes = []
    for m in re.finditer(
        r'<node[^>]*?(?:text|content-desc)="([^"]+)"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
        xml, re.I):
        label = m.group(1)
        if label.strip():
            x1, y1, x2, y2 = map(int, m.groups()[1:])
            nodes.append((label, (x1 + x2) // 2, (y1 + y2) // 2))
    # dedup conservando orden
    seen, uniq = set(), []
    for n in nodes:
        if n[0] not in seen:
            seen.add(n[0]); uniq.append(n)
    print(f"\n=== {tag} ({len(xml)}B) ===")
    for label, x, y in uniq[:45]:
        print(f"   {label!r} @({x},{y})")
    return xml


def tap_label(xml, *needles, exact=False):
    """Toca el primer nodo cuyo text o content-desc matchea."""
    for m in re.finditer(
        r'<node[^>]*?(?:text|content-desc)="([^"]*)"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
        xml, re.I):
        label = m.group(1)
        if not label.strip():
            continue
        hit = (label.strip().lower() == needles[0].strip().lower()) if exact \
            else any(n.lower() in label.lower() for n in needles)
        if hit:
            x1, y1, x2, y2 = map(int, m.groups()[1:])
            x, y = (x1 + x2) // 2, (y1 + y2) // 2
            print(f"   -> tap {label!r} @({x},{y})")
            adb("shell", "input", "tap", str(x), str(y))
            return label
    print(f"   !! no match para {needles}")
    return None


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.youtube.com/watch?v=4bfeCGHw8ZI"
    os.makedirs(OUT, exist_ok=True)
    subprocess.run([ADB, "kill-server"], capture_output=True); time.sleep(2)
    print("connect:", adb("connect", f"127.0.0.1:{LP}")); time.sleep(3)

    # 1. abrir la URL en Chrome
    print("\n>>> 1: abrir URL en Chrome")
    print(adb("shell", "am", "start", "-n", "com.android.chrome/com.google.android.apps.chrome.IntentDispatcher",
              "-a", "android.intent.action.VIEW", "-d", url, timeout=40)[:200])
    time.sleep(14)
    xml = dump("01_chrome")

    # 2. abrir el menu de compartir
    print("\n>>> 2: compartir")
    tap_label(xml, "compartir", "share", "More options", "Más opciones")
    time.sleep(4)
    xml = dump("02_menu")

    # 3. hoja de compartir: buscar la opcion de Google / acortar
    print("\n>>> 3: hoja compartir - busco Google/acortar/copiar")
    tap_label(xml, "Google", "acortar", "Acortar enlaces", "copiar", "Copy link", "Copiar enlace")
    time.sleep(6)
    xml = dump("03_tras_google")

    # 4. estado del portapapeles
    print("\n>>> 4: clipboard")
    print("   service call:", adb("shell", "service", "call", "clipboard", "1", timeout=30)[:300])

    # 5. pegar en el campo de busqueda de la app Google
    print("\n>>> 5: app Google + pegar")
    adb("shell", "input", "keyevent", "3"); time.sleep(2)
    adb("shell", "monkey", "-p", "com.google.android.googlequicksearchbox",
        "-c", "android.intent.category.LAUNCHER", "1", timeout=40)
    time.sleep(5)
    xml = dump("04_google")
    tapped = tap_label(xml, "Buscar", "Search")
    time.sleep(2)
    if tapped:
        adb("shell", "input", "keyevent", "279")
        time.sleep(3)
        xml = dump("05_pasted")
        toks = re.findall(r"https://share\.google/[A-Za-z0-9_\-]+", xml)
        print("\n>>> TOKENS ENCONTRADOS:", toks)
    else:
        print("   !! no hay campo Buscar visible")

    print("\n>>> XMLs guardados en", OUT)


if __name__ == "__main__":
    main()
