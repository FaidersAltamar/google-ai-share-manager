"""Diagnostico v4: hoja de compartir (share sheet) -> opcion Google -> token bare.

    python /tmp/diag4.py [url]
"""
import sys, os, json, time, socket, threading, select, subprocess, urllib.request, re

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
API = "http://ai-share-manager:8000"
ADB = "/opt/platform-tools/platform-tools/adb"
LP = 19536
OUT = "/tmp/diag4"
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


def adb(*a, timeout=60):
    r = subprocess.run([ADB, "-s", f"127.0.0.1:{LP}", *a], capture_output=True, timeout=timeout)
    return (r.stdout + r.stderr).decode("utf-8", errors="ignore")


def ensure_dev(tries=8):
    for _ in range(tries):
        out = adb("devices")
        if "127.0.0.1" in out and "device" in out:
            return True
        adb("connect", f"127.0.0.1:{LP}")
        time.sleep(2)
    raise RuntimeError("dispositivo no disponible: " + adb("devices"))


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
        x1, y1, x2, y2 = map(int, bm.groups())
        out.append({"text": tm.group(1) if tm else "", "desc": dm.group(1) if dm else "",
                    "rid": rm.group(1) if rm else "", "pkg": (re.search(r'package="([^"]*)"', node) or [None, ""])[1] if re.search(r'package="([^"]*)"', node) else "",
                    "x": (x1 + x2) // 2, "y": (y1 + y2) // 2})
    return out


def dump(tag, limit=70):
    adb("shell", "uiautomator", "dump", "/sdcard/ui.xml", timeout=60)
    xml = adb("shell", "cat", "/sdcard/ui.xml", timeout=30)
    open(os.path.join(OUT, f"{tag}.xml"), "w", encoding="utf-8").write(xml)
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
        print(f"   {label!r} @({n['x']},{n['y']})" + (f"  id={rid}" if rid else "") + (f"  pkg={n['pkg'].split('.')[-1]}" if n["pkg"] else ""))
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
    os.makedirs(OUT, exist_ok=True)
    print("connect:", adb("connect", f"127.0.0.1:{LP}")); time.sleep(3)
    ensure_dev(); print("devices ok")

    print("\n>>> A: red desde el telefono")
    for u in ("https://scale.com.co", "https://example.com", "https://www.google.com"):
        code = adb("shell", "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-m", "15", u, timeout=30).strip()
        print(f"   {u} -> {code[:120]}")

    print("\n>>> B: abrir URL en Chrome")
    adb("shell", "input", "keyevent", "3"); time.sleep(2)
    adb("shell", "am", "start", "-n", "com.android.chrome/com.google.android.apps.chrome.IntentDispatcher",
        "-a", "android.intent.action.VIEW", "-d", url, timeout=40)
    time.sleep(14)
    xml = dump("A_chrome")

    print("\n>>> C: botón 'Compartir vínculo'")
    if not tap(xml, contains="Compartir vínculo"):
        tap(xml, desc="Compartir vínculo")
    time.sleep(5)
    xml = dump("B_share_sheet")

    print("\n>>> D: hoja - buscar apps de Google")
    for cand in ("Google", "Gmail", "Documentos", "Drive", "Google Docs", "Acortar", "acortar"):
        if tap(xml, contains=cand):
            time.sleep(6)
            xml = dump("C_tras_" + cand.replace(" ", "_"))
            break
    else:
        print("   (no se encontro opcion Google en la hoja)")

    print("\n>>> E: clipboard")
    print("   ", adb("shell", "service", "call", "clipboard", "1", timeout=30)[:500].replace("\n", " | "))

    print("\n>>> F: pegar en la app Google y leer el token")
    adb("shell", "input", "keyevent", "3"); time.sleep(2)
    adb("shell", "monkey", "-p", GAPP, "-c", "android.intent.category.LAUNCHER", "1", timeout=40)
    time.sleep(6)
    xml = dump("D_google")
    for lbl in ("NO PERMITIR", "No permitir"):
        if tap(xml, text=lbl):
            time.sleep(3)
            xml = dump("D2_google")
            break
    # campo de busqueda real
    if tap(xml, rid="com.google.android.googlequicksearchbox:id/googleapp_srp_search_box_text"):
        time.sleep(3)
    elif tap(xml, contains="Búsqueda"):
        time.sleep(3)
    else:
        print("   !! no encontre campo de busqueda")
    adb("shell", "input", "keyevent", "279")
    time.sleep(3)
    adb("shell", "input", "keyevent", "111")
    time.sleep(2)
    xml = dump("E_pegado")
    toks = re.findall(r"https://share\.google/[A-Za-z0-9_\-]+", xml)
    print("\n>>> TOKENS:", toks)
    if not toks:
        # buscar en el xml completo (puede estar partido por el dump)
        raw = open(os.path.join(OUT, "E_pegado.xml"), encoding="utf-8").read()
        print(">>> share.google en xml crudo:", re.findall(r"share\.google.{0,60}", raw)[:5])


if __name__ == "__main__":
    main()
