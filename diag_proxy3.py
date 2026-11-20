"""Diagnostico v10: matriz de credenciales del proxy + camino de datos moviles.

    python /tmp/diag_proxy3.py
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


print("connect:", adb("connect", f"127.0.0.1:{LP}")); time.sleep(3)
ensure_dev(); print("devices OK\n")

PROXY_HOST = "proxy.naproxy.net"
PROXY_PORT = "1000"
PASSWORD = "KJiASPufi1MidDOS"
PID = "api-lyqlunpisb8b"

print("=== 1. matriz de credenciales SOCKS5 (desde el telefono) ===")
users = ["", PID, "api", "naproxy", "byteproxy", "volc", "admin"]
for u in users:
    for p in (PASSWORD, "", "naproxy"):
        r = adb("shell", "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                "--socks5-hostname", f"{PROXY_HOST}:{PROXY_PORT}",
                "--proxy-user", f"{u}:{p}", "-m", "12", "https://www.google.com/")
        code = r.strip()[:40]
        if code and code != "000":
            print(f"   *** OK user={u!r} pass={p!r} -> {code}")
        else:
            print(f"      user={u!r} pass={p!r} -> {code}")

print("\n=== 2. proxy HTTP con usuario:PASS (distintos hosts SOCKS) ===")
for host in ("proxy.naproxy.net", "43.240.14.20", "79.127.221.20"):
    for u in ("", PID):
        r = adb("shell", "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                "--proxy", f"http://{host}:{PROXY_PORT}", "--proxy-user", f"{u}:{PASSWORD}",
                "-m", "12", "https://www.google.com/")
        print(f"   http-proxy {host:22s} user={u!r} -> {r.strip()[:40]}")

print("\n=== 3. activar datos moviles y apagar wifi ===")
print("   wifi off:", adb("shell", "svc", "wifi", "disable").strip()[:80])
print("   data on :", adb("shell", "svc", "data", "enable").strip()[:80])
time.sleep(12)
print("   redes:", [l for l in adb("shell", "dumpsys", "connectivity").splitlines()
                    if "Active default network" in l or "NetworkAgentInfo" in l][:3])
print("   interfaces:")
for line in adb("shell", "ip", "-4", "addr").splitlines():
    if "inet " in line:
        print("     ", line.strip())
print("   curl https google:", adb("shell", "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                                   "-m", "12", "https://www.google.com/").strip()[:60])
print("   curl http  any:", adb("shell", "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                               "-m", "12", "http://neverssl.com/").strip()[:60])

print("\n=== 4. volver wifi on y probar ===")
adb("shell", "svc", "wifi", "enable")
time.sleep(10)
print("   curl https google:", adb("shell", "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                                   "-m", "12", "https://www.google.com/").strip()[:60])

print("\n=== 5. logcat del proxy (errores) ===")
out = adb("shell", "logcat", "-d", "-t", "300", timeout=30)
for line in out.splitlines():
    low = line.lower()
    if any(k in low for k in ("volcproxy", "byteproxy", "naproxy", "proxy_byte", "socks")):
        print("   ", line.strip()[:220])
