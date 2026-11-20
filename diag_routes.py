"""Diagnostico v16: encontrar la ruta que genera share.google?q=TOKEN.

Rutas probadas:
  A) Chrome -> Compartir... -> Mas -> Google
  B) App Google -> buscar URL -> compartir/acortar
  C) App Google -> resultado -> menu 3 puntos -> acortar
  D) Chrome -> copiar vinculo -> leer (control: URL cruda)

    python /tmp/diag_routes.py [url]
"""
import sys, os, json, time, socket, threading, select, subprocess, urllib.request, re

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
API = os.environ.get("VPS_API", "http://ai-share-manager:8000")
ADB = "/opt/platform-tools/platform-tools/adb"
LP = int(os.environ.get("DIAG_PORT", "19536"))
GAPP = "com.google.android.googlequicksearchbox"

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


def adb(*a, timeout=20):
    try:
        r = subprocess.run([ADB, "-s", f"127.0.0.1:{LP}", *a], capture_output=True, timeout=timeout)
        return (r.stdout + r.stderr).decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return "<TIMEOUT>"


def ensure_dev(tries=10):
    for _ in range(tries):
        out = adb("devices")
        if "127.0.0.1" in out and "\tdevice" in out:
            return True
        adb("disconnect", f"127.0.0.1:{LP}")
        adb("connect", f"127.0.0.1:{LP}")
        time.sleep(3)
    raise RuntimeError("sin dispositivo")


NODE_RE = re.compile(r'<node[^>]*?>', re.I)


