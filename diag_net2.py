"""Diagnostico v12: limpiar la cadena NAT muerta del proxy y probar egress.

    python /tmp/diag_net2.py
"""
import sys, os, json, time, socket, threading, select, subprocess, urllib.request, re

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
API = os.environ.get("VPS_API", "http://ai-share-manager:8000")
ADB = "/opt/platform-tools/platform-tools/adb"
LP = int(os.environ.get("DIAG_PORT", "19536"))
VPS = "179.66.140.79"

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


def test(host):
    r = adb("shell", "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-m", "12", host)
    return r.strip()[:60]


print("connect:", adb("connect", f"127.0.0.1:{LP}")); time.sleep(3)
ensure_dev(); print("devices OK\n")

print("=== 1. hay listener en 12345/12346? ===")
for p in (12345, 12346, 12347):
    r = adb("shell", "nc", "-w", "2", "127.0.0.1", str(p), timeout=8)
    print(f"   127.0.0.1:{p} -> {r.strip()[:100]!r}")

print("\n=== 2. volcproxy: proceso y sockets ===")
out = adb("shell", "ps", "-A", "-o", "PID,ARGS")
for line in out.splitlines():
    if "volc" in line.lower() or "proxy" in line.lower():
        print("   ", line.strip()[:200])
for pid in re.findall(r"^\s*(\d+)\s+.*volcproxy", out, re.M):
    print("   fds de", pid, ":")
    print(adb("shell", "ls", "-l", f"/proc/{pid}/fd")[:1500])
    print("   net/tcp del proceso:")
    print(adb("shell", "cat", f"/proc/{pid}/net/tcp")[:800])

print("\n=== 3. reglas NAT exactas (backup) ===")
rules = adb("shell", "iptables", "-t", "nat", "-S")
open("/tmp/nat_rules.txt", "w", encoding="utf-8").write(rules)
print(rules[:2500])

print("\n=== 4. ¿el telefono alcanza al VPS por TCP? (antes de tocar nada) ===")
for p in (8000, 443, 80, 8888):
    r = adb("shell", "nc", "-w", "4", VPS, str(p), timeout=10)
    print(f"   {VPS}:{p} -> {r.strip()[:80]!r}")

print("\n=== 5. probar HTTPS con proxy explicito del API (fastapi no es proxy) ===")
print("   api health via IP publica:", adb("shell", "curl", "-s", "-m", "8", f"http://{VPS}:8000/health").strip()[:120])

print("\n=== 6. VOLCAR la cadena VOLC_PROXY_NAT_CHAIN (los REDIRECT muertos) ===")
print("   flush:", adb("shell", "iptables", "-t", "nat", "-F", "VOLC_PROXY_NAT_CHAIN").strip()[:200])
time.sleep(2)
print("   cadena ahora:")
print(adb("shell", "iptables", "-t", "nat", "-L", "VOLC_PROXY_NAT_CHAIN", "-n")[:1200])

print("\n=== 7. egress directo (sin proxy local) ===")
for u in ("https://www.google.com/", "https://www.youtube.com/", "https://scale.com.co/",
          "http://neverssl.com/"):
    print(f"   {u:32s} -> {test(u)}")

print("\n=== 8. ping y DNS ===")
print("   ping gw:", "OK" if "bytes from" in adb("shell", "ping", "-c", "1", "-W", "2", "10.24.4.1", timeout=12) else "FAIL")
print("   dns:", adb("shell", "getprop", "dhcp.wlan0.dns1").strip(),
      adb("shell", "getprop", "dhcp.wlan0.dns2").strip())
print("   curl por IP de google (sin DNS):",
      adb("shell", "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-m", "10",
          "https://142.251.153.119/").strip()[:40])

print("\n=== 9. si funciona: probar el proxy http del VPS como puente ===")
print("   (el VPS tiene internet; probamos si el telefono alcanza 179.66.140.79:8000)")
