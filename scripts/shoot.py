"""Take screenshots of main pages: python scripts/shoot.py <out_dir> <route> [<route> ...]"""

import glob
import sys

from playwright.sync_api import sync_playwright

out, routes = sys.argv[1], sys.argv[2:]
with sync_playwright() as p:
    exe = (glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome") or [None])[0]
    b = p.chromium.launch(executable_path=exe)
    page = b.new_page(viewport={"width": 1280, "height": 800})
    errors = []
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.on("pageerror", lambda e: errors.append(str(e)))
    for r in routes:
        page.goto(f"http://127.0.0.1:8765/#{r}")
        page.wait_for_timeout(1200)
        name = r.strip("/").replace("/", "_") or "home"
        page.screenshot(path=f"{out}/{name}.png")
    b.close()
print("console errors:", errors)
sys.exit(1 if errors else 0)
