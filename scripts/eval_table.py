"""Print Markdown tables from data/eval/*.json (real measurements only)."""

import glob
import json
import os
import sys

d = sys.argv[1] if len(sys.argv) > 1 else "data/eval"
pct = lambda v: "—" if v is None else f"{v * 100:.0f}%"  # noqa: E731
for n in (5, 19):
    rows = [json.load(open(f))["summary"] for f in sorted(glob.glob(f"{d}/llm-*-{n}.json"))]
    if not rows:
        continue
    print(f"\n### 生成模型（{n} 篇）\n")
    print("| 模型 | JSON合法率 | 文献类型准确 | 模态召回 | 方法召回 | 抽取可溯源率 | 分类Top-1 | 分类Top-3 | 生成速度 tok/s | 单篇抽取秒 | 峰值内存 MB |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for s in rows:
        print(f"| {s['model']} | {pct(s['json_valid_rate'])} | {pct(s['type_acc'])} | {pct(s['modality_recall'])} | {pct(s['method_recall'])} | {pct(s['grounded_rate'])} | {pct(s['cls_top1'])} | {pct(s['cls_top3'])} | {(s['gen_tps'] or 0):.1f} | {(s['extract_seconds'] or 0):.1f} | {s['peak_rss_mb']:.0f} |")  # noqa: E501
rows = [json.load(open(f)) for f in sorted(glob.glob(f"{d}/embed-*.json"))]
if rows:
    print("\n### 嵌入模型（19 篇 / 20 条查询）\n")
    print("| 模型 | 维度 | 查询Top-1 | 查询Top-3 | 类别描述零样本Top-1 | 零样本Top-3 | 留一1-NN | 单篇秒 | 峰值内存 MB |")
    print("|---|---|---|---|---|---|---|---|---|")
    for s in rows:
        print(f"| {s['model']} | {s['dim']} | {pct(s['query_top1'])} | {pct(s['query_top3'])} | {pct(s.get('zeroshot_top1'))} | {pct(s.get('zeroshot_top3'))} | {pct(s['knn1_acc'])} | {s['seconds_per_doc']:.2f} | {s['peak_rss_mb']:.0f} |")  # noqa: E501
