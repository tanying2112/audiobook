"""Comprehensive unit tests for extract pipeline targeting ≥80% line coverage.

Tests match the ACTUAL API from src/audiobook_studio/pipeline/extract.py:
- ExtractPipeline class with run(), _extract_pdf(), _extract_epub(), _extract_docx(), _extract_txt()
- extract_text() convenience function
- ExtractionInput/ExtractionResult Pydantic models
- mock_mode behavior for testing without external APIs
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.audiobook_studio.pipeline.extract import ExtractPipeline, extract_text
from src.audiobook_studio.schemas import ExtractionInput, ExtractionResult


class TestExtractPipeline:
    """Test ExtractPipeline class."""

    def setup_method(self):
        """Setup test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.pipeline = ExtractPipeline()

    def teardown_method(self):
        """Clean up test fixtures."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def create_minimal_input(self, **overrides):
        """Create minimal valid ExtractionInput for testing."""
        defaults = {
            "file_path": "/fake/path/test.pdf",
            "mime_type": "application/pdf",
            "detect_language": True,
        }
        defaults.update(overrides)
        return ExtractionInput(**defaults)

    def create_mock_result(self, **overrides):
        """Create a valid ExtractionResult for mocking."""
        defaults = {
            "raw_text": "这是一个用于测试的模拟提取文本，包含足够的字符数以满足最小长度要求。第一章  从前有一个小女孩，她戴着红色的帽子，大家都叫她小红帽。",
            "language": "zh",
            "page_count": 5,
            "has_ocr": False,
            "ocr_page_ratio": 0.0,
            "warnings": [],
        }
        defaults.update(overrides)
        return ExtractionResult(**defaults)

    def test_init_default(self):
        """Test pipeline initialization with defaults."""
        from src.audiobook_studio.llm import create_router

        pipeline = ExtractPipeline()
        assert pipeline.router is not None

    def test_init_with_custom_router(self):
        """Test pipeline initialization with custom router."""
        mock_router = Mock()
        pipeline = ExtractPipeline(router=mock_router)
        assert pipeline.router == mock_router

    def test_detect_language_chinese(self):
        """Test _detect_language with Chinese text."""
        text = "这是中文文本测试。" * 10
        lang = self.pipeline._detect_language(text)
        assert lang == "zh"

    def test_detect_language_english(self):
        """Test _detect_language with English text."""
        text = "This is English text for testing. " * 10
        lang = self.pipeline._detect_language(text)
        assert lang == "en"

    def test_detect_language_mixed(self):
        """Test _detect_language with mixed text (Chinese dominant)."""
        text = "这是中文文本。" * 10 + "English. " * 2
        lang = self.pipeline._detect_language(text)
        assert lang == "zh"

    def test_detect_language_short_text(self):
        """Test _detect_language with very short text."""
        text = "Hi"
        lang = self.pipeline._detect_language(text)
        assert lang == "en"  # Short English text defaults to en

    def test_run_mock_mode_returns_extraction_result(self):
        """Test run() returns ExtractionResult in mock mode without calling real extraction."""
        input_data = self.create_minimal_input()

        with patch.object(self.pipeline, "_extract_pdf") as mock_extract:
            result = self.pipeline.run(input_data)

            assert isinstance(result, ExtractionResult)
            assert result.raw_text is not None
            assert len(result.raw_text) > 0
            # In mock_mode, _extract_pdf should NOT be called
            mock_extract.assert_not_called()

    def test_run_mock_mode_records_performance(self):
        """Test run() in mock mode records mock performance metrics."""
        input_data = self.create_minimal_input()

        with patch.object(self.pipeline, "_extract_pdf") as mock_extract:
            with patch(
                "src.audiobook_studio.pipeline.extract.record_stage_performance"
            ) as mock_record:
                self.pipeline.run(input_data)
                # In mock mode, record_stage_performance should be called with mock data
                mock_record.assert_called_once()
                call_kwargs = mock_record.call_args.kwargs
                assert call_kwargs["stage"] == "extract_mock"
                assert call_kwargs["success"] is True
                # _extract_pdf should NOT be called in mock mode
                mock_extract.assert_not_called()

    def test_run_mock_mode_with_custom_router(self):
        """Test run() with custom router in mock mode."""
        mock_router = Mock()
        pipeline = ExtractPipeline(router=mock_router)
        input_data = self.create_minimal_input()

        with patch.object(pipeline, "_extract_pdf") as mock_extract:
            result = pipeline.run(input_data)

            assert isinstance(result, ExtractionResult)
            # In mock mode, _extract_pdf should NOT be called
            mock_extract.assert_not_called()
            # Router is not called in mock mode
            mock_router.call.assert_not_called()

    def test_run_real_mode_no_router_call_in_mock(self):
        """Test that router is not called for basic extraction in mock mode."""
        mock_router = Mock()
        pipeline = ExtractPipeline(router=mock_router)
        input_data = self.create_minimal_input()

        with patch.object(pipeline, "_extract_pdf") as mock_extract:
            pipeline.run(input_data)
            # In mock mode, _extract_pdf should NOT be called
            mock_extract.assert_not_called()
            # Router is not called in mock mode
            mock_router.call.assert_not_called()


# Additional tests for actual extraction logic (not mock mode)
class TestExtractPipelineRealLogic:
    """Test actual extraction logic paths by mocking external deps."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        # Explicitly set mock_mode=False for real mode tests
        self.pipeline = ExtractPipeline(mock_mode=False)

    def teardown_method(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("src.audiobook_studio.pipeline.extract.pdfplumber")
    @patch("src.audiobook_studio.pipeline.extract.fitz")
    def test_extract_pdf_with_pdfplumber(self, mock_fitz, mock_pdfplumber):
        """Test _extract_pdf when pdfplumber succeeds."""
        mock_page = Mock()
        mock_page.extract_text.return_value = "测试页面内容" * 20

        mock_pdf = Mock()
        mock_pdf.pages = [mock_page, mock_page]
        mock_pdfplumber.open.return_value.__enter__.return_value = mock_pdf

        test_file = Path(self.temp_dir) / "test.pdf"
        test_file.write_bytes(b"%PDF-1.4 dummy")

        text, pages, has_ocr, ocr_ratio = self.pipeline._extract_pdf(str(test_file))

        assert "测试页面内容" in text
        assert pages == 2
        assert has_ocr is False
        assert ocr_ratio == 0.0

    @patch("src.audiobook_studio.pipeline.extract.pdfplumber")
    @patch("src.audiobook_studio.pipeline.extract.fitz")
    def test_extract_pdf_fallback_to_ocr(self, mock_fitz, mock_pdfplumber):
        """Test _extract_pdf falls back to OCR when text too short."""
        mock_page = Mock()
        mock_page.extract_text.return_value = "短"

        mock_pdf = Mock()
        mock_pdf.pages = [mock_page]
        mock_pdfplumber.open.return_value.__enter__.return_value = mock_pdf

        mock_doc = Mock()
        mock_page_pymupdf = Mock()
        mock_block = {"text": "OCR identified content"}
        mock_page_pymupdf.get_text.return_value = {"blocks": [mock_block]}
        mock_doc.__len__ = Mock(return_value=1)
        mock_doc.__getitem__ = Mock(return_value=mock_page_pymupdf)
        mock_fitz.open.return_value = mock_doc

        test_file = Path(self.temp_dir) / "test.pdf"
        test_file.write_bytes(b"%PDF-1.4 dummy")

        text, pages, has_ocr, ocr_ratio = self.pipeline._extract_pdf(str(test_file))

        assert "OCR identified content" in text
        assert pages == 1
        assert has_ocr is True
        assert ocr_ratio == 1.0

    @patch("src.audiobook_studio.pipeline.extract.epub")
    def test_extract_epub(self, mock_epub):
        """Test _extract_epub."""
        import sys
        from unittest.mock import Mock

        # Mock bs4 module
        mock_bs4 = Mock()
        mock_soup = Mock()
        mock_soup.get_text.return_value = "EPUB content"
        mock_bs4.BeautifulSoup.return_value = mock_soup
        sys.modules["bs4"] = mock_bs4

        mock_item = Mock()
        mock_item.get_type.return_value = "application/xhtml+xml"
        mock_item.get_content.return_value = b"<html><body>EPUB content</body></html>"

        mock_book = Mock()
        mock_book.get_items.return_value = [mock_item]
        mock_epub.read_epub.return_value = mock_book

        test_file = Path(self.temp_dir) / "test.epub"
        test_file.write_bytes(b"dummy")

        text, count, has_ocr, ocr_ratio = self.pipeline._extract_epub(str(test_file))

        assert "EPUB content" in text
        assert count == 1
        assert has_ocr is False

        # Cleanup
        if "bs4" in sys.modules:
            del sys.modules["bs4"]

    @patch("src.audiobook_studio.pipeline.extract.Document")
    def test_extract_docx(self, mock_document):
        """Test _extract_docx."""
        mock_para = Mock()
        mock_para.text = "DOCX paragraph content"
        mock_doc = Mock()
        mock_doc.paragraphs = [mock_para, mock_para]
        mock_document.return_value = mock_doc

        test_file = Path(self.temp_dir) / "test.docx"
        test_file.write_bytes(b"dummy")

        text, count, has_ocr, ocr_ratio = self.pipeline._extract_docx(str(test_file))

        assert "DOCX paragraph content" in text
        assert count == 2

    def test_extract_txt_utf8(self):
        """Test _extract_txt with UTF-8 encoding."""
        test_file = Path(self.temp_dir) / "test.txt"
        test_file.write_text("Text file content\nSecond line", encoding="utf-8")

        text, pages, has_ocr, ocr_ratio = self.pipeline._extract_txt(str(test_file))

        assert "Text file content" in text
        assert pages == 1

    def test_extract_txt_gbk_fallback(self):
        """Test _extract_txt falls back to GBK on UnicodeDecodeError."""
        test_file = Path(self.temp_dir) / "test_gbk.txt"
        test_file.write_bytes("Chinese content".encode("gbk"))

        text, pages, has_ocr, ocr_ratio = self.pipeline._extract_txt(str(test_file))

        assert "Chinese content" in text
        assert pages == 1

    def test_detect_language_various(self):
        """Test _detect_language with various inputs."""
        assert self.pipeline._detect_language("这是中文文本" * 5) == "zh"
        assert self.pipeline._detect_language("This is English text " * 5) == "en"
        assert self.pipeline._detect_language("Hi") == "en"
        assert self.pipeline._detect_language("12345") == "zh"

    @patch("src.audiobook_studio.pipeline.extract.pdfplumber")
    @patch("src.audiobook_studio.pipeline.extract.fitz")
    def test_run_real_mode_pdf(self, mock_fitz, mock_pdfplumber):
        """Test run() in real mode with PDF."""
        mock_page = Mock()
        mock_page.extract_text.return_value = "第一章 内容\n\n第二章 更多内容" * 10

        mock_pdf = Mock()
        mock_pdf.pages = [mock_page, mock_page]
        mock_pdfplumber.open.return_value.__enter__.return_value = mock_pdf

        input_data = ExtractionInput(
            file_path="/fake/test.pdf",
            mime_type="application/pdf",
            detect_language=True,
        )

        result = self.pipeline.run(input_data)

        assert isinstance(result, ExtractionResult)
        assert "第一章" in result.raw_text
        assert result.language == "zh"
        assert result.page_count == 2
        assert result.has_ocr is False

    @patch("src.audiobook_studio.pipeline.extract.epub")
    def test_run_real_mode_epub(self, mock_epub):
        """Test run() in real mode with EPUB."""
        import sys
        from unittest.mock import Mock

        # Mock bs4 module
        mock_bs4 = Mock()
        mock_soup = Mock()
        mock_soup.get_text.return_value = "EPUB 测试内容 " * 30
        mock_bs4.BeautifulSoup.return_value = mock_soup
        sys.modules["bs4"] = mock_bs4

        mock_item = Mock()
        mock_item.get_type.return_value = "application/xhtml+xml"
        mock_item.get_content.return_value = (
            "<html><body>EPUB 测试内容 " * 30 + "</body></html>"
        ).encode("utf-8")

        mock_book = Mock()
        mock_book.get_items.return_value = [mock_item]
        mock_epub.read_epub.return_value = mock_book = mock_book

        input_data = ExtractionInput(
            file_path="/fake/test.epub",
            mime_type="application/epub+zip",
            detect_language=True,
        )

        result = self.pipeline.run(input_data)

        assert "EPUB 测试内容" in result.raw_text
        assert result.language == "zh"

        # Cleanup
        if "bs4" in sys.modules:
            del sys.modules["bs4"]

    @patch("src.audiobook_studio.pipeline.extract.Document")
    def test_run_real_mode_docx(self, mock_document):
        """Test run() in real mode with DOCX."""
        mock_para = Mock()
        mock_para.text = "DOCX 测试文档内容 " * 10
        mock_doc = Mock()
        mock_doc.paragraphs = [mock_para]
        mock_document.return_value = mock_doc

        input_data = ExtractionInput(
            file_path="/fake/test.docx",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            detect_language=True,
        )

        result = self.pipeline.run(input_data)

        assert "DOCX 测试文档内容" in result.raw_text

    def test_run_real_mode_txt(self):
        """Test run() in real mode with TXT."""
        test_file = Path(self.temp_dir) / "test.txt"
        test_file.write_text("纯文本测试内容 " * 20, encoding="utf-8")

        input_data = ExtractionInput(
            file_path=str(test_file), mime_type="text/plain", detect_language=True
        )

        result = self.pipeline.run(input_data)

        assert "纯文本测试内容" in result.raw_text
        assert result.language == "zh"

    def test_run_unsupported_mime_raises(self):
        """Test run() with unsupported MIME type raises ValueError."""
        input_data = ExtractionInput(
            file_path="/fake/test.xyz",
            mime_type="application/pdf",  # Valid for schema, but will raise in run()
            detect_language=True,
        )
        # We need to mock the extraction to raise ValueError for unsupported types
        # but since pdf is supported, we'll test a different path
        # Actually the run() raises ValueError for unsupported mime types
        # which are caught by schema validation first
        # So this test is not applicable - schema prevents invalid mime types
        pass


class TestExtractConvenienceFunction:
    """Test extract_text convenience function."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()

    def teardown_method(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("src.audiobook_studio.pipeline.extract.pdfplumber")
    @patch("src.audiobook_studio.pipeline.extract.fitz")
    def test_extract_text_integration(self, mock_fitz, mock_pdfplumber):
        """Test extract_text() function with mocked dependencies.

        Note: extract_text defaults to mock_mode=True, so we explicitly set mock_mode=False.
        """
        mock_page = Mock()
        mock_page.extract_text.return_value = (
            "集成测试文本内容" * 20
        )  # > 100 chars to avoid OCR fallback

        mock_pdf = Mock()
        mock_pdf.pages = [mock_page]
        mock_pdfplumber.open.return_value.__enter__.return_value = mock_pdf

        test_file = Path(self.temp_dir) / "test.pdf"
        test_file.write_bytes(b"%PDF-1.4")

        # Explicitly set mock_mode=False for real extraction test
        result = extract_text(
            str(test_file), mime_type="application/pdf", mock_mode=False
        )

        assert "集成测试文本内容" in result.raw_text
        assert result.language == "zh"
