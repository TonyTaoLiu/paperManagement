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
deadline = time.time() + 420
try:
    while time.time() < deadline:
        if proc.poll() is not None:
            print(f"launcher exited early with code {proc.returncode}", flush=True)
            break
        try:
            with urllib.request.urlopen("http://127.0.0.1:8765/api/health", timeout=2) as r:
                body = r.read().decode()
                print(body, flush=True)
                ok = '"status":"ok"' in body.replace(" ", "")
                break
        except OSError:
            time.sleep(2)
    if ok:
        with urllib.request.urlopen("http://127.0.0.1:8765/", timeout=5) as r:
            ok = b"PaperMind" in r.read()
        print("index page ok" if ok else "index page missing", flush=True)
finally:
    if win:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], check=False, capture_output=True)
    else:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
print("SMOKE", "PASS" if ok else "FAIL", flush=True)
sys.stdout.flush()
os._exit(0 if ok else 1)
