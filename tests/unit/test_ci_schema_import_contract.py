"""Static contract regression for the llm_quality_gate schema-load check.

``.github/workflows/llm_quality_gate.yml`` has a "Validate all Pydantic schemas
load" step that does ``from src.audiobook_studio.schemas import (...)`` with a
hard-coded name sample. Three of those names were long-standing phantoms that
never existed on the public ``schemas`` surface (``ChapterAnalysis``,
``CharacterInfo``, ``QualityReport``) → ``ImportError`` → the step stayed red on
``main`` indefinitely (legacy, pre-dating this work).

The fix swaps each phantom for the real schema exported from the same sub-area:
``ChapterAnalysis`` → ``ChapterSource``, ``CharacterInfo`` →
``CharacterVoiceBinding``, ``QualityReport`` → ``QualityJudgment``.

We pin the contract WITHOUT importing the venv: the YAML import list is
string-scanned, and the real ``schemas.__all__`` is parsed via AST from
``schemas/__init__.py`` (mirrors ``test_locustfile_contract.py``'s no-import
philosophy). A future edit that re-introduces a phantom name fails this gate
before it can redden CI.
"""

import ast
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_YML = _REPO / ".github" / "workflows" / "llm_quality_gate.yml"
_SCHEMAS_INIT = _REPO / "src" / "audiobook_studio" / "schemas" / "__init__.py"

# The three phantoms that reddened CI; none were ever a class in schemas/.
_PHANTOMS = {"ChapterAnalysis", "CharacterInfo", "QualityReport"}
# Their real same-sub-area replacements (verified exported classes).
_REAL_REPLACEMENTS = {"ChapterSource", "CharacterVoiceBinding", "QualityJudgment"}


def _import_block_names() -> list[str]:
    """Names listed in the CI `from src.audiobook_studio.schemas import (...)`."""
    txt = _YML.read_text(encoding="utf-8")
    m = re.search(r"from src\.audiobook_studio\.schemas import \(([^)]*)\)", txt, re.S)
    assert m, "schemas import block not found in llm_quality_gate.yml"
    names: list[str] = []
    for line in m.group(1).splitlines():
        tok = line.strip().rstrip(",")
        if tok and re.fullmatch(r"[A-Za-z_]\w*", tok):
            names.append(tok)
    return names


def _schemas_all() -> set[str]:
    """The real public surface from schemas/__init__.py __all__ (AST, no import)."""
    tree = ast.parse(_SCHEMAS_INIT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "__all__":
                    if isinstance(node.value, ast.List):
                        return {
                            elt.value
                            for elt in node.value.elts
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                        }
    return set()


def test_schemas_import_block_exists_and_has_names() -> None:
    names = _import_block_names()
    assert len(names) >= 8, f"sample too thin: {names}"
    # the known-good names that were already correct must survive the edit
    for required in (
        "ExtractionInput",
        "ExtractionResult",
        "BookAnalysisOutput",
        "EmotionSnapshot",
        "ParagraphAnnotation",
        "TtsRoutingInput",
        "TtsRoutingDecision",
    ):
        assert required in names, f"real schema dropped from sample: {required}"


def test_every_ci_imported_name_is_on_the_public_surface() -> None:
    names = set(_import_block_names())
    real = _schemas_all()
    missing = names - real
    assert not missing, (
        f"CI imports non-existent schema name(s) {missing}; "
        f"must all be in schemas/__init__.py __all__"
    )


def test_phantom_schema_names_are_gone() -> None:
    """The three names that reddened CI must never reappear."""
    names = set(_import_block_names())
    leaked = _PHANTOMS & names
    assert not leaked, f"phantom schema name(s) re-introduced: {leaked}"


def test_real_replacement_names_are_present() -> None:
    """The three real same-sub-area schemas are in the sample."""
    names = set(_import_block_names())
    missing = _REAL_REPLACEMENTS - names
    assert not missing, f"real replacement schema(s) missing: {missing}"


def test_no_duplicate_names_in_sample() -> None:
    names = _import_block_names()
    assert len(names) == len(set(names)), f"duplicate name(s): {names}"
