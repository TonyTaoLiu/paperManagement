"""Screenshots of a populated library (server on :8765): inbox before/after confirming, taxonomy, paper card, digests."""

import glob
import json
import sys
import urllib.request

from playwright.sync_api import sync_playwright

out = sys.argv[1]
API = "http://127.0.0.1:8765/api"
BASE = "http://127.0.0.1:8765/#"


def call(path, method="GET", body=None):
    req = urllib.request.Request(
        API + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )  # noqa: E501
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


errors: list[str] = []
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome")[0])
    page = b.new_page(viewport={"width": 1360, "height": 860})
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("response", lambda r: r.status >= 400 and errors.append(f"{r.status} {r.url}"))

    def shot(name, route, wait=1500):
        page.goto(BASE + route)
        page.wait_for_timeout(wait)
        page.screenshot(path=f"{out}/{name}.png")

    shot("m2-inbox", "/inbox")
    shot("m2-categories", "/categories")
    inbox = call("/inbox")
    for it in inbox:  # the user's one-click confirmation of the top suggestion
        call(
            f"/inbox/{it['id']}/decision",
            "POST",
            {"action": "confirm", "category_id": it["suggestions"][0]["category_id"]},
        )
    print("confirmed", len(inbox))
    shot("m2-categories-after", "/categories")
    shot("m1-library", "/library")
    page.goto(BASE + "/library")
    page.wait_for_selector(".paper-row")
    page.locator(".paper-row").nth(9).click()
    page.wait_for_selector("h2")
    page.wait_for_timeout(1200)
    page.screenshot(path=f"{out}/m1-paper.png")
    shot("m3-graph", "/graph", 3000)
    shot("m3-map", "/map", 3000)
    page.goto(BASE + "/digests")
    page.wait_for_timeout(1000)
    page.locator(".digest-cat").nth(4).click()
    page.wait_for_timeout(1500)
    page.screenshot(path=f"{out}/m3-digests.png")
    shot("home", "/")
    b.close()
print("errors:", errors)
sys.exit(1 if errors else 0)
