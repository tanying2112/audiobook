#!/usr/bin/env python3
"""Generate coverage report from existing coverage.json."""

import json
from pathlib import Path
from datetime import datetime


def categorize(filepath):
    if "schemas" in filepath: return "schemas"
    elif "pipeline" in filepath: return "pipeline"
    elif "llm" in filepath and "router" in filepath: return "router"
    elif "llm" in filepath and "client" in filepath: return "client"
    elif "api" in filepath: return "api"
    elif "monitoring" in filepath: return "monitoring"
    elif "database" in filepath: return "database"
    elif "models" in filepath: return "models"
    else: return "other"


with open("coverage.json") as f:
    d = json.load(f)

totals = d.get("totals", {})
print(f"Overall: {totals.get('percent_covered', 0):.1f}%")
print(f"Covered: {totals.get('covered_lines', 0)} / {totals.get('num_statements', 0)}")

cats = {}
for fp, data in d.get("files", {}).items():
    if "test" in fp or "__pycache__" in fp: continue
    s = data.get("summary", {})
    c = s.get("covered_lines", 0)
    t = s.get("num_statements", 0)
    p = s.get("percent_covered", 0)
    if t == 0: continue
    cat = categorize(fp)
    if cat not in cats:
        cats[cat] = {"c": 0, "t": 0, "files": []}
    cats[cat]["c"] += c
    cats[cat]["t"] += t
    cats[cat]["files"].append({"file": fp, "pct": p, "missing": len(data.get("missing_lines", []))})

print("\nCategories:")
targets = {"pipeline": 75, "schemas": 95, "router": 70, "client": 70, "api": 80, "monitoring": 70, "database": 70, "models": 70}
for cat, data in sorted(cats.items()):
    if data["t"] > 0:
        pct = data["c"] / data["t"] * 100
        target = targets.get(cat, "N/A")
        status = "PASS" if pct >= target else "FAIL"
        print(f"  {cat:15s} {pct:6.1f}% target={target}% [{status}] files={len(data['files'])}")

# Low coverage files
print("\nLow coverage (<50%, >10 lines):")
for cat, data in cats.items():
    for f in sorted(data["files"], key=lambda x: x["pct"]):
        if f["pct"] < 50 and f["file"].count("/") > 2:
            print(f"  {f['pct']:.1f}% {f['file']} ({f['missing']} missing)")