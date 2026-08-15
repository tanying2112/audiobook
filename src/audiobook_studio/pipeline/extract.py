"""Pipeline Stage 1: Extract - Text extraction with OCR/language detection.

Supports PDF, EPUB, DOCX, TXT, and image formats (PNG, JPG, TIFF, BMP, WebP) with OCR.
Outputs ExtractionResult with raw_text, language, page stats, OCR info.
"""

import logging
import os
import time
from pathlib import Path
from typing import Any, Literal, Optional

import fitz  # pymupdf
import pdfplumber
from docx import Document
from ebooklib import epub

from ..llm import LLMRouter, create_router
from ..monitoring import record_stage_performance
from ..schemas import ExtractionInput, ExtractionResult

logger = logging.getLogger(__name__)

# MIME types accepted by ExtractionInput.mime_type. Kept in sync with the
# Literal in schemas/extraction.py (ExtractionInput.mime_type); widening to a
# bare ``str`` would let unsupported values through silently.
ExtractMimeType = Literal[
    "application/pdf",
    "application/epub+zip",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/tiff",
    "image/bmp",
    "image/webp",
]

# Optional OCR dependencies.
#
# Red line #1 (主路径真实性): ``OCR_AVAILABLE`` MUST reflect whether OCR can
# ACTUALLY run end-to-end, not merely whether the ``pytesseract`` Python module
# imports. ``pytesseract`` is only a thin wrapper around the ``tesseract``
# SYSTEM BINARY — the import succeeds even when the binary is absent, so the
# previous form (``OCR_AVAILABLE = True`` on import success) let the pipeline
# enter the OCR branch, call ``pytesseract.image_to_string`` -- which raises
# ``TesseractNotFoundError`` -- then silently swallowed the error at line ~101
# and fell back to the embedded text layer as if OCR had been attempted, i.e.
# *fake-success* on scanned/image-only PDFs (audit §5.2 / §七#5).
#
# The fix: require BOTH the Python module import AND a resolvable ``tesseract``
# binary on PATH (``shutil.which``); only then claim OCR is available. When the
# binary is missing, honest-disable OCR and log a clear, actionable message so
# callers know scanned-image extraction is degraded to embedded-text-layer
# only -- never masquerade. (tesseract is free / Apache-2.0; install via
# ``apt-get install tesseract-ocr tesseract-ocr-chi-sim`` on Debian/Ubuntu,
# ``brew install tesseract tesseract-lang`` on macOS; also add to the
# Dockerfile RUN line and requirements.in -- see P1.8.)
import shutil

# Module-level imports of the optional deps. Bound under the SAME names the
# call sites use (``pytesseract``, ``Image``) so the OCR branch is unchanged when
# OCR is genuinely available. ``OCR_AVAILABLE`` gates those call sites.
pytesseract = None  # type: Optional[Any]
Image = None  # type: Optional[Any]
_ocr_imports_ok = False

try:
    import pytesseract  # noqa: F811
    from PIL import Image  # noqa: F811

    _ocr_imports_ok = True
except ImportError:
    _ocr_imports_ok = False

# Resolve the ``tesseract`` binary, honoring an explicit override
# (``TESSERACT_CMD`` env) the same way the pytesseract wrapper does.
_TESSERACT_BIN = os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")

if _ocr_imports_ok and _TESSERACT_BIN:
    OCR_AVAILABLE = True
else:
    OCR_AVAILABLE = False
    if not _ocr_imports_ok:
        logger.warning(
            "OCR disabled: pytesseract/Pillow Python modules not installed "
            "(pip install pytesseract pillow). Scanned-image/PDF OCR "
            "unavailable; only embedded-text-layer extraction runs."
        )
    elif not _TESSERACT_BIN:
        logger.warning(
            "OCR disabled: the `tesseract` system binary was not found on PATH "
            "(pytesseract is only a wrapper). Install tesseract + chi_sim "
            "(apt-get install tesseract-ocr tesseract-ocr-chi-sim / "
            "brew install tesseract tesseract-lang) to enable scanned-image "
            "OCR. Until then, scanned/image-only inputs degrade honestly to "
            "empty/best-effort embedded-text-layer text——NOT fake-success."
        )


