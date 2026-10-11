"""Temporary diagnostic: verify bare import no longer re-executes after conftest fix."""

import sys


def test_bare_import_no_reexecution():
    import src.audiobook_studio.schemas.quality as canonical

    canonical_id = id(canonical)
    canonical_qj = id(canonical.QualityJudgment)
    print(f"\ncanonical quality id={canonical_id}")

    # Force a fresh bare import by dropping the bare keys (as a test would see).
    for k in ("audiobook_studio.schemas.quality", "audiobook_studio.schemas"):
        sys.modules.pop(k, None)

    import audiobook_studio.schemas.quality as bare
    from audiobook_studio.schemas.quality import QualityJudgment as bare_qj  # noqa: F401

    print(f"bare quality id={id(bare)}, same: {id(bare) == canonical_id}")
    print(f"bare QJ id={id(bare_qj)}, same: {id(bare_qj) == canonical_qj}")
    print(
        f"src key id={id(sys.modules['src.audiobook_studio.schemas.quality'])}, same: {id(sys.modules['src.audiobook_studio.schemas.quality']) == canonical_id}"
    )

    assert id(bare) == canonical_id, "bare import re-executed the module (orphan created)"
    assert id(sys.modules["src.audiobook_studio.schemas.quality"]) == canonical_id, "src key was clobbered by orphan"
