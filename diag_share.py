"""Diagnostico v13: flujo de acuñacion del token bare en el FoxPhone.

Secuencia: abrir URL -> 'Compartir vinculo' -> hoja -> opcion Google/acortar
-> copiar -> pegar en la app Google para leer el token del portapapeles.

    python /tmp/diag_share.py [url]
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
        tm = re.search(r'text="([^"]*)"', node)
        dm = re.search(r'content-desc="([^"]*)"', node)
        rm = re.search(r'resource-id="([^"]*)"', node)
        pm = re.search(r'package="([^"]*)"', node)
        x1, y1, x2, y2 = map(int, bm.groups())
        out.append({"text": tm.group(1) if tm else "", "desc": dm.group(1) if dm else "",
                    "rid": rm.group(1) if rm else "", "pkg": pm.group(1) if pm else "",
                    "x": (x1 + x2) // 2, "y": (y1 + y2) // 2})
    return out


def dump(tag, limit=70):
    adb("shell", "uiautomator", "dump", "/sdcard/ui.xml", timeout=60)
    xml = adb("shell", "cat", "/sdcard/ui.xml", timeout=30)
    print(f"\n=== {tag} ({len(xml)}B) ===")
    seen = set()
    for n in nodes(xml):
        label = (n["text"] or n["desc"]).strip()
        if not label:
            continue
        key = (label, n["x"], n["y"])
        if key in seen:
            continue
        seen.add(key)
        rid = n["rid"].split("/")[-1] if n["rid"] else ""
        pk = n["pkg"].split(".")[-1] if n["pkg"] else ""
        print(f"   {label!r} @({n['x']},{n['y']})" + (f" [{rid}]" if rid else "") + (f" <{pk}>" if pk else ""))
        if len(seen) >= limit:
            break
    return xml


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
        print(f"   !! no match text={text} desc={desc} rid={rid} contains={contains} pkg={pkg}")
        return False
    n = hits[index]
    print(f"   -> tap {(n['text'] or n['desc'] or n['rid'])!r} @({n['x']},{n['y']})")
    adb("shell", "input", "tap", str(n["x"]), str(n["y"]))
    return True


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "https://scale.com.co/"
    print("connect:", adb("connect", f"127.0.0.1:{LP}")); time.sleep(3)
    ensure_dev(); print("devices OK\n")

    print("=== 0. asegurar red (limpiar NAT muerta) ===")
    adb("shell", "iptables", "-t", "nat", "-F", "VOLC_PROXY_NAT_CHAIN")
    print("   https google ->", adb("shell", "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                                   "-m", "12", "https://www.google.com/").strip()[:20])

    print("\n=== 1. abrir URL en Chrome ===")
    adb("shell", "am", "force-stop", "com.android.chrome")
    time.sleep(2)
    print(adb("shell", "am", "start", "-n", "com.android.chrome/com.google.android.apps.chrome.IntentDispatcher",
              "-a", "android.intent.action.VIEW", "-d", url)[:200])
    time.sleep(16)
    xml = dump("01_chrome")

    print("\n=== 2. 'Compartir vinculo' ===")
    if not tap(xml, contains="Compartir"):
        tap(xml, desc="Compartir")
    time.sleep(6)
    xml = dump("02_hoja")

    print("\n=== 3. opcion de Google / acortar en la hoja ===")
    chosen = None
    for cand in ("Acortar", "acortar", "Google", "Gmail", "Documentos", "Drive", "Copiar", "Copiar enlace"):
        if tap(xml, contains=cand):
            chosen = cand
            break
    time.sleep(7)
    xml = dump("03_tras_" + (chosen or "nada").replace(" ", "_"))

    print("\n=== 4. clipboard ===")
    print("   ", adb("shell", "service", "call", "clipboard", "1")[:400].replace("\n", " | "))

    print("\n=== 5. app Google: pegar para leer el token ===")
    adb("shell", "input", "keyevent", "3"); time.sleep(2)
    adb("shell", "am", "force-stop", GAPP)
    time.sleep(1)
    adb("shell", "monkey", "-p", GAPP, "-c", "android.intent.category.LAUNCHER", "1", timeout=40)
    time.sleep(7)
    xml = dump("04_google")
    for lbl in ("NO PERMITIR", "No permitir"):
        if tap(xml, text=lbl):
            time.sleep(4)
            xml = dump("04b_google")
            break
    if tap(xml, rid=GAPP + ":id/googleapp_srp_search_box_text"):
        time.sleep(3)
    elif tap(xml, contains="Búsqueda"):
        time.sleep(3)
    else:
        print("   !! sin campo de busqueda")
    adb("shell", "input", "keyevent", "279")
    time.sleep(3)
    adb("shell", "input", "keyevent", "111")
    time.sleep(2)
    xml = dump("05_pegado")
    toks = re.findall(r"https://share\.google/[A-Za-z0-9_\-]+", xml)
    print("\n>>> TOKENS:", toks)
    if not toks:
        print(">>> texto del campo:")
        for n in nodes(xml):
            if n["rid"] and "search" in n["rid"].lower():
                print("    ", n["rid"], repr(n["text"]), repr(n["desc"]))


if __name__ == "__main__":
    main()
