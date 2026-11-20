"""Diagnostico v8: proxy/VPN/SIM del telefono + egress alternativo.

    python /tmp/diag_proxy.py
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

print("=== 1. apps de proxy/vpn/privacidad ===")
pk = adb("shell", "pm", "list", "packages")
for line in pk.splitlines():
    low = line.lower()
    if any(k in low for k in ("proxy", "vpn", "clash", "shadow", "v2ray", "sing", "tunnel",
                              "firewall", "ads", "super", "global", "turbo", "browser")):
        print("   ", line.strip())

print("\n=== 2. VPN en connectivity ===")
out = adb("shell", "dumpsys", "connectivity")
for line in out.splitlines():
    if "VPN" in line or "Vpn" in line or "vpn" in line:
        print("   ", line.strip()[:250])
print("   --- DefaultNetwork/ActiveNetwork ---")
for line in out.splitlines():
    if "Active default network" in line or "DefaultNetwork" in line or "DefaultHttpProxy" in line:
        print("   ", line.strip()[:250])

print("\n=== 3. DefaultHttpProxy real ===")
print(adb("shell", "dumpsys", "netpolicy")[:600])
print("   --- settings global proxy completo ---")
for line in adb("shell", "settings", "list", "global").splitlines():
    if "proxy" in line.lower():
        print("   ", line.strip()[:200])

print("\n=== 4. SIM / datos moviles ===")
print("   mobile_data:", adb("shell", "settings", "get", "global", "mobile_data").strip())
print("   svc data enable ->", adb("shell", "svc", "data", "enable").strip()[:120])
time.sleep(8)
print("   mobile_data ahora:", adb("shell", "settings", "get", "global", "mobile_data").strip())
print("   testeando egress con datos moviles:")
print("   ", adb("shell", "curl", "-v", "-o", "/dev/null", "-m", "10", "https://www.google.com")[:600])

print("\n=== 5. proxy en el gateway 10.24.4.1 (puertos comunes) ===")
for p in (3128, 8080, 8888, 1080, 7890, 8118, 9090, 443, 80):
    r = adb("shell", "nc", "-w", "2", "10.24.4.1", str(p), timeout=8)
    print(f"   10.24.4.1:{p} -> {r.strip()[:120]!r}")

print("\n=== 6. dns servers del dhcp ===")
print("   ", adb("shell", "getprop", "dhcp.wlan0.dns1").strip(),
      adb("shell", "getprop", "dhcp.wlan0.dns2").strip(),
      adb("shell", "getprop", "dhcp.wlan0.gateway").strip())

print("\n=== 7. GMS: la app Google tiene red propia? ===")
adb("shell", "am", "start", "-a", "android.intent.action.VIEW", "-d",
    "https://www.google.com/search?q=test", timeout=25)
time.sleep(12)
adb("shell", "uiautomator", "dump", "/sdcard/ui.xml", timeout=40)
xml = adb("shell", "cat", "/sdcard/ui.xml", timeout=25)
texts = [m.group(1) for m in re.finditer(r'text="([^"]{3,90})"', xml)]
print("   textos en pantalla:", texts[:25])

print("\n=== 8. byteproxy / daemons del sistema ===")
out = adb("shell", "ps", "-A")
for line in out.splitlines():
    low = line.lower()
    if any(k in low for k in ("proxy", "tun2socks", "redsocks", "iptables", "netd", "vpn")):
        print("   ", line.strip()[:200])
