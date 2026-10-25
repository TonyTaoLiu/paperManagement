"""Full real-model walk-through against a running server (no mocks): LLM import, classify, relations, recommend, QA.

Usage: python scripts/full_e2e.py  (server on :8765 with models/bin available). Prints a JSON report.
"""

import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8765/api"


def call(path, method="GET", body=None):
    req = urllib.request.Request(
        BASE + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )  # noqa: E501
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.loads(r.read())


def wait(task, label, timeout=3600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        t = call(f"/tasks/{task['id']}")
        if t["status"] != "running":
            print(
                label,
                t["status"],
                round(time.time() - t0),
                "s",
                json.dumps(t["result"], ensure_ascii=False)[:300] if t["result"] else t["error"],
                flush=True,
            )
            return t
        time.sleep(5)
    raise TimeoutError(label)


report = {}
START = next((a.split("=")[1] for a in sys.argv if a.startswith("--from=")), "import")
if START == "relations":
    report = json.load(open("data/eval/full_e2e.json")) if False else {}
paste = open("tests/fixtures/论文总结记录.md", encoding="utf-8").read().split("## 06.")[0].split("## 02.")[1]
paste = "## 02." + paste
sample = "Decoding alignment without encoding alignment\n\n" + paste
if START == "import":
    t = wait(call("/import/text", "POST", {"text": sample, "use_llm": True}), "llm-import-single")
    report["llm_import"] = t["result"]
    assert t["status"] == "done" and t["result"]["used_llm"], "LLM extraction did not run"
    p = call("/papers/1")
    report["llm_extracted_paper"] = {k: p[k] for k in ("title", "paper_type", "one_liner")} | {
        "entities": p["entities"]
    }
    call("/papers/1", "DELETE")
    text = open("论文总结记录.md", encoding="utf-8").read()
    report["import_full"] = wait(
        call("/import/text", "POST", {"text": text, "use_llm": False, "filename": "论文总结记录.md"}), "import-full"
    )["result"]
    call("/categories/preset", "POST")
    report["classify"] = wait(call("/classify", "POST", {}), "classify")["result"]
report["relations"] = wait(call("/relations/rebuild?use_llm=true", "POST"), "relations")["result"]
report["recommend"] = wait(call("/recommendations/refresh", "POST"), "recommend")
rec = call("/recommendations?limit=10")
report["recommend_top"] = [{"title": r["title"][:80], "reason": r["reason"][:120], "src": r["source"]} for r in rec[:5]]
report["recommend_all_have_reason"] = all(r["reason"] for r in rec)
if rec:
    call(f"/recommendations/{rec[0]['id']}/feedback", "POST", {"value": -1})
    report["after_dislike_first_changed"] = call("/recommendations?limit=10")[0]["id"] != rec[0]["id"]
qa = call("/qa", "POST", {"question": "Percept 上的 aDBS 能不能改算法？"})
report["qa"] = {"answer": qa["answer"][:400], "sources": qa["sources"], "used_llm": qa["used_llm"]}
report["qa_out_of_scope"] = call("/qa", "POST", {"question": "How do I bake sourdough bread?"})["answer"]
json.dump(report, open("data/eval/full_e2e.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(report, ensure_ascii=False, indent=1)[:3000])
sys.exit(0)
