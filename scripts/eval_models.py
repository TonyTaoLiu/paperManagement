"""Benchmark candidate models on the 19-paper archive (docs/模型评测.md).

  python scripts/eval_models.py llm  <model-id> [--papers N] [--delete]
  python scripts/eval_models.py embed <model-id> [--delete]

Results are written to data/eval/<kind>-<model>-<n>.json; nothing here is estimated.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from papermind.config import data_dir  # noqa: E402
from papermind.importers.archive_md import parse_archive  # noqa: E402
from papermind.llm.client import LLMClient  # noqa: E402
from papermind.llm.schemas import (  # noqa: E402
    CLASSIFY_SYSTEM,
    EXTRACT_SYSTEM,
    PaperExtraction,
    category_schema,
    classify_user_prompt,
    extract_user_prompt,
)
from papermind.runtime.catalog import get_model  # noqa: E402
from papermind.runtime.downloader import delete_model, ensure_model  # noqa: E402
from papermind.runtime.llama_bin import ensure_llama_server  # noqa: E402
from papermind.runtime.manager import LlamaProcess  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
GOLD = json.loads((FIX / "gold.json").read_text(encoding="utf-8"))
MAX_CHARS = 3500


def load_papers():
    parsed = parse_archive((FIX / "论文总结记录.md").read_text(encoding="utf-8"))
    out = []
    for p in parsed.papers:
        text = "\n".join(t.assistant for t in p.turns)[:MAX_CHARS]
        out.append({"key": str(p.turns[0].index), "title": p.title, "text": text})
    return out


def progress_printer():
    last = [0.0]

    def cb(done, total):
        if time.time() - last[0] > 5:
            last[0] = time.time()
            print(f"  download {done / 1e6:.0f}/{total / 1e6:.0f} MB", flush=True)

    return cb


def norm(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


def recall(extracted: list[str], gold: list[str]) -> float | None:
    if not gold:
        return None
    ex = [norm(e) for e in extracted]
    return sum(any(norm(g) in e for e in ex) for g in gold) / len(gold)


def eval_llm(args):
    spec = get_model(args.model)
    papers = load_papers()
    # quick-screen set: spread across categories (first N of an interleaved order)
    order = [0, 5, 10, 14, 17, 2, 7, 12, 3, 9, 15, 1, 6, 11, 16, 4, 8, 13, 18]
    papers = [papers[i] for i in order][: args.papers]
    binary = ensure_llama_server(print)
    t0 = time.time()
    path = ensure_model(spec, progress_printer())
    print(f"model ready in {time.time() - t0:.0f}s: {path.name}", flush=True)
    proc = LlamaProcess(binary, path, ctx=8192)
    t0 = time.time()
    proc.start()
    load_s = time.time() - t0
    client = LLMClient(proc.base_url, spec.id)
    cats = [tuple(c) for c in GOLD["categories"]]
    CatSchema = category_schema([c[0] for c in cats])
    rows = []
    try:
        for p in papers:
            gold = GOLD["papers"][p["key"]]
            row = {"key": p["key"], "title": p["title"][:60]}
            try:
                r = client.chat(
                    [{"role": "system", "content": EXTRACT_SYSTEM},
                     {"role": "user", "content": extract_user_prompt(p["title"], p["text"])}],
                    schema=PaperExtraction, max_tokens=900, retries=0,
                )  # fmt: skip
                ex = r.parsed
                src = norm(p["text"])
                items = ex.modalities + ex.methods + ex.datasets + ex.devices
                row.update(
                    valid=True, seconds=r.seconds, tps=r.tokens_per_second,
                    prompt_tokens=r.prompt_tokens, completion_tokens=r.completion_tokens,
                    type_ok=ex.paper_type == gold["paper_type"], paper_type=ex.paper_type,
                    modality_recall=recall(ex.modalities, gold["modalities"]),
                    method_recall=recall(ex.methods, gold["methods"]),
                    grounded=(sum(norm(i) in src for i in items) / len(items)) if items else None,
                    n_items=len(items), one_liner=ex.one_liner,
                )  # fmt: skip
            except Exception as e:  # noqa: BLE001 - record and continue
                row.update(valid=False, error=str(e)[:200])
            try:
                r = client.chat(
                    [{"role": "system", "content": CLASSIFY_SYSTEM},
                     {"role": "user", "content": classify_user_prompt(cats, p["title"], p["text"])}],
                    schema=CatSchema, max_tokens=60, retries=0,
                )  # fmt: skip
                rank = r.parsed.ranking
                row.update(cls_top1=bool(rank) and rank[0] == gold["primary"],
                           cls_top3=gold["primary"] in rank[:3], cls_rank=rank, cls_seconds=r.seconds)  # fmt: skip
            except Exception as e:  # noqa: BLE001
                row.update(cls_top1=False, cls_top3=False, cls_error=str(e)[:200])
            rows.append(row)
            print(json.dumps({k: v for k, v in row.items() if k != "one_liner"}, ensure_ascii=False), flush=True)
        peak = proc.peak_rss_mb()
    finally:
        proc.stop()

    def mean(key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return sum(vals) / len(vals) if vals else None

    summary = {
        "model": spec.id, "file": spec.filename, "papers": len(rows), "load_seconds": load_s,
        "json_valid_rate": sum(bool(r.get("valid")) for r in rows) / len(rows),
        "type_acc": mean("type_ok"), "modality_recall": mean("modality_recall"),
        "method_recall": mean("method_recall"), "grounded_rate": mean("grounded"),
        "cls_top1": mean("cls_top1"), "cls_top3": mean("cls_top3"),
        "gen_tps": mean("tps"), "extract_seconds": mean("seconds"), "peak_rss_mb": peak,
        "threads": proc.threads,
    }  # fmt: skip
    out = data_dir() / "eval"
    out.mkdir(exist_ok=True)
    (out / f"llm-{spec.id}-{len(rows)}.json").write_text(
        json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print("SUMMARY", json.dumps(summary, ensure_ascii=False), flush=True)
    if args.delete:
        delete_model(spec)


def eval_embed(args):
    spec = get_model(args.model)
    papers = load_papers()
    binary = ensure_llama_server(print)
    path = ensure_model(spec, progress_printer())
    proc = LlamaProcess(binary, path, embedding=True, ctx=spec.ctx, extra_args=["-b", "2048", "-ub", "2048"])
    t0 = time.time()
    proc.start()
    load_s = time.time() - t0
    client = LLMClient(proc.base_url, spec.id)
    try:
        docs = [spec.doc_prefix + f"{p['title']}\n{p['text'][:1500]}" for p in papers]
        t0 = time.time()
        D = np.array([client.embed([d])[0] for d in docs], dtype=np.float32)
        doc_s = time.time() - t0
        qs = [spec.query_prefix + q for q, _ in GOLD["queries"]]
        Q = np.array(client.embed(qs), dtype=np.float32)
        cat_texts = [spec.doc_prefix + f"{c[1]}：{c[2]}" for c in GOLD["categories"]]
        C = np.array(client.embed(cat_texts), dtype=np.float32)
        peak = proc.peak_rss_mb()
    finally:
        proc.stop()
    D /= np.linalg.norm(D, axis=1, keepdims=True)
    C /= np.linalg.norm(C, axis=1, keepdims=True)
    Q /= np.linalg.norm(Q, axis=1, keepdims=True)
    keys = [p["key"] for p in papers]
    sims = Q @ D.T
    top1 = top3 = 0
    for i, (_, key) in enumerate(GOLD["queries"]):
        order = [keys[j] for j in np.argsort(-sims[i])]
        top1 += order[0] == key
        top3 += key in order[:3]
    # leave-one-out kNN on top-level category (k=3, similarity-weighted vote)
    labels = [GOLD["papers"][k]["primary"] for k in keys]
    S = D @ D.T
    np.fill_diagonal(S, -1)
    knn1 = knn3 = 0
    for i in range(len(keys)):
        nn = np.argsort(-S[i])[:3]
        knn1 += labels[nn[0]] == labels[i]
        votes: dict[str, float] = {}
        for j in nn:
            votes[labels[j]] = votes.get(labels[j], 0) + float(S[i, j])
        knn3 += max(votes, key=votes.get) == labels[i]
    # zero-shot: nearest category-description vector (no labelled papers used)
    cat_ids = [c[0] for c in GOLD["categories"]]
    zs1 = zs3 = 0
    for i, k in enumerate(keys):
        order = [cat_ids[j] for j in np.argsort(-(D[i] @ C.T))]
        zs1 += order[0] == GOLD["papers"][k]["primary"]
        zs3 += GOLD["papers"][k]["primary"] in order[:3]
    summary = {
        "zeroshot_top1": zs1 / len(keys), "zeroshot_top3": zs3 / len(keys),
        "model": spec.id, "dim": int(D.shape[1]), "load_seconds": load_s,
        "query_top1": top1 / len(qs), "query_top3": top3 / len(qs),
        "knn1_acc": knn1 / len(keys), "knn3_acc": knn3 / len(keys),
        "seconds_per_doc": doc_s / len(docs), "peak_rss_mb": peak,
    }  # fmt: skip
    out = data_dir() / "eval"
    out.mkdir(exist_ok=True)
    (out / f"embed-{spec.id}.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print("SUMMARY", json.dumps(summary), flush=True)
    if args.delete:
        delete_model(spec)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["llm", "embed"])
    ap.add_argument("model")
    ap.add_argument("--papers", type=int, default=19)
    ap.add_argument("--delete", action="store_true")
    a = ap.parse_args()
    (eval_llm if a.kind == "llm" else eval_embed)(a)
