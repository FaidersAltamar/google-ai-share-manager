"""Diagnostico v5: red del telefono FoxPhone.

    python /tmp/diag5.py
"""
import sys, os, json, time, socket, threading, select, subprocess, urllib.request, re

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
API = "http://ai-share-manager:8000"
ADB = "/opt/platform-tools/platform-tools/adb"
LP = 19536

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
    return (r.stdout + r.stderr).decode("utf-8", errors="replace")


def ensure_dev(tries=8):
    for _ in range(tries):
        out = adb("devices")
        if "127.0.0.1" in out and "device" in out:
            return True
        adb("connect", f"127.0.0.1:{LP}")
        time.sleep(2)
    raise RuntimeError("sin dispositivo")


print("connect:", adb("connect", f"127.0.0.1:{LP}")); time.sleep(2)
ensure_dev(); print("devices ok\n")

print("=== 1. mobile_data / wifi settings ===")
for c in (["shell", "settings", "get", "global", "mobile_data"],
          ["shell", "settings", "get", "global", "wifi_on"],
          ["shell", "settings", "get", "global", "airplane_mode_on"],
          ["shell", "settings", "get", "secure", "http_proxy"]):
    print(f"   $ {' '.join(c[1:])} -> {adb(*c, timeout=20).strip()[:200]}")

print("\n=== 2. connectivity ===")
out = adb("shell", "dumpsys", "connectivity", timeout=40)
for line in out.splitlines():
    if any(k in line for k in ("NetworkAgentInfo", "Active default", "mDefault", "No Networks",
                                "WIFI", "MOBILE", "isDefault", "State:")):
        print("   ", line.strip()[:220])

print("\n=== 3. interfaces / ip ===")
print(adb("shell", "ip", "-4", "addr", timeout=30)[:1200])
print("\n=== 4. rutas ===")
print(adb("shell", "ip", "route", timeout=30)[:600])

print("\n=== 5. dns ===")
print(adb("shell", "getprop", "net.dns1", timeout=20),
      adb("shell", "getprop", "net.dns2", timeout=20))
print("   ping dns:", adb("shell", "ping", "-c", "1", "-W", "3", "www.google.com", timeout=25).strip()[:300])

print("\n=== 6. wifi scan ===")
print(adb("shell", "cmd", "wifi", "status", timeout=30)[:600])
try:
    print(adb("shell", "cmd", "wifi", "list-networks", timeout=40)[:1200])
except Exception as e:
    print("   err", e)

print("\n=== 7. probando activacion ===")
for c in (["shell", "svc", "data", "enable"],
          ["shell", "svc", "wifi", "enable"],
          ["shell", "cmd", "netpolicy", "list", "networks"]):
    print(f"   $ {' '.join(c[1:])} -> {adb(*c, timeout=40).strip()[:500]}")

time.sleep(5)
print("\n=== 8. reconexion ===")
print("   ping:", adb("shell", "ping", "-c", "1", "-W", "3", "www.google.com", timeout=25).strip()[:300])
for u in ("https://www.google.com", "https://scale.com.co"):
    print(f"   curl {u} ->", adb("shell", "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-m", "15", u, timeout=30).strip()[:200])

print("\n=== 9. proxy del dispositivo (si elISP filtra) ===")
print(adb("shell", "settings", "list", "global", timeout=30)[:1500])
