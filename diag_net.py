"""Diagnostico standalone de red del telefono FoxPhone.

Se ejecuta en un contenedor efimero (con el worker detenido) para no competir
por la sesion SSH/ADB del telefono.

    python /tmp/diag_net.py
"""
import sys, os, json, time, socket, threading, select, subprocess, urllib.request, re

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
API = os.environ.get("VPS_API", "http://ai-share-manager:8000")
ADB = "/opt/platform-tools/platform-tools/adb"
LP = int(os.environ.get("DIAG_PORT", "19536"))

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


def adb(*a, timeout=18):
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
    raise RuntimeError("sin dispositivo: " + adb("devices"))


print("connect:", adb("connect", f"127.0.0.1:{LP}")); time.sleep(3)
ensure_dev(); print("devices OK\n")

print("=== 1. curl -v https (punto de fallo exacto) ===")
print(adb("shell", "curl", "-v", "-o", "/dev/null", "-m", "10", "https://www.google.com")[:1800])

print("\n=== 2. curl -v http puerto 80 ===")
print(adb("shell", "curl", "-v", "-o", "/dev/null", "-m", "10", "http://neverssl.com")[:1500])

print("\n=== 3. curl -v con IP directa (sin DNS) ===")
print(adb("shell", "curl", "-v", "-o", "/dev/null", "-m", "10", "http://142.251.153.119/")[:1200])

print("\n=== 4. proxies configurados ===")
for k in ("http_proxy", "global_http_proxy_host", "global_http_proxy_port",
          "proxy_pac_url", "captive_portal_mode", "wifi_watchdog_poor_network_test_enabled"):
    print(f"   {k} = {adb('shell','settings','get','global',k).strip()[:120]!r}")

print("\n=== 5. props de red ===")
out = adb("shell", "getprop")
for line in out.splitlines():
    if any(k in line.lower() for k in ("proxy", "gsm.sim", "wifi.interface", "dhcp",
                                       "net.hostname", "qemu", "build.version")):
        print("   ", line.strip()[:200])

print("\n=== 6. MTU ===")
print("   ", adb("shell", "ip", "link", "show", "wlan0").strip()[:300])
for sz in (1200, 1400):
    r = adb("shell", "ping", "-c", "1", "-W", "2", "-s", str(sz), "142.251.153.119", timeout=14)
    print(f"   ping -s {sz}: {'OK' if 'bytes from' in r else 'FAIL'}")

print("\n=== 7. gateway y ARP ===")
print("   ping gw 10.24.4.1:", "OK" if "bytes from" in adb("shell", "ping", "-c", "1", "-W", "2", "10.24.4.1", timeout=12) else "FAIL")
print("   ip neigh:", adb("shell", "ip", "neigh", timeout=12).strip()[:400])

print("\n=== 8. chrome: probar con http (no https) ===")
adb("shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", "http://neverssl.com", timeout=25)
time.sleep(10)
adb("shell", "uiautomator", "dump", "/sdcard/ui.xml", timeout=40)
xml = adb("shell", "cat", "/sdcard/ui.xml", timeout=25)
for m in re.finditer(r'text="([^"]{4,80})"', xml):
    print("   ", m.group(1))
