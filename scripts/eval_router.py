"""M2 acceptance run: route the 19 archive papers with the app's real router (docs Appendix A labels).

Modes: zero-shot (descriptions only) and leave-one-out (the other 18 papers carry their gold labels, as in steady state).
Needs downloaded models. Result: data/eval/router-<llm>.json
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
use_llm = "--llm" in sys.argv
weights = next(
    (tuple(float(x) for x in a.split("=")[1].split(",")) for a in sys.argv if a.startswith("--weights=")), None
)
tau = next((float(a.split("=")[1]) for a in sys.argv if a.startswith("--tau=")), None)
out_dir = ROOT / "data" / "eval"
os.environ["PAPERMIND_DATA_DIR_REAL"] = os.environ.get("PAPERMIND_DATA_DIR", str(ROOT / "data"))
real_data = Path(os.environ["PAPERMIND_DATA_DIR_REAL"])
tmp = tempfile.mkdtemp()
os.environ["PAPERMIND_DATA_DIR"] = tmp
(Path(tmp) / "models").symlink_to(real_data / "models")  # reuse downloaded models
(Path(tmp) / "bin").symlink_to(real_data / "bin")

from papermind.db.core import connect, init_db  # noqa: E402
from papermind.embed.index import ensure_paper_embeddings  # noqa: E402
from papermind.pipeline.ingest import import_text  # noqa: E402
from papermind.services import classify, router, taxonomy  # noqa: E402
from papermind.services.models import models  # noqa: E402

fix = ROOT / "tests" / "fixtures"
gold = json.loads((fix / "gold.json").read_text(encoding="utf-8"))["papers"]
if tau:
    router.SOFTMAX_TAU = tau
if weights:
    router.W_SIM, router.W_KNN, router.W_LLM = weights
# LLM output is deterministic (temperature 0): memoise it so weight sweeps need no extra LLM time
_cache_path = out_dir / "llm_cache.json"
_cache = json.loads(_cache_path.read_text()) if _cache_path.exists() else {}
_orig = router.llm_scores
_mode = {"m": ""}


def _cached(conn, client, paper, cats, examples):
    key = f"{_mode['m']}:{paper['id']}"
    if key not in _cache:
        _cache[key] = {str(k): v for k, v in _orig(conn, client, paper, cats, examples).items()}
        _cache_path.write_text(json.dumps(_cache))
    return {int(k): v for k, v in _cache[key].items()}


router.llm_scores = _cached
init_db()
conn = connect()
import_text(conn, (fix / "论文总结记录.md").read_text(encoding="utf-8"))
ids = taxonomy.seed_preset(conn)
tops = [c["id"] for c in conn.execute("SELECT id FROM category WHERE parent_id IS NULL ORDER BY position")]
top_by_label = {str(i + 1): cid for i, cid in enumerate(tops)}
keys = sorted(gold, key=int)  # papers were inserted in archive order
pids = [r["id"] for r in conn.execute("SELECT id FROM paper ORDER BY id")]
label = {pid: gold[k]["primary"] for pid, k in zip(pids, keys, strict=True)}
embed_client, spec = models.embedder()
ensure_paper_embeddings(conn, embed_client, spec)
llm = models.llm() if use_llm else None
result = {"llm": models.selected("llm").id if use_llm else None, "embed": spec.id, "modes": {}}
for mode in ("zero_shot", "leave_one_out"):
    _mode["m"] = mode
    conn.execute("DELETE FROM paper_category")
    conn.commit()
    if mode == "leave_one_out":
        for pid in pids:
            classify.set_categories(conn, pid, [top_by_label[label[pid]]])
    top1 = top3 = 0
    rows = []
    for pid in pids:
        res = router.route_paper(conn, pid, embed_client, spec, llm)
        ranked = []
        for s in res.suggestions:  # map sub-categories to their top-level parent
            t = taxonomy.top_level(conn, s.category_id)
            if t not in ranked:
                ranked.append(t)
        want = top_by_label[label[pid]]
        top1 += ranked[:1] == [want]
        top3 += want in ranked[:3]
        rows.append(
            {
                "paper": pid,
                "gold": label[pid],
                "correct": ranked[:1] == [want],
                "decision": res.decision,
                "top": [s.name for s in res.suggestions[:3]],
            }
        )
        print(mode, pid, ranked[:1] == [want], res.decision, flush=True)
    auto = [r for r in rows if r["decision"] == "auto"]
    result["modes"][mode] = {
        "top1": top1 / len(pids),
        "top3": top3 / len(pids),
        "rows": rows,
        "n_auto": len(auto),
        "auto_correct": sum(r["correct"] for r in auto),
        "n_inbox": sum(r["decision"] == "inbox" for r in rows),
        "tau": router.SOFTMAX_TAU,
    }
    m = result["modes"][mode]
    print("RESULT", mode, m["top1"], m["top3"], "auto", m["n_auto"], "inbox", m["n_inbox"], flush=True)
(out_dir / f"router-{'llm' if use_llm else 'embed-only'}{'-tau' + str(tau) if tau else ''}.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8"
)
