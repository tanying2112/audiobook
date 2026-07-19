#!/usr/bin/env python3
"""Read coverage.json and extract totals."""

import json
from pathlib import Path

with open("coverage.json", "r") as f:
    d = json.load(f)

totals = d.get("totals", {})
print("Overall Coverage:", totals.get("percent_covered", 0))
print("Covered lines:", totals.get("covered_lines", 0))
print("Total statements:", totals.get("num_statements", 0))
print("Branches:", totals.get("num_branches", 0))
print("Missing branches:", totals.get("num_missing_branches", 0))
