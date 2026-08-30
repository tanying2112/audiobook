"""Pipeline Stage 1: Extract - Text extraction with OCR/language detection.

Supports PDF, EPUB, DOCX, TXT, and image formats (PNG, JPG, TIFF, BMP, WebP) with OCR.
Outputs ExtractionResult with raw_text, language, page stats, OCR info.
"""

import io
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
from ..pipeline.progress_emitter import emit_stage_enter, emit_stage_exit, emit_stage_progress
from ..schemas import ExtractionInput, ExtractionResult, VisualElement

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

__all__ = [
    "ExtractPipeline",
    "ExtractMimeType",
    "ExtractionResult",
    "ExtractionInput",
    "VisualElement",
    "OCR_AVAILABLE",
]

# Optional OCR dependencies.

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

        # 多模态视觉客户端 (Task 4) — 懒加载，无视觉提供方时 understand_image 返回 None。
        self._vision_client = None
        self._vision_checked = False

    # ── 多模态视觉理解 (Task 4) ──────────────────────────────────────────────
    def _get_vision_client(self):
        """懒加载并缓存 MultimodalVisionClient（尊重 self.mock_mode）。"""
        # getattr 防御：兼容经 __new__ 跳过 __init__ 的实例（测试/反序列化场景）
        if not getattr(self, "_vision_checked", False):
            self._vision_checked = True
            from .vision import MultimodalVisionClient

            self._vision_client = MultimodalVisionClient(mock_mode=getattr(self, "mock_mode", False))
        return getattr(self, "_vision_client", None)

    def _understand_image_bytes(self, image_bytes: bytes, media_type: Optional[str] = None):
        """对一张图像做多模态理解；无视觉提供方/失败时返回 None（诚实降级）。"""
        client = self._get_vision_client()
        try:
            return client.understand_image(image_bytes, media_type=media_type)
        except Exception as e:  # noqa: BLE001 — 视觉失败不影响文本提取主流程
            logger.warning(f"Vision understanding failed (degraded): {e}")
            return None

    @staticmethod
    def _merge_visual_into_text(raw_text: str, elements: list[VisualElement]) -> str:
        """把视觉元素并入 raw_text，供下游章节拆分/分段/分析可见。

        有 caption/extracted_text 的图以 [插图: ...] 块标记追加，避免与正文混读。
        """
        if not elements:
            return raw_text
        parts = [raw_text] if raw_text else []
        for el in elements:
            block = f"\n[插图: {el.caption}]\n{el.extracted_text}".strip()
            if block:
                parts.append(block)
        return "\n\n".join(p for p in parts if p)

    def _extract_pdf(self, file_path: str) -> tuple[str, int, bool, float, list[VisualElement]]:
        """Extract text from PDF.

        Path order (S2.4 — OCR honesty):
          1. Embedded text layer via pdfplumber (ALWAYS attempted).
          2. If pdfplumber fails, fall back to PyMuPDF (fitz) for text layer.
          3. If the text layer is too thin AND the ``tesseract`` binary +
             ``pytesseract``/``Pillow`` are genuinely available (``OCR_AVAILABLE``),
             run real OCR with PyMuPDF + pytesseract.
          4. Otherwise we degrade HONESTLY to text-layer-only extraction
             (``has_ocr=False``). We never claim OCR ran when it could not.

        NOTE: the OCR path is opt-in. When tesseract is not installed the
        pipeline is "text-layer extraction only" — see the module-level
        ``OCR_AVAILABLE`` gate and the warnings logged at import time.
        """
        text_parts = []
        page_count = 0
        has_ocr = False
        ocr_pages = 0

        # Try pdfplumber first (text layer)
        pdfplumber_succeeded = False
        try:
            with pdfplumber.open(file_path) as pdf:
                page_count = len(pdf.pages)
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
            pdfplumber_succeeded = True
        except Exception as e:
            logger.warning(f"pdfplumber failed: {e}")

        extracted_text = "\n\n".join(text_parts).strip()

        # If pdfplumber failed or got no text, fall back to PyMuPDF (fitz) for text layer
        # This gives us page count and any embedded text even when OCR is not available
        if not pdfplumber_succeeded or len(extracted_text) < 100:
            try:
                doc = fitz.open(file_path)
                page_count = len(doc)
                if not pdfplumber_succeeded:
                    # Try to extract text from fitz as fallback
                    for page_num in range(len(doc)):
                        page = doc[page_num]
                        page_text = page.get_text()
                        if page_text:
                            text_parts.append(page_text)
                    extracted_text = "\n\n".join(text_parts).strip()
                doc.close()
            except Exception as e:
                logger.warning(f"PyMuPDF fallback failed: {e}")

        # If text still too short, try OCR (only when OCR_AVAILABLE)
        if len(extracted_text) < 100 and OCR_AVAILABLE:
            logger.info("Text layer insufficient, attempting OCR with PyMuPDF + pytesseract")
            # OCR_AVAILABLE is only True when both modules imported; narrow for the
            # type checker so the call sites below are not flagged union-attr.
            assert Image is not None and pytesseract is not None
            try:
                doc = fitz.open(file_path)
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

        # Task 4 多模态视觉：对每页内嵌图像做理解（图文混排核心）。
        # 只处理 PDF 内真正嵌入的位图（插图/图表/扫描图），渲染后交 VLM，
        # 把 caption+图内文字并入 raw_text；视觉不可用/无内嵌图则保持原文本层结果。
        visual_elements: list[VisualElement] = []
        try:
            doc = fitz.open(file_path)
            for page_num in range(len(doc)):
                page = doc[page_num]
                try:
                    images = page.get_images(full=True)
                except RuntimeError:
                    images = []
                for img_ref in images:
                    try:
                        xref = img_ref[0]
                        pix = fitz.Pixmap(doc, xref)
                        # 灰度需先转 RGB 再编码，否则单通道 PNG 无法直接喂 VLM
                        if pix.n < 5:
                            pix = fitz.Pixmap(fitz.csRGB, pix)
                        png_bytes = pix.tobytes("png")
                        pix = None
                        el = self._understand_image_bytes(png_bytes, media_type="image/png")
                        if el is not None:
                            visual_elements.append(el)
                    except Exception as e:  # noqa: BLE001
                        logger.debug(f"PDF page {page_num} image vision failed: {e}")
            doc.close()
        except Exception as e:  # noqa: BLE001 — 视觉不阻塞提取
            logger.warning(f"PDF embedded-image vision pass failed (degraded): {e}")

        if visual_elements:
            extracted_text = self._merge_visual_into_text(extracted_text, visual_elements)

        ocr_ratio = ocr_pages / page_count if page_count > 0 else 0.0
        return extracted_text, page_count, has_ocr, ocr_ratio, visual_elements

    def _extract_epub(self, file_path: str) -> tuple[str, int, bool, float, list[VisualElement]]:
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
        return "\n\n".join(text_parts).strip(), len(text_parts), False, 0.0, []

    def _extract_docx(self, file_path: str) -> tuple[str, int, bool, float, list[VisualElement]]:
        """Extract text from DOCX."""
        text_parts = []
        try:
            doc = Document(file_path)
            for para in doc.paragraphs:
                if para.text.strip():
                    text_parts.append(para.text)
        except Exception as e:
            logger.error(f"DOCX extraction failed: {e}")
        return "\n\n".join(text_parts).strip(), len(text_parts), False, 0.0, []

    def _extract_txt(self, file_path: str) -> tuple[str, int, bool, float, list[VisualElement]]:
        """Extract text from plain text file."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
            return text.strip(), 1, False, 0.0, []
        except UnicodeDecodeError:
            with open(file_path, "r", encoding="gbk") as f:
                text = f.read()
            return text.strip(), 1, False, 0.0, []

    def _extract_image(self, file_path: str) -> tuple[str, int, bool, float, list[VisualElement]]:
        """Extract from a single image.

        多模态视觉 (Task 4) 优先：转写图内文字 + 描述图的内容/性质。视觉不可用时
        诚实降级到 OCR（若可用），再否则抛错（同原 Red line #1 语义，不假装成功）。

        视觉与 OCR 双缺时，即使目标文件也不存在，也必须抛能力缺失错误
        （而非误导性的 FileNotFoundError）——red line #1 诚实语义。
        """
        try:
            with open(file_path, "rb") as f:
                image_bytes = f.read()
        except FileNotFoundError as e:
            if not OCR_AVAILABLE:
                vision_client = self._get_vision_client()
                if not getattr(vision_client, "available", False):
                    raise ValueError(
                        "Image understanding unavailable: no vision provider reachable AND "
                        "OCR not available. Install the pytesseract Python module "
                        "(pip install pytesseract pillow) AND the tesseract system binary "
                        "(apt-get install tesseract-ocr tesseract-ocr-chi-sim / "
                        "brew install tesseract tesseract-lang) to enable OCR fallback."
                    ) from e
            raise

        # Task 4: VLM 理解优先
        el = self._understand_image_bytes(image_bytes)
        if el is not None:
            text = (el.extracted_text or "").strip()
            # 仅视觉理解（非 OCR）；图内转写文字 + 描述一并作为结果文本。
            parts = [p for p in (text, (el.caption or "")) if p]
            raw = "\n".join(parts).strip()
            return raw, 1, False, 0.0, [el]

        # 视觉不可用 → 降级 OCR
        if not OCR_AVAILABLE:
            raise ValueError(
                "Image understanding unavailable: no vision provider reachable AND "
                "OCR not available. Install the pytesseract Python module "
                "(pip install pytesseract pillow) AND the tesseract system binary "
                "(apt-get install tesseract-ocr tesseract-ocr-chi-sim / "
                "brew install tesseract tesseract-lang) to enable OCR fallback."
            )

        # OCR_AVAILABLE is True => both modules imported; narrow for the type
        # checker so the call sites below are not flagged union-attr.
        assert Image is not None and pytesseract is not None

        try:
            image = Image.open(io.BytesIO(image_bytes))
            # Convert to RGB if needed (for RGBA images)
            if image.mode != "RGB":
                image = image.convert("RGB")

            # Use pytesseract for OCR
            text = pytesseract.image_to_string(image, lang="chi_sim+eng")

            return text.strip(), 1, True, 1.0, []
        except Exception as e:
            logger.error(f"Image OCR failed: {e}")
            return "", 1, False, 0.0, []

    def _detect_language(self, text: str) -> str:
        """Simple heuristic language detection.

        Supports Chinese (zh), Japanese (ja), French (fr) and English (en)
        in addition to the previous zh/en split. Uses Unicode script ranges
        rather than a hard dependency on langdetect/fasttext.
        """
        # In production: use langdetect or fasttext
        if not text:
            return "zh"
        chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        # Hiragana + Katakana => Japanese
        japanese_chars = sum(1 for c in text if ("\u3040" <= c <= "\u309f") or ("\u30a0" <= c <= "\u30ff"))
        # Latin letters (incl. accented) for French/English detection
        latin_chars = sum(1 for c in text if ("\u0041" <= c <= "\u007a") or ("\u00c0" <= c <= "\u017f"))
        total_alpha = len([c for c in text if c.isalpha()])
        if total_alpha == 0:
            return "zh"
        # Japanese: strong hiragana/katakana presence
        if japanese_chars / total_alpha > 0.05:
            return "ja"
        # Chinese: predominantly CJK ideographs
        if chinese_chars / total_alpha > 0.3:
            return "zh"
        # Latin-script: French has many accented characters; default to fr when
        # a notable fraction of latin chars carry diacritics, else en.
        accented = sum(1 for c in text if "\u00c0" <= c <= "\u017f")
        if latin_chars / total_alpha > 0.8 and accented / max(latin_chars, 1) > 0.05:
            return "fr"
        return "en"

    def run(self, input_data: ExtractionInput) -> ExtractionResult:
        """Execute extraction pipeline."""
        start_time = time.time()
        logger.info(f"Starting extraction: {input_data.file_path}")

        # Emit stage enter
        try:
            import asyncio

            loop = asyncio.get_running_loop()
            loop.create_task(
                emit_stage_enter(
                    stage="extract",
                    project_id=getattr(input_data, "project_id", 0) or 0,
                    chapter_index=getattr(input_data, "chapter_index", 1),
                    total_items=1,
                )
            )
        except RuntimeError:
            pass

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

        # Route to appropriate extractor. 每个 extractor 返回
        # (raw_text, page_count, has_ocr, ocr_ratio, visual_elements)。
        visual_elements: list[VisualElement] = []
        if mime_type == "application/pdf":
            raw_text, page_count, has_ocr, ocr_ratio, visual_elements = self._extract_pdf(file_path)
        elif mime_type == "application/epub+zip":
            raw_text, page_count, has_ocr, ocr_ratio, visual_elements = self._extract_epub(file_path)
        elif mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            raw_text, page_count, has_ocr, ocr_ratio, visual_elements = self._extract_docx(file_path)
        elif mime_type == "text/plain":
            raw_text, page_count, has_ocr, ocr_ratio, visual_elements = self._extract_txt(file_path)
        elif mime_type in (
            "image/png",
            "image/jpeg",
            "image/jpg",
            "image/tiff",
            "image/bmp",
            "image/webp",
        ):
            raw_text, page_count, has_ocr, ocr_ratio, visual_elements = self._extract_image(file_path)
        else:
            raise ValueError(f"Unsupported MIME type: {mime_type}")

        multimodal_used = bool(visual_elements)

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

        # Emit stage progress (100% complete)
        try:
            import asyncio

            loop = asyncio.get_running_loop()
            loop.create_task(
                emit_stage_progress(
                    stage="extract",
                    project_id=getattr(input_data, "project_id", 0) or 0,
                    chapter_index=getattr(input_data, "chapter_index", 1),
                    current=1,
                    total=1,
                    message="Extraction complete",
                )
            )
        except RuntimeError:
            pass

        # Emit stage exit
        try:
            import asyncio

            loop = asyncio.get_running_loop()
            loop.create_task(
                emit_stage_exit(
                    stage="extract",
                    project_id=getattr(input_data, "project_id", 0) or 0,
                    chapter_index=getattr(input_data, "chapter_index", 1),
                    success=True,
                )
            )
        except RuntimeError:
            pass

        return ExtractionResult(
            raw_text=raw_text,
            language=language,
            page_count=page_count,
            has_ocr=has_ocr,
            ocr_page_ratio=ocr_ratio,
            warnings=warnings,
            visual_descriptions=visual_elements,
            multimodal_used=multimodal_used,
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
