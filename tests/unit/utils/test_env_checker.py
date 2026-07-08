"""Tests for env_checker production pre-flight script."""

import sqlite3
import sys
from pathlib import Path

import pytest

from src.audiobook_studio.utils import env_checker
from src.audiobook_studio.utils.env_checker import (
    EnvCheckResult,
    _is_set,
    _sqlite_path_from_url,
    check_database,
    check_disk_space,
    check_env_vars,
    main,
    run_all_checks,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_is_set_none(self):
        assert _is_set(None) is False

    def test_is_set_empty(self):
        assert _is_set("") is False

    def test_is_set_whitespace(self):
        assert _is_set("   ") is False

    def test_is_set_value(self):
        assert _is_set("value") is True

    def test_sqlite_path_relative(self):
        assert _sqlite_path_from_url("sqlite:///app.db") == Path("app.db")

    def test_sqlite_path_absolute(self):
        assert _sqlite_path_from_url("sqlite:////var/data/app.db") == Path("/var/data/app.db")

    def test_sqlite_path_non_sqlite(self):
        assert _sqlite_path_from_url("postgres://localhost/db") is None

    def test_sqlite_path_empty(self):
        # sqlite:/// with no path -> empty Path
        assert _sqlite_path_from_url("sqlite:///") == Path("")


# ---------------------------------------------------------------------------
# check_env_vars
# ---------------------------------------------------------------------------


class TestCheckEnvVars:
    def test_all_required_present(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")
        result = EnvCheckResult()
        assert check_env_vars(result, required=["DATABASE_URL"], recommended=[]) is True
        assert result.results["env_vars"] is True
        assert result.errors == []

    def test_missing_required_fails(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        result = EnvCheckResult()
        assert check_env_vars(result, required=["DATABASE_URL"], recommended=[]) is False
        assert result.results["env_vars"] is False
        assert any("Missing required" in e for e in result.errors)

    def test_empty_required_fails(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "   ")
        result = EnvCheckResult()
        assert check_env_vars(result, required=["DATABASE_URL"], recommended=[]) is False
        assert result.errors

    def test_missing_recommended_warns_only(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")
        monkeypatch.delenv("REDIS_URL", raising=False)
        result = EnvCheckResult()
        # required passes, recommended missing -> warning, not error
        assert check_env_vars(result, required=["DATABASE_URL"], recommended=["REDIS_URL"]) is True
        assert any("REDIS_URL" in w for w in result.warnings)
        assert result.errors == []

    def test_multiple_missing_required_listed(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("SECRET_KEY", raising=False)
        result = EnvCheckResult()
        check_env_vars(result, required=["DATABASE_URL", "SECRET_KEY"], recommended=[])
        msg = result.errors[0]
        assert "DATABASE_URL" in msg
        assert "SECRET_KEY" in msg


# ---------------------------------------------------------------------------
# check_database
# ---------------------------------------------------------------------------


class TestCheckDatabase:
    def test_successful_connection(self, tmp_path, monkeypatch):
        db = tmp_path / "app.db"
        # Pre-create the DB so the table exists
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE t (id INTEGER)")
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
        result = EnvCheckResult()
        assert check_database(result) is True
        assert result.results["database"] is True
        assert result.errors == []

    def test_creates_db_if_missing(self, tmp_path, monkeypatch):
        db = tmp_path / "fresh.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
        result = EnvCheckResult()
        assert check_database(result) is True
        assert db.exists()

    def test_missing_database_url_fails(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        result = EnvCheckResult()
        assert check_database(result) is False
        assert any("DATABASE_URL not configured" in e for e in result.errors)

    def test_unsupported_scheme_fails(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgres://localhost/db")
        result = EnvCheckResult()
        assert check_database(result) is False
        assert any("Unsupported" in e for e in result.errors)

    def test_creates_parent_directory(self, tmp_path, monkeypatch):
        nested = tmp_path / "deep" / "nest" / "app.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{nested}")
        result = EnvCheckResult()
        assert check_database(result) is True
        assert nested.parent.exists()


# ---------------------------------------------------------------------------
# check_disk_space
# ---------------------------------------------------------------------------


class TestCheckDiskSpace:
    def test_passes_when_threshold_low(self, tmp_path, monkeypatch):
        # Real tmp_path has plenty of space; require 0 GB -> always passes
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        result = EnvCheckResult()
        assert check_disk_space(result, min_free_gb=0.0) is True
        assert result.results["disk_space"] is True
        assert result.errors == []

    def test_fails_when_threshold_huge(self, tmp_path, monkeypatch):
        # Require an absurd amount of space -> always fails
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        result = EnvCheckResult()
        assert check_disk_space(result, min_free_gb=1_000_000.0) is False
        assert result.results["disk_space"] is False
        assert any("Insufficient disk space" in e for e in result.errors)

    def test_deduplicates_paths(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        monkeypatch.setenv("TMPDIR", str(tmp_path))  # same as DATA_DIR
        result = EnvCheckResult()
        check_disk_space(result, min_free_gb=0.0)
        # Various envs pointing to the same resolved path must not double-report
        assert result.errors == []


# ---------------------------------------------------------------------------
# run_all_checks / main
# ---------------------------------------------------------------------------


class TestRunAllChecks:
    def test_all_pass(self, tmp_path, monkeypatch):
        db = tmp_path / "app.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
        monkeypatch.delenv("REDIS_URL", raising=False)
        result = EnvCheckResult()
        all_passed, results = run_all_checks(result)
        # env_vars + database + disk_space all pass (REDIS only a warning)
        assert all_passed is True
        assert results["env_vars"] is True
        assert results["database"] is True
        assert results["disk_space"] is True

    def test_missing_db_url_fails_overall(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        result = EnvCheckResult()
        all_passed, results = run_all_checks(result)
        assert all_passed is False
        assert results["env_vars"] is False
        assert results["database"] is False


class TestMain:
    def test_main_success_exit_zero(self, tmp_path, monkeypatch):
        db = tmp_path / "app.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
        monkeypatch.delenv("REDIS_URL", raising=False)
        rc = main()
        assert rc == 0

    def test_main_failure_exit_one(self, monkeypatch, capsys):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        rc = main()
        assert rc == 1
        captured = capsys.readouterr()
        assert "FAIL" in captured.out

    def test_main_critical_error_exit_two(self, monkeypatch):
        # Force run_all_checks to raise -> critical error path
        def boom(_result):
            raise RuntimeError("boom")

        monkeypatch.setattr(env_checker, "run_all_checks", boom)
        rc = main()
        assert rc == 2


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
