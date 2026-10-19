"""Smoke test: run the launcher, wait for /api/health, then shut it down."""

import os
import subprocess
import sys
import time
import urllib.request

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
win = sys.platform == "win32"
launcher = ["cmd", "/c", "start.bat"] if win else ["bash", "start.sh"]
env = dict(os.environ, PAPERMIND_NO_OPEN="1", PAPERMIND_DATA_DIR=os.path.join(root, "data-smoke"))
proc = subprocess.Popen(launcher, cwd=root, env=env)
ok = False
try:
    for _ in range(180):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8765/api/health", timeout=2) as r:
                body = r.read().decode()
                print(body)
                ok = '"status":"ok"' in body.replace(" ", "")
                break
        except Exception:
            time.sleep(1)
    if ok:
        with urllib.request.urlopen("http://127.0.0.1:8765/", timeout=5) as r:
            ok = b"PaperMind" in r.read()
finally:
    if win:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.terminate()
sys.exit(0 if ok else 1)
