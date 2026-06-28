#!/usr/bin/env python3
"""Read coverage.json totals only."""

import json

with open("coverage.json", "r") as f:
    d = json.load(f)

totals = d.get("totals", {})
print("Overall Coverage:", totals.get("percent_covered", 0))
print("Covered lines:", totals.get("covered_lines", 0))
print("Total statements:", totals.get("num_statements", 0))
print("Branches:", totals.get("num_branches", 0))
print("Missing branches:", totals.get("num_missing_branches", 0))

# Also print category breakdown
categories = {
    "pipeline": {"covered": 0, "total": 0},
    "schemas": {"covered": 0, "total": 0},
    "router": {"covered": 0, "total": 0},
    "client": {"covered": 0, "total": 0},
    "api": {"covered": 0, "total": 0},
    "monitoring": {"covered": 0, "total": 0},
    "database": {"covered": 0, "total": 0},
    "models": {"covered": 0, "total": 0},
    "other": {"covered": 0, "total": 0},
}

for filepath, data in d.get("files", {}).items():
    if "test" in filepath or "__pycache__" in filepath:
        continue
    summary = data.get("summary", {})
    covered = summary.get("covered_lines", 0)
    total = summary.get("num_statements", 0)
    if total == 0:
        continue

    cat = "other"
    if "schemas" in filepath:
        cat = "schemas"
    elif "pipeline" in filepath:
        cat = "pipeline"
    elif "llm" in filepath and "router" in filepath:
        cat = "router"
    elif "llm" in filepath and "client" in filepath:
        cat = "client"
    elif "api" in filepath:
        cat = "api"
    elif "monitoring" in filepath:
        cat = "monitoring"
    elif "database" in filepath:
        cat = "database"
    elif "models" in filepath:
        cat = "models"

    categories[cat]["covered"] += covered
    categories[cat]["total"] += total

print("\nCategory Breakdown:")
for cat, data in categories.items():
    if data["total"] > 0:
        pct = (data["covered"] / data["total"]) * 100
        print(
            f"  {cat:15s} | {pct:6.1f}% | covered={data['covered']} total={data['total']}"
        )