def nodes(xml):
    out = []
    for m in NODE_RE.finditer(xml):
        node = m.group(0)
        bm = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node)
        if not bm:
            continue
        g = lambda p: (re.search(p, node).group(1) if re.search(p, node) else "")
        x1, y1, x2, y2 = map(int, bm.groups())
        out.append({"text": g(r'text="([^"]*)"'), "desc": g(r'content-desc="([^"]*)"'),
                    "rid": g(r'resource-id="([^"]*)"'), "pkg": g(r'package="([^"]*)"'),
                    "x": (x1 + x2) // 2, "y": (y1 + y2) // 2})
    return out


def dump(tag, limit=45):
    adb("shell", "uiautomator", "dump", "/sdcard/ui.xml", timeout=60)
    xml = adb("shell", "cat", "/sdcard/ui.xml", timeout=30)
    print(f"\n=== {tag} ({len(xml)}B) ===")
    seen = set()
    for n in nodes(xml):
        label = (n["text"] or n["desc"]).strip()
        if not label:
            continue
        key = (label, n["x"], n["y"], n["rid"])
        if key in seen:
            continue
        seen.add(key)
        rid = n["rid"].split("/")[-1] if n["rid"] else ""
        pk = n["pkg"].split(".")[-1] if n["pkg"] else ""
        print(f"   {label!r} @({n['x']},{n['y']})" + (f" [{rid}]" if rid else "") + (f" <{pk}>" if pk else ""))
        if len(seen) >= limit:
            break
    return xml


def clear_overlays():
    """Cierra el dialogo de permiso de microfono si esta ahi."""
    adb("shell", "uiautomator", "dump", "/sdcard/ui2.xml", timeout=50)
    xml = adb("shell", "cat", "/sdcard/ui2.xml", timeout=25)
    for n in nodes(xml):
        if n["text"].strip().lower() in ("no permitir", "cancelar", "solo esta vez"):
            if "permission" in n["rid"] or n["pkg"] == "permissioncontroller":
                print(f"   (cerrando dialogo: {n['text']!r})")
                adb("shell", "input", "tap", str(n["x"]), str(n["y"]))
                time.sleep(3)
                return True
    return False


def tap(xml, *, text=None, desc=None, rid=None, contains=None, pkg=None, index=0):
    hits = []
    for n in nodes(xml):
        if pkg and pkg not in n["pkg"]:
            continue
        if text is not None and n["text"].strip().lower() == text.lower():
            hits.append(n)
        elif desc is not None and n["desc"].strip().lower() == desc.lower():
            hits.append(n)
        elif rid is not None and n["rid"] == rid:
            hits.append(n)
        elif contains is not None and (contains.lower() in n["text"].lower() or contains.lower() in n["desc"].lower()):
            hits.append(n)
    if not hits:
        print(f"   !! no match text={text} desc={desc} rid={rid} contains={contains}")
        return False
    n = hits[index]
    print(f"   -> tap {(n['text'] or n['desc'] or n['rid'])!r} @({n['x']},{n['y']})")
    adb("shell", "input", "tap", str(n["x"]), str(n["y"]))
    return True


def leer_clipboard(tag):
    """Pega en el campo de busqueda de la app Google y lee el texto."""
    adb("shell", "input", "keyevent", "3"); time.sleep(2)
    adb("shell", "am", "force-stop", GAPP); time.sleep(1)
    adb("shell", "monkey", "-p", GAPP, "-c", "android.intent.category.LAUNCHER", "1", timeout=40)
    time.sleep(7)
    clear_overlays()
    xml = dump(f"{tag}_google", limit=18)
    ok = tap(xml, rid=GAPP + ":id/googleapp_srp_search_box_text")
    if not ok:
        ok = tap(xml, rid=GAPP + ":id/googleapp_search_box")
    if not ok:
        for n in nodes(xml):
            if n["rid"] and "search_box" in n["rid"]:
                print(f"   -> tap rid={n['rid']} @({n['x']},{n['y']})")
                adb("shell", "input", "tap", str(n["x"]), str(n["y"]))
                ok = True
                break
    if not ok:
        ok = tap(xml, contains="Buscar")
    time.sleep(3)
    adb("shell", "input", "keyevent", "279")
    time.sleep(3)
    adb("shell", "input", "keyevent", "111")
    time.sleep(2)
    xml = dump(f"{tag}_pegado", limit=25)
    toks = re.findall(r"https://share\.google/[A-Za-z0-9_\-]+", xml)
    campo = [n["text"] for n in nodes(xml) if n["text"].strip() and n["rid"] and "search" in n["rid"]]
    return toks, campo


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "https://scale.com.co/"
    print("connect:", adb("connect", f"127.0.0.1:{LP}")); time.sleep(3)
    ensure_dev(); print("devices OK\n")
    adb("shell", "iptables", "-t", "nat", "-F", "VOLC_PROXY_NAT_CHAIN")
    clear_overlays()

    # ---------- RUTA A: Chrome -> Compartir -> Mas -> Google ----------
    print("\n########## RUTA A: Chrome -> Compartir... -> Mas -> Google ##########")
    adb("shell", "am", "force-stop", "com.android.chrome"); time.sleep(3)
    adb("shell", "am", "start", "-n", "com.android.chrome/com.google.android.apps.chrome.IntentDispatcher",
        "-a", "android.intent.action.VIEW", "-d", url)
    time.sleep(18)
    clear_overlays()
    xml = dump("A_chrome", limit=12)
    tap(xml, rid="com.android.chrome:id/menu_button"); time.sleep(4)
    clear_overlays()
    xml = dump("A_menu", limit=30)
    tap(xml, contains="Compartir"); time.sleep(6)
    clear_overlays()
    xml = dump("A_hoja", limit=25)
    tap(xml, text="Más"); time.sleep(7)
    clear_overlays()
    xml = dump("A_sistema", limit=45)
    tap(xml, text="Google", pkg="android"); time.sleep(9)
    clear_overlays()
    xml = dump("A_tras_google", limit=40)
    toks = re.findall(r"https://share\.google/[A-Za-z0-9_\-]+", xml)
    print("   TOKENS en pantalla:", toks)

    print("\n########## RUTA B: app Google -> buscar URL -> compartir ##########")
    adb("shell", "input", "keyevent", "3"); time.sleep(2)
    adb("shell", "am", "force-stop", GAPP); time.sleep(1)
    adb("shell", "monkey", "-p", GAPP, "-c", "android.intent.category.LAUNCHER", "1", timeout=40)
    time.sleep(8)
    clear_overlays()
    xml = dump("B_home", limit=20)
    ok = tap(xml, rid=GAPP + ":id/googleapp_srp_search_box_text")
    if not ok:
        ok = tap(xml, contains="Buscar")
    time.sleep(3)
    adb("shell", "input", "text", url.replace(":", "%s").replace("/", "%s"))
    time.sleep(2)
    adb("shell", "input", "keyevent", "66")
    time.sleep(10)
    clear_overlays()
    xml = dump("B_resultados", limit=35)
    # buscar acciones de compartir/acortar en la pagina de resultados
    for cand in ("Compartir", "Acortar", "acortar", "Más opciones", "⋮"):
        if tap(xml, contains=cand):
            time.sleep(5)
            clear_overlays()
            xml = dump("B_menu", limit=35)
            break

    print("\n########## RUTA D: control - 'Copiar vinculo' en Chrome ##########")
    adb("shell", "am", "force-stop", "com.android.chrome"); time.sleep(3)
    adb("shell", "am", "start", "-n", "com.android.chrome/com.google.android.apps.chrome.IntentDispatcher",
        "-a", "android.intent.action.VIEW", "-d", url)
    time.sleep(18)
    clear_overlays()
    xml = dump("D_chrome", limit=12)
    tap(xml, rid="com.android.chrome:id/menu_button"); time.sleep(4)
    clear_overlays()
    xml = dump("D_menu", limit=30)
    tap(xml, contains="Compartir"); time.sleep(6)
    clear_overlays()
    xml = dump("D_hoja", limit=25)
    tap(xml, text="Copiar vínculo"); time.sleep(4)
    toks, campo = leer_clipboard("D")
    print("\n   >>> TOKENS:", toks)
    print("   >>> campo de busqueda:", campo)


if __name__ == "__main__":
    main()
