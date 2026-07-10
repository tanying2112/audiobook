#!/usr/bin/env python3
"""
Production Environment Pre-check Script for Audiobook Studio.

Pre-flight checks before running in production:
1. Required / recommended environment variables are present (not empty).
2. SQLite database is reachable and a connection can be opened.
3. Local disk has enough free space for runtime artifacts.

Design notes:
- Reads environment variables directly via ``os.getenv`` rather than going
  through the ``Settings`` (pydantic-settings) object. ``Settings`` supplies
  default values for missing variables, which would silently mask the very
  "variable is missing" condition this script exists to detect.
- Pure standard library: no third-party deps, so it can run in a fresh shell
  before the rest of the app is even importable.

Exit codes:
  0 - All checks passed.
  1 - One or more checks failed.
  2 - Critical/unexpected error during check execution.

Usage:
    python -m audiobook_studio.utils.env_checker
    python -m audiobook_studio.utils.env_checker --fail-on-warning

CLI:
    --fail-on-warning  Treat non-empty warnings (e.g. missing recommended env
                        vars) as a hard failure (exit 1). Used as a CI / container
                        health hard gate (see .github/workflows/ci.yml).
"""

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# Variables the service cannot start without. Absence is a hard error.
REQUIRED_ENV_VARS: List[str] = [
    "DATABASE_URL",
]

# Variables that most deployments want but whose absence only degrades
# optional features (queueing, TTS providers). Absence is a warning only.
RECOMMENDED_ENV_VARS: List[str] = [
    "REDIS_URL",
    "CELERY_BROKER_URL",
    "CELERY_RESULT_BACKEND",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
]

# Minimum free disk space in GB. Default is conservative; override via env.
DEFAULT_MIN_FREE_GB: float = 1.0
MIN_FREE_GB_ENV = "ENV_CHECK_MIN_FREE_GB"


class EnvCheckResult:
    """Accumulator for environment check outcomes."""

    def __init__(self) -> None:
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.results: Dict[str, bool] = {}


def _is_set(value: str | None) -> bool:
    """A variable counts as set only if it is non-None and non-empty."""
    return value is not None and value.strip() != ""


def check_env_vars(result: EnvCheckResult, required: List[str], recommended: List[str]) -> bool:
    """Verify required and recommended environment variables are set."""
    missing_required = [v for v in required if not _is_set(os.getenv(v))]
    missing_recommended = [v for v in recommended if not _is_set(os.getenv(v))]

    if missing_required:
        result.errors.append(f"Missing required environment variables: {', '.join(missing_required)}")
    if missing_recommended:
        result.warnings.append(f"Recommended environment variables not set: {', '.join(missing_recommended)}")

    ok = not missing_required
    result.results["env_vars"] = ok
    return ok


def _sqlite_path_from_url(db_url: str) -> Path | None:
    """Extract the filesystem path from a SQLite URL.

    Supports ``sqlite:///relative.db`` and ``sqlite:////absolute/path.db``.
    Returns None if the URL is not a recognized SQLite scheme.
    """
    prefix = "sqlite:///"
    if not db_url.startswith(prefix):
        return None
    # Everything after the prefix is the path. Leading slash preserved for
    # absolute paths (sqlite:////abs -> "/abs" after stripping prefix).
    return Path(db_url[len(prefix) :])


def check_database(result: EnvCheckResult, timeout_seconds: float = 5.0, test_query: str = "SELECT 1") -> bool:
    """Open a SQLite connection and run a trivial query to confirm reachability."""
    db_url = os.getenv("DATABASE_URL")
    if not _is_set(db_url):
        result.errors.append("DATABASE_URL not configured")
        result.results["database"] = False
        return False

    db_path = _sqlite_path_from_url(db_url)
    if db_path is None:
        result.errors.append(f"Unsupported DATABASE_URL scheme (need sqlite:///): {db_url}")
        result.results["database"] = False
        return False

    try:
        parent = db_path.parent
        if str(parent) and not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        result.errors.append(f"Cannot create database directory {parent}: {e}")
        result.results["database"] = False
        return False

    try:
        with sqlite3.connect(str(db_path), timeout=timeout_seconds) as conn:
            conn.execute(test_query)
    except sqlite3.Error as e:
        result.errors.append(f"Database connection failed ({db_path}): {e}")
        result.results["database"] = False
        return False

    result.results["database"] = True
    return True


