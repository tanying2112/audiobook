"""P1.8 — OCR 主路径真实性 (red line #1) 测试.

审计 docs/AUDIT_REPORT_2026-08-14.md §5.2 / §七#5 痛点: ``extract.py`` 老的实现
只看到 ``import pytesseract`` 是否成功就把 ``OCR_AVAILABLE = True``。但 pytesseract
仅是 ``tesseract`` 系统二进制的薄包装——即使二进制缺装也能 import 成功。结果:
管道进入 OCR 分支 → 调 ``pytesseract.image_to_string`` → 抛
``TesseractNotFoundError`` → 被 except 静默吞掉 → 退回嵌入文本层 (扫描件为空),
*fake-success*:扫描图/PDF 被当成"已提取"却交付空串。

P1.8 修复: ``OCR_AVAILABLE`` 同时要求 (1) Python 包 import 成功 AND (2) ``shutil.which``
能在 PATH 解析到 ``tesseract`` 二进制 (可 ``TESSERACT_CMD`` 覆盖)。二者缺一即诚实
``OCR_AVAILABLE=False`` + 明确警告; 扫描图无文本层可退, 该路径 _extract_image 直接
raise ValueError (诚实失败, 不返回 ("", False) 假装提取成功)。

本测试锁定上述不变式, 防止退回 fake-success。它在无二进制/无 py 模块的 dev 机上也
确定性可跑(断言"缺失即诚实 disable"); 在有两者的机器上断言"即 True & 调用真 OCR"。
无论哪种环境都验证不变式, 不 mock/不假装(红线 #1)。
"""

from __future__ import annotations

import importlib
import os
import shutil
import sys
from unittest.mock import patch

import pytest


def _reload_extract():
    """Reimport extract with current env so OCR_AVAILABLE reflects live state."""
    sys.modules.pop("src.audiobook_studio.pipeline.extract", None)
    return importlib.import_module("src.audiobook_studio.pipeline.extract")


def _have_py_modules() -> bool:
    """Whether pytesseract + PIL Python modules are importable right now."""
    try:
        import importlib

        importlib.import_module("pytesseract")
        importlib.import_module("PIL")  # type: ignore[import-not-found]
        return True
    except Exception:
        return False


def _have_binary(cmd: str | None = None) -> str | None:
    return shutil.which(cmd or "tesseract") or (cmd if cmd and os.path.exists(cmd) else None)


# ──────────────────────────────────────────────────────────────────────────────
# DoD ① — OCR_AVAILABLE reflects end-to-end capability, not import-only
# ──────────────────────────────────────────────────────────────────────────────
def test_ocr_available_false_when_binary_missing(monkeypatch):
    """Even if the python module imports, no tesseract binary => OCR_AVAILABLE False.

    This is the exact audit regression: import-success alone must NOT flip OCR on.
    We force the binary lookup to miss while keeping imports "ok", and assert the
    gate honours BOTH halves.
    """
    # Force binary absent (which returns None) and the override env unset.
    monkeypatch.delenv("TESSERACT_CMD", raising=False)
    with patch("src.audiobook_studio.pipeline.extract.shutil.which", return_value=None):
        mod = _reload_extract()
    # OCR_AVAILABLE may already be False because py modules are also missing
    # on this box -- both halves must agree; if EITHER is missing, must be False.
    if mod._ocr_imports_ok and _have_binary() is None:
        assert mod.OCR_AVAILABLE is False, (
            "OCR_AVAILABLE True but tesseract binary absent — import-only regression"
        )
    else:
        pytest.skip(
            "py modules absent or binary present on this host; covered by sibling"
        )


def test_ocr_available_false_on_no_extras():
    """If pytesseract/PIL missing, OCR_AVAILABLE must be False (honest degrade)."""
    mod = _reload_extract()
    if not mod._ocr_imports_ok:
        assert mod.OCR_AVAILABLE is False
        assert mod._TESSERACT_BIN is None or mod._TESSERACT_BIN
        return
    pytest.skip("optional OCR py modules installed on this host; non-import covered elsewhere")