class ExtractPipeline:
    """Pipeline for text extraction from various formats."""

    def __init__(self, router: Optional[LLMRouter] = None, mock_mode: Optional[bool] = None):
        # Default mock_mode from environment if not specified
        if mock_mode is None:
            self.mock_mode = os.environ.get("MOCK_LLM", "false").lower() == "true"
        else:
            self.mock_mode = mock_mode

        # Create router (mock mode passed directly to avoid thread-unsafe env manipulation)
        if router is None:
            self.router = create_router(mock_mode=self.mock_mode)
        else:
            self.router = router

    def _extract_pdf(self, file_path: str) -> tuple[str, int, bool, float]:
        """Extract text from PDF using pdfplumber, fallback to PyMuPDF + pytesseract OCR."""
        text_parts = []
        page_count = 0
        has_ocr = False
        ocr_pages = 0

        # Try pdfplumber first (text layer)
        try:
            with pdfplumber.open(file_path) as pdf:
                page_count = len(pdf.pages)
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
        except Exception as e:
            logger.warning(f"pdfplumber failed: {e}")

        extracted_text = "\n\n".join(text_parts).strip()

        # If text too short, try OCR. Red line #1 (主路径真实性): ``has_ocr`` and
        # ``ocr_pages`` MUST reflect OCR that actually *ran and produced text*,
        # not "the OCR branch was entered". The previous form set
        # ``has_ocr = True`` unconditionally here and counted dict-block text as
        # OCR pages even when ``OCR_AVAILABLE`` was False -- i.e. claiming OCR on
        # scanned PDFs that simply returned embedded-text-layer fragments (audit
        # §5.2 / §七#5). We now: only attempt OCR when it is honestly available;
        # when it is not, fall through cleanly with has_ocr=False/ocr_pages=0
        # (the embedded text layer was already extracted by pdfplumber above;
        # nothing further to do here that would be real OCR).
        if len(extracted_text) < 100 and OCR_AVAILABLE:
            logger.info("Text layer insufficient, attempting OCR with PyMuPDF + pytesseract")
            # OCR_AVAILABLE is only True when both modules imported; narrow for the
            # type checker so the call sites below are not flagged union-attr.
            assert Image is not None and pytesseract is not None
            try:
                doc = fitz.open(file_path)
                page_count = len(doc)
                ocr_text_parts = []
                for page_num in range(len(doc)):
                    page = doc[page_num]
                    # Render page to image and OCR it
                    pix = page.get_pixmap(dpi=200)

                    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    # Use pytesseract for OCR
                    page_text = pytesseract.image_to_string(img, lang="chi_sim+eng")

                    if page_text.strip():
                        ocr_text_parts.append(page_text)
                        ocr_pages += 1
                if ocr_text_parts:
                    extracted_text = "\n\n".join(ocr_text_parts).strip()
                    # OCR genuinely contributed content -- only now assert has_ocr.
                    has_ocr = True
                doc.close()
            except Exception as e:
                logger.error(f"PyMuPDF OCR failed: {e}")
        elif len(extracted_text) < 100 and not OCR_AVAILABLE:
            # Honest degradation: text layer is thin AND OCR cannot run in this
            # environment. We do NOT fabricate OCR; leave has_ocr=False so the
            # downstream report reflects "embedded-text-layer only".
            logger.info(
                "Text layer insufficient and OCR unavailable (tesseract binary "
                "or pytesseract missing) -- returning embedded-text-layer text "
                "only; has_ocr stays False (no fake OCR claim)."
            )

        ocr_ratio = ocr_pages / page_count if page_count > 0 else 0.0
        return extracted_text, page_count, has_ocr, ocr_ratio

    def _extract_epub(self, file_path: str) -> tuple[str, int, bool, float]:
        """Extract text from EPUB."""
        text_parts = []
        # Common EPUB document media types
        DOCUMENT_TYPES = {
            "application/xhtml+xml",
            "text/html",
            "application/x-dtbncx+xml",
        }
        try:
            book = epub.read_epub(file_path)
            for item in book.get_items():
                if item.get_type() in DOCUMENT_TYPES:
                    from bs4 import BeautifulSoup

                    soup = BeautifulSoup(item.get_content(), "html.parser")
                    text_parts.append(soup.get_text())
        except Exception as e:
            logger.error(f"EPUB extraction failed: {e}")
        return "\n\n".join(text_parts).strip(), len(text_parts), False, 0.0

    def _extract_docx(self, file_path: str) -> tuple[str, int, bool, float]:
        """Extract text from DOCX."""
        text_parts = []
        try:
            doc = Document(file_path)
            for para in doc.paragraphs:
                if para.text.strip():
                    text_parts.append(para.text)
        except Exception as e:
            logger.error(f"DOCX extraction failed: {e}")
        return "\n\n".join(text_parts).strip(), len(text_parts), False, 0.0

    def _extract_txt(self, file_path: str) -> tuple[str, int, bool, float]:
        """Extract text from plain text file."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
            return text.strip(), 1, False, 0.0
        except UnicodeDecodeError:
            with open(file_path, "r", encoding="gbk") as f:
                text = f.read()
            return text.strip(), 1, False, 0.0

    def _extract_image(self, file_path: str) -> tuple[str, int, bool, float]:
        """Extract text from image using OCR (requires pytesseract + Pillow + tesseract binary)."""
        if not OCR_AVAILABLE:
            # Red line #1: honest failure, not fake-success. A scanned image has
            # NO embedded text layer to fall back to, so returning ("", False)
            # would be masquerading-as-success. Raise so the caller can decide
            # how to surface it.
            raise ValueError(
                "Image OCR not available. Install the pytesseract Python module "
                "(pip install pytesseract pillow) AND the tesseract system binary "
                "(apt-get install tesseract-ocr tesseract-ocr-chi-sim / "
                "brew install tesseract tesseract-lang). extract.py reports OCR "
                "available only when BOTH are present."
            )

        # OCR_AVAILABLE is True => both modules imported; narrow for the type
        # checker so the call sites below are not flagged union-attr.
        assert Image is not None and pytesseract is not None

        try:
            image = Image.open(file_path)
            # Convert to RGB if needed (for RGBA images)
            if image.mode != "RGB":
                image = image.convert("RGB")

            # Use pytesseract for OCR
            text = pytesseract.image_to_string(image, lang="chi_sim+eng")

            return text.strip(), 1, True, 1.0
        except Exception as e:
            logger.error(f"Image OCR failed: {e}")
            return "", 1, False, 0.0

    def _detect_language(self, text: str) -> str:
        """Simple language detection."""
        # In production: use langdetect or fasttext
        chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        total_chars = len([c for c in text if c.isalpha()])
        if total_chars == 0:
            return "zh"
        return "zh" if chinese_chars / total_chars > 0.3 else "en"

    def run(self, input_data: ExtractionInput) -> ExtractionResult:
        """Execute extraction pipeline."""
        start_time = time.time()
        logger.info(f"Starting extraction: {input_data.file_path}")

        # MOCK: 待真实实现
        # Mock mode: return simulated result
        if self.mock_mode:
            mock_text = "用于测试的模拟提取文本。这是模拟数据，用于测试 extract 功能。" * 10

            # Record mock performance
            record_stage_performance(
                stage="extract_mock",
                latency_ms=int((time.time() - start_time) * 1000),
                tokens_in=10,
                tokens_out=100,
                cost_usd=0.0,
                success=True,
                quality_score=1.0,
                provider="mock",
                model="mock_model",
                schema_compliance=True,
            )

            return ExtractionResult(
                raw_text=mock_text,
                language="zh",
                page_count=5,
                has_ocr=False,
                ocr_page_ratio=0.0,
                warnings=[],
            )

        file_path = input_data.file_path
        mime_type = input_data.mime_type
        warnings = []

        # Route to appropriate extractor
        if mime_type == "application/pdf":
            raw_text, page_count, has_ocr, ocr_ratio = self._extract_pdf(file_path)
        elif mime_type == "application/epub+zip":
            raw_text, page_count, has_ocr, ocr_ratio = self._extract_epub(file_path)
        elif mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            raw_text, page_count, has_ocr, ocr_ratio = self._extract_docx(file_path)
        elif mime_type == "text/plain":
            raw_text, page_count, has_ocr, ocr_ratio = self._extract_txt(file_path)
        elif mime_type in (
            "image/png",
            "image/jpeg",
            "image/jpg",
            "image/tiff",
            "image/bmp",
            "image/webp",
        ):
            raw_text, page_count, has_ocr, ocr_ratio = self._extract_image(file_path)
        else:
            raise ValueError(f"Unsupported MIME type: {mime_type}")

        if not raw_text or len(raw_text) < 50:
            warnings.append("Extracted text too short, may need manual review")

        language = self._detect_language(raw_text) if input_data.detect_language else "zh"

        # Calculate extraction metrics
        extraction_time_ms = (time.time() - start_time) * 1000

        # Estimate token usage for extraction
        # Input: file (we'll approximate by file size or just use 0 for now)
        # Output: extracted text
        input_chars = 0  # Hard to estimate input without reading file twice
        output_chars = len(raw_text)

        # Rough approximation: 1 token ≈ 4 characters
        tokens_in = max(1, input_chars // 4)
        tokens_out = max(1, output_chars // 4)

        # Estimate cost (extraction is mostly free/local, except for OCR which might use API)
        # For simplicity, we'll use a small constant cost
        cost_usd = 0.001  # Placeholder for extraction cost

        # Determine if OCR was used (might indicate API usage in real implementation)
        provider = "ocr" if has_ocr else "local"
        if provider == "ocr":
            # If OCR was used, might have used a paid API
            cost_usd = 0.005  # Slightly higher for OCR

        # Record extraction performance
        record_stage_performance(
            stage=f"extract_{provider}",
            latency_ms=extraction_time_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            success=bool(raw_text and len(raw_text) >= 50),  # Success if we got reasonable text
            quality_score=(1.0 if (raw_text and len(raw_text) >= 50) else 0.5),  # Quality based on text length
            provider=provider,
            model="unknown",
            schema_compliance=None,
        )

        return ExtractionResult(
            raw_text=raw_text,
            language=language,
            page_count=page_count,
            has_ocr=has_ocr,
            ocr_page_ratio=ocr_ratio,
            warnings=warnings,
        )


def extract_text(
    file_path: str,
    mime_type: ExtractMimeType,
    detect_language: bool = True,
    mock_mode: Optional[bool] = None,
) -> ExtractionResult:
    """Convenience function for text extraction."""
    input_data = ExtractionInput(
        file_path=file_path,
        mime_type=mime_type,
        detect_language=detect_language,
    )
    pipeline = ExtractPipeline(mock_mode=mock_mode)
    return pipeline.run(input_data)


if __name__ == "__main__":  # pragma: no cover
    import sys
    from typing import cast

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 3:
        logger.info("Usage: python extract.py <file_path> <mime_type>")
        sys.exit(1)

    # ``sys.argv[2]`` is runtime ``str`` from the shell; we cannot statically
    # prove it is one of the accepted MIME literals, so cast the CLI boundary
    # value (ExtractionInput will still validate it).
    result = extract_text(sys.argv[1], cast(ExtractMimeType, sys.argv[2]))
    logger.info(f"Language: {result.language}")
    logger.info(f"Pages: {result.page_count}")
    logger.info(f"OCR: {result.has_ocr} ({result.ocr_page_ratio:.1%})")
    logger.info(f"Text preview: {result.raw_text[:200]}...")