def _free_gb_of(path: Path) -> float:
    """Return free space in GB at the filesystem containing ``path``."""
    stat = os.statvfs(path)
    free_bytes = stat.f_bavail * stat.f_frsize
    return free_bytes / (1024**3)


def check_disk_space(result: EnvCheckResult, min_free_gb: float) -> bool:
    """Confirm enough free space on the filesystems we will write to."""
    candidate_paths: List[Path] = [Path.cwd()]
    for env_name in ("DATA_DIR", "TMPDIR"):
        val = os.getenv(env_name)
        if val:
            candidate_paths.append(Path(val))

    db_url = os.getenv("DATABASE_URL")
    db_path = _sqlite_path_from_url(db_url) if _is_set(db_url) else None
    if db_path is not None:
        candidate_paths.append(db_path.parent)

    # Deduplicate by resolved path, dropping anything we can't resolve.
    unique: List[Path] = []
    seen = set()
    for p in candidate_paths:
        try:
            resolved = p.resolve()
        except OSError:
            continue
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)

    all_ok = True
    for path in unique:
        try:
            free_gb = _free_gb_of(path)
        except OSError as e:
            result.warnings.append(f"Could not check disk space on {path}: {e}")
            continue
        if free_gb < min_free_gb:
            result.errors.append(
                f"Insufficient disk space on {path}: {free_gb:.2f} GB free " f"(minimum {min_free_gb:.2f} GB required)"
            )
            all_ok = False

    result.results["disk_space"] = all_ok
    return all_ok


def _resolve_min_free_gb() -> float:
    raw = os.getenv(MIN_FREE_GB_ENV)
    if not raw:
        return DEFAULT_MIN_FREE_GB
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_MIN_FREE_GB


def run_all_checks(result: EnvCheckResult) -> Tuple[bool, Dict[str, bool]]:
    """Run every check in sequence and return (all_passed, results map)."""
    check_env_vars(result, REQUIRED_ENV_VARS, RECOMMENDED_ENV_VARS)
    check_database(result)
    check_disk_space(result, _resolve_min_free_gb())
    all_passed = all(result.results.values())
    return all_passed, result.results


def print_report(result: EnvCheckResult) -> None:
    width = 60
    print("=" * width)
    print("Audiobook Studio - Production Environment Pre-check")
    print("=" * width)

    for name, passed in result.results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {name:<20} {status}")

    if result.warnings:
        print("\nWarnings:")
        for w in result.warnings:
            print(f"  ! {w}")

    if result.errors:
        print("\nErrors:")
        for e in result.errors:
            print(f"  X {e}")

    print("=" * width)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audiobook Studio production environment pre-check " "(exit 0=ok, 1=failure, 2=critical).",
    )
    parser.add_argument(
        "--fail-on-warning",
        action="store_true",
        help="Treat any warning (e.g. missing recommended env vars) as a "
        "failure (exit 1). Used as a hard gate in CI and container health checks.",
    )
    args = parser.parse_args(argv)

    result = EnvCheckResult()
    try:
        all_passed, _ = run_all_checks(result)
        print_report(result)
        # Without --fail-on-warning: only hard errors (required vars / DB / disk)
        # drive the exit code; warnings are advisory.
        # With --fail-on-warning: any warning also flips the exit code to 1.
        if result.errors or (args.fail_on_warning and result.warnings):
            if result.errors:
                print("\nSome checks failed. Please review errors above.")
            else:
                print("\nFail-on-warning enabled: warnings treated as failures.")
            return 1
        if all_passed:
            print("\nAll checks passed. Environment is ready for production.")
            return 0
        return 1
    except Exception as e:
        print(f"\nCritical error during environment check: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
