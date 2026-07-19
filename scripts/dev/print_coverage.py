import json
import sys

with open("coverage.json") as f:
    d = json.load(f)
t = d.get("totals", {})
print("Overall:", t.get("percent_covered", 0), "%")
print("Covered:", t.get("covered_lines", 0), "Total:", t.get("num_statements", 0))