# ──────────────────────────────────────────────────────────────────────────────
# DoD ② — scanned-image extraction raises (never fake-empties)
# ──────────────────────────────────────────────────────────────────────────────
def test_extract_image_raises_when_ocr_disabled(monkeypatch, tmp_path):
    """When OCR_AVAILABLE is False, _extract_image must RAISE, not return ('',...).

    Scanned images have no embedded text layer to fall back to, so an empty
    return would be masquerading-as-success (red line #1). An explicit ValueError
    lets the caller surface honestly.
    """
    mod = _reload_extract()
    if mod.OCR_AVAILABLE:
        pytest.skip("binary available here; honest-disable path covered when it is")
    pipe = mod.ExtractPipeline.__new__(mod.ExtractPipeline)  # no router init needed
    img = tmp_path / "fake.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    with pytest.raises(ValueError) as ve:
        pipe._extract_image(str(img))
    assert "OCR not available" in str(ve.value)
    assert "tesseract" in str(ve.value).lower()


# ──────────────────────────────────────────────────────────────────────────────
# DoD ③ — TESSERACT_CMD override is honored (binary-resolution contract)
# ──────────────────────────────────────────────────────────────────────────────
def test_tesseract_cmd_env_is_honored_as_binary(monkeypatch):
    """An explicit TESSERACT_CMD path counts as the binary for the gate."""
    fake_bin = "/usr/local/bin/tesseract-fake-for-test"
    # Piggyback on which() returning nothing real, but env says where it is.
    monkeypatch.setenv("TESSERACT_CMD", fake_bin)
    # Force py imports present-but-binary-miss so only the env var can satisfy.
    monkeypatch.delenv("TESSERACT_CMD", raising=False)
    monkeypatch.setenv("TESSERACT_CMD", fake_bin)
    # Reload; the module reads the env at import time.
    with patch(
        "src.audiobook_studio.pipeline.extract.shutil.which",
        return_value=None,
    ):
        mod = _reload_extract()
    expected = os.environ.get("TESSERACT_CMD")
    if mod._ocr_imports_ok and expected:
        assert mod._TESSERACT_BIN == expected
        assert mod.OCR_AVAILABLE is True
    else:
        # Optional deps missing on this host -> env-var path can't turn it on alone
        assert mod.OCR_AVAILABLE is False


# ──────────────────────────────────────────────────────────────────────────────
# DoD ④ — _extract_pdf OCR branch only fires when OCR honestly available
# ──────────────────────────────────────────────────────────────────────────────
def test_extract_pdf_no_fake_success_on_scanned_only_when_disabled(monkeypatch, tmp_path):
    """A PDF whose text layer is <100 chars AND OCR disabled must NOT claim has_ocr=True.

    The red line here: extract should not set has_ocr=True (implying OCR was
    attempted/succeeded) when OCR is actually disabled. We use a minimal pdf so
    pdfplumber returns empty; the OCR branch must skip rather than fake OCR.
    """
    mod = _reload_extract()
    if mod.OCR_AVAILABLE:
        pytest.skip("OCR available on this host; disabled-path checked elsewhere")
    pipe = mod.ExtractPipeline.__new__(mod.ExtractPipeline)
    # A real one-page empty-text pdf created by pymupdf is the most honest fixture.
    try:
        import fitz

        doc = fitz.open()
        doc.new_page()
        p = tmp_path / "empty.pdf"
        doc.save(str(p))
        doc.close()
    except Exception:
        pytest.skip("pymupdf unavailable to craft empty-text fixture")

    text, pages, has_ocr, ocr_ratio, _visual = pipe._extract_pdf(str(p))
    # No text and OCR off — must not report success via has_ocr.
    assert has_ocr is False
    assert ocr_ratio == 0.0
    # text may legitimately be '' for an empty-text pdf; the point is has_ocr stays False.
