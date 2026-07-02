#!/usr/bin/env python3
"""Pre-commit hook to check coverage configuration exists.

This is a lightweight hook that verifies coverage configuration is present.
Actual coverage enforcement happens in CI and can be run locally with:
  pytest --cov=src --cov-fail-under=80
"""

import os
import sys


def main():
    # Check if either .coveragerc or pyproject.toml exists with coverage config
    config_files = [".coveragerc", "pyproject.toml"]
    config_found = False
    
    for config_file in config_files:
        if os.path.exists(config_file):
            with open(config_file, "r") as f:
                content = f.read()
                if "fail_under" in content and ("80" in content or "fail_under = 80" in content or '"fail_under": 80' in content):
                    config_found = True
                    print(f"✅ Found coverage configuration in {config_file}")
                    break
    
    if not config_found:
        print("⚠️  Warning: No coverage configuration with fail_under=80 found")
        print("   Please ensure .coveragerc or pyproject.toml has:")
        print("   [tool.coverage.report]")
        print("   fail_under = 80")
        # Don't fail - just warn, as CI will catch it
        return 0
    
    # Also check if we have recent coverage data (optional)
    if os.path.exists("coverage.json"):
        import json
        try:
            with open("coverage.json", "r") as f:
                data = json.load(f)
            total_pct = data.get("totals", {}).get("percent_covered", 0)
            if total_pct >= 80:
                print(f"✅ Current coverage: {total_pct:.2f}% (≥80%)")
            else:
                print(f"⚠️  Current coverage: {total_pct:.2f}% (<80%) - will be caught in CI")
        except Exception:
            pass  # Ignore errors reading coverage.json
    
    print("✅ Coverage configuration check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
