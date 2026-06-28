#!/usr/bin/env python3
"""Generate coverage baseline report from existing coverage.json."""

import json
from datetime import datetime
from pathlib import Path


def categorize_file(filepath: str) -> str:
    """Categorize a file by its module type."""
    if "schemas" in filepath:
        return "schemas"
    elif "pipeline" in filepath:
        return "pipeline"
    elif "llm" in filepath and "router" in filepath:
        return "router"
    elif "llm" in filepath and "client" in filepath:
        return "client"
    elif "api" in filepath:
        return "api"
    elif "monitoring" in filepath:
        return "monitoring"
    elif "database" in filepath:
        return "database"
    elif "models" in filepath:
        return "models"
    else:
        return "other"


def calculate_category_coverage(cov_data: dict) -> dict:
    """Calculate coverage per category."""
    categories = {
        "pipeline": {"covered": 0, "total": 0, "files": []},
        "schemas": {"covered": 0, "total": 0, "files": []},
        "router": {"covered": 0, "total": 0, "files": []},
        "client": {"covered": 0, "total": 0, "files": []},
        "api": {"covered": 0, "total": 0, "files": []},
        "monitoring": {"covered": 0, "total": 0, "files": []},
        "database": {"covered": 0, "total": 0, "files": []},
        "models": {"covered": 0, "total": 0, "files": []},
        "other": {"covered": 0, "total": 0, "files": []},
    }

    for filepath, data in cov_data.get("files", {}).items():
        # Skip test files
        if "test" in filepath or "__pycache__" in filepath:
            continue

        summary = data.get("summary", {})
        covered = summary.get("covered_lines", 0)
        total = summary.get("num_statements", 0)
        pct = summary.get("percent_covered", 0.0)

        if total == 0:
            continue

        cat = categorize_file(filepath)
        categories[cat]["covered"] += covered
        categories[cat]["total"] += total
        categories[cat]["files"].append(
            {
                "file": filepath,
                "covered": covered,
                "total": total,
                "percent": pct,
                "missing_lines": data.get("missing_lines", []),
            }
        )

    # Calculate percentages
    result = {}
    for cat, data in categories.items():
        if data["total"] > 0:
            pct = (data["covered"] / data["total"]) * 100
        else:
            pct = 0.0
        result[cat] = {
            "percent_covered": round(pct, 1),
            "covered_lines": data["covered"],
            "total_lines": data["total"],
            "file_count": len(data["files"]),
            "files": sorted(data["files"], key=lambda x: x["percent"]),
        }

    return result


def check_targets(category_coverage: dict) -> dict:
    """Check coverage against targets."""
    targets = {
        "pipeline": 75,
        "schemas": 95,
        "router": 70,
        "client": 70,
        "api": 80,
        "monitoring": 70,
        "database": 70,
        "models": 70,
    }

    results = {}
    all_pass = True

    for cat, target in targets.items():
        actual = category_coverage.get(cat, {}).get("percent_covered", 0.0)
        passed = actual >= target
        if not passed:
            all_pass = False

        results[cat] = {
            "target": target,
            "actual": actual,
            "passed": passed,
            "gap": round(target - actual, 1) if not passed else 0,
        }

    # Total
    total_covered = sum(v["covered_lines"] for v in category_coverage.values())
    total_lines = sum(v["total_lines"] for v in category_coverage.values())
    total_pct = round((total_covered / total_lines) * 100, 1) if total_lines > 0 else 0

    results["total"] = {
        "target": 90,
        "actual": total_pct,
        "passed": total_pct >= 90,
        "gap": round(90 - total_pct, 1) if total_pct < 90 else 0,
    }

    results["overall_pass"] = all_pass
    return results


def generate_report():
    """Generate full coverage baseline report."""
    print("Loading coverage.json...")

    with open("coverage.json", "r") as f:
        cov_data = json.load(f)

    category_coverage = calculate_category_coverage(cov_data)
    targets_check = check_targets(category_coverage)

    totals = cov_data.get("totals", {})
    overall_pct = totals.get("percent_covered", 0.0)

    report = {
        "timestamp": datetime.now().isoformat(),
        "overall_percent_covered": overall_pct,
        "totals": {
            "covered_lines": totals.get("covered_lines", 0),
            "num_statements": totals.get("num_statements", 0),
            "num_branches": totals.get("num_branches", 0),
            "num_partial_branches": totals.get("num_partial_branches", 0),
            "num_missing_branches": totals.get("num_missing_branches", 0),
        },
        "categories": category_coverage,
        "targets_check": targets_check,
        "low_coverage_files": _get_low_coverage_files(category_coverage),
    }

    return report


def _get_low_coverage_files(category_coverage: dict, threshold: float = 50.0) -> list:
    """Get files below coverage threshold."""
    low = []
    for cat, cat_data in category_coverage.items():
        for f in cat_data.get("files", []):
            if f["percent"] < threshold and f["total"] > 10:
                low.append(
                    {
                        "file": f["file"],
                        "category": cat,
                        "percent": f["percent"],
                        "missing_lines_count": len(f["missing_lines"]),
                    }
                )
    return sorted(low, key=lambda x: x["percent"])


def save_report(report: dict, output_path: str):
    """Save report to JSON file."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report saved to: {output_path}")


def print_summary(report: dict):
    """Print formatted summary."""
    print("\n" + "=" * 70)
    print("COVERAGE BASELINE REPORT")
    print("=" * 70)
    print(f"Timestamp: {report['timestamp']}")
    print(f"\nOverall Coverage: {report['overall_percent_covered']:.1f}%")

    print("\nCategory Breakdown:")
    print("-" * 70)
    for cat, data in report["categories"].items():
        if data["total_lines"] > 0:
            target = report["targets_check"].get(cat, {}).get("target", "N/A")
            status = "✅" if data["percent_covered"] >= target else "⚠️"
            print(
                f"  {status} {cat:15s} | {data['percent_covered']:6.1f}% (target: {target}%) | {data['file_count']} files"
            )

    print("\nTarget Compliance:")
    print("-" * 70)
    for cat, check in report["targets_check"].items():
        if cat == "overall_pass":
            continue
        status = "✅ PASS" if check["passed"] else "❌ FAIL"
        print(
            f"  {status} {cat:15s} | Target: {check['target']:3d}% | Actual: {check['actual']:6.1f}% | Gap: {check['gap']:.1f}%"
        )

    overall_status = (
        "✅ ALL TARGETS MET"
        if report["targets_check"]["overall_pass"]
        else "❌ SOME TARGETS MISSED"
    )
    print(f"\n{overall_status}")

    if report["low_coverage_files"]:
        print(f"\nLow Coverage Files (< 50%, >10 lines):")
        print("-" * 70)
        for f in report["low_coverage_files"][:20]:
            print(
                f"  ⚠️  {f['file']}: {f['percent']:.1f}% ({f['missing_lines_count']} missing)"
            )

    print("=" * 70)


def main():
    report = generate_report()
    print_summary(report)
    save_report(report, "reports/coverage_baseline.json")

    if not report["targets_check"]["overall_pass"]:
        print("\n⚠️  Some category targets not met. See details above.")
        return 1
    return 0


if __name__ == "__main__":
    exit(main())
