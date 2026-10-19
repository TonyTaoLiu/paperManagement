"""Run the PyInstaller bundle (dist/papermind) and wait for /api/health plus the index page."""

import os
import subprocess
import sys
import time
import urllib.request

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
exe = os.path.join(root, "dist", "papermind", "papermind.exe" if sys.platform == "win32" else "papermind")
env = dict(os.environ, PAPERMIND_DATA_DIR=os.path.join(root, "data-frozen"))
proc = subprocess.Popen([exe, "serve", "--port", "8766"], env=env)
ok = False
deadline = time.time() + 120
try:
    while time.time() < deadline and proc.poll() is None:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8766/api/health", timeout=2) as r:
                ok = b'"status":"ok"' in r.read().replace(b" ", b"")
            with urllib.request.urlopen("http://127.0.0.1:8766/", timeout=5) as r:
                ok = ok and b"PaperMind" in r.read()
            break
        except OSError:
            time.sleep(2)
finally:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], check=False, capture_output=True)
    else:
        proc.terminate()
print("FROZEN SMOKE", "PASS" if ok else "FAIL", flush=True)
os._exit(0 if ok else 1)
