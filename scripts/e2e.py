"""Browser walk-through used for milestone screenshots: python scripts/e2e.py <out_dir> [stage]

Stages: m1 (import + library), m2 (taxonomy + inbox), m3 (graph, map, digests, timeline), m4 (qa, recommend), m5 (settings, review)
Requires a running server on :8765.
"""

import glob
import sys

from playwright.sync_api import sync_playwright

out = sys.argv[1]
stages = sys.argv[2:] or ["m1"]
BASE = "http://127.0.0.1:8765/#"
errors: list[str] = []


def shot(page, name):
    page.wait_for_timeout(700)
    page.screenshot(path=f"{out}/{name}.png", full_page=False)


with sync_playwright() as p:
    exe = (glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome") or [None])[0]
    b = p.chromium.launch(executable_path=exe)
    page = b.new_page(viewport={"width": 1360, "height": 860})
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.on("pageerror", lambda e: errors.append(str(e)))

    if "m1" in stages:
        page.goto(BASE + "/import")
        page.click("text=使用 LLM 精修")  # rule-based import here; the LLM path is exercised by scripts/full_e2e.py
        page.set_input_files("input[type=file]", "论文总结记录.md")
        page.wait_for_selector("#import-report", timeout=60000)
        shot(page, "m1-import")
        page.goto(BASE + "/library")
        page.wait_for_selector(".paper-row")
        assert page.locator(".paper-row").count() == 19, page.locator(".paper-row").count()
        shot(page, "m1-library")
        page.fill("#search-box input", "Percept")
        page.wait_for_timeout(900)
        shot(page, "m1-search")
        page.locator(".paper-row").first.click()
        page.wait_for_selector("h2")
        shot(page, "m1-paper")
        page.goto(BASE + "/")
        shot(page, "home")
    if "m2" in stages:
        page.goto(BASE + "/categories")
        page.click("#preset-btn")
        page.wait_for_selector(".cat-row")
        shot(page, "m2-categories")
        page.goto(BASE + "/inbox")
        page.click("#classify-btn")
        page.wait_for_selector(".n-alert--success-type", timeout=900000)
        shot(page, "m2-inbox")
    if "m3" in stages:
        for name, route in [
            ("m3-graph", "/graph"),
            ("m3-map", "/map"),
            ("m3-digests", "/digests"),
            ("m3-timeline", "/timeline"),
        ]:
            page.goto(BASE + route)
            page.wait_for_timeout(2500)
            if name == "m3-digests":
                page.locator(".digest-cat").first.click()
                page.wait_for_timeout(1500)
            shot(page, name)
    if "m4" in stages:
        page.goto(BASE + "/qa")
        page.fill("#qa-input textarea", "Percept 上的 aDBS 能不能改算法？")
        page.click("#qa-btn")
        page.wait_for_selector("#qa-answer", timeout=240000)
        page.wait_for_timeout(3000)
        shot(page, "m4-qa")
        page.goto(BASE + "/recommend")
        shot(page, "m4-recommend")
    if "m5" in stages:
        for name, route in [("m5-settings", "/settings"), ("m5-review", "/review")]:
            page.goto(BASE + route)
            shot(page, name)
    b.close()
print("console errors:", errors)
sys.exit(1 if errors else 0)
