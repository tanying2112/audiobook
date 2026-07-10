"""Import-safety regression for the feedback package.

``dspy`` is a heavy, *optional* runtime dependency used only by the
BootstrapFewShot prompt optimiser (``feedback/bootstrap_fewshot.py``). It is not
declared in ``requirements.txt`` / ``pyproject.toml`` and is therefore absent
from a clean install — most notably the production Docker image, which only
installs listed deps.

Before the fix, ``audiobook_studio/__init__.py`` eagerly imported
``feedback.bootstrap_fewshot`` which does ``import dspy`` at module top, so every
entrypoint that touches the package (``python -m audiobook_studio.main`` for the
web server, ``celery -A audiobook_studio.celery_app`` for the worker, and
``env_checker``) died with ``ModuleNotFoundError: No module named 'dspy'`` on a
clean install. The local dev venv masked this because dspy was hand-installed
there; only a real ``docker build`` surfaced it.

These tests run ``audiobook_studio`` import in an isolated subprocess with
``import dspy`` blocked, mirroring a clean install. This neither pollutes the
pytest process' ``sys.modules`` cache nor depends on whether dspy happens to be
installed on the dev/CI machine.
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

_HERE = Path(__file__).resolve()
_SRC = _HERE.parents[2] / "src"

# Public optimiser symbols the feedback package must keep re-exporting, but only
# loaded on first access (lazy), so a bare import never touches dspy.
_LAZY_OPTIMISER_NAMES = frozenset(
    {
        "BUDGET_LIMIT",
        "DEFAULT_EARLY_STOP_PATIENCE",
        "BootstrapFewShotOptimizer",
        "EarlyStoppingStopper",
        "MultiObjectiveLoss",
        "OptimizationMetrics",
        "OptimizationResult",
        "load_training_examples",
        "run_bootstrap_optimization",
    }
)


def _run_with_dspy_blocked(script: str) -> subprocess.CompletedProcess[str]:
    """Exec ``script`` in a fresh interpreter with ``import dspy`` blocked.

    Blocks ``dspy`` and any ``dspy.*`` submodule identically to them being absent
    on a clean install. The subprocess inherits the parent env plus the project
    ``src`` dir on PYTHONPATH so ``audiobook_studio`` is importable.
    """
    launcher = textwrap.dedent(
        """
        import builtins

        _real_import = builtins.__import__


        def _block_dspy(name, *args, **kwargs):
            if name == "dspy" or name.startswith("dspy."):
                raise ModuleNotFoundError(f"No module named {name!r}")
            return _real_import(name, *args, **kwargs)


        builtins.__import__ = _block_dspy
        """
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(_SRC), env.get("PYTHONPATH", "")])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-c", launcher + script],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_import_audiobook_studio_without_dspy() -> None:
    """``import audiobook_studio`` must succeed even when dspy is unimportable.

    Regression for the original defect: the package top-level eagerly reached
    into the DSPy-backed optimiser, so a clean install crashed on import.
    """
    script = textwrap.dedent(
        """
        import audiobook_studio
        print("import-ok", audiobook_studio.__name__)
        """
    )
    result = _run_with_dspy_blocked(script)
    assert result.returncode == 0, "import audiobook_studio crashed when dspy was blocked:\n" + result.stderr
    assert "import-ok" in result.stdout


def test_feedback_export_symbols_lazy_on_dspy() -> None:
    """The optimiser re-exports stay public but load lazily.

    A bare ``import audiobook_studio.feedback`` must not trigger dspy; accessing
    an optimiser symbol must surface the missing dep as a clear
    ``ModuleNotFoundError`` (so users who actually run optimisation still get an
    honest error, while the package import stays cheap and optional-free).
    """
    script = textwrap.dedent(
        """
        import audiobook_studio.feedback as fb
        # importing the package must NOT have pulled dspy in
        import sys
        assert "dspy" not in sys.modules, "dspy was eagerly imported by feedback"
        # accessing a heavy optimiser symbol must raise the missing-dep error
        try:
            fb.run_bootstrap_optimization
            print("access-no-error")
        except ModuleNotFoundError as exc:
            print("dspy-required")
        """
    )
    result = _run_with_dspy_blocked(script)
    assert result.returncode == 0, "import audiobook_studio.feedback crashed when dspy was blocked:\n" + result.stderr
    assert "dspy-required" in result.stdout, (
        "expected the optimiser symbol access to surface the missing dspy dep, " "got: " + result.stdout
    )


def test_all_lazy_optimiser_names_reachable_when_dspy_present() -> None:
    """When dspy IS available, every lazy symbol resolves (no public API lost).

    Guards against the lazy __getattr__ accidentally dropping a name from
    __all__ — they must all still resolve once dspy is installed.
    """
    script = "\n".join(
        [
            "import audiobook_studio.feedback as fb",
            "missing = [n for n in %r if not hasattr(fb, n)]" % sorted(_LAZY_OPTIMISER_NAMES),
            "print('missing=' + repr(missing))",
        ]
    )
    # NOTE: not blocking dspy here — this asserts resolvability on a dev machine
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(_SRC), env.get("PYTHONPATH", "")])
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "missing=[]" in result.stdout, "lazy re-export dropped public symbols: " + result.stdout
