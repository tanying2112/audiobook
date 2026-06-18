"""Unit tests for text extraction pipeline."""

import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from src.audiobook_studio.pipeline.extract import ExtractPipeline, extract_text
from src.audiobook_studio.schemas import ExtractionInput, ExtractionResult


class TestExtractPipeline:
    """Test text extraction pipeline functionality."""

    def setup_method(self):
        """Setup test fixtures."""
        self.mock_router = Mock()
        self.pipeline = ExtractPipeline(router=self.mock_router, mock_mode=True)

    def test_init_default(self):
        """Test pipeline initialization with defaults."""
        pipeline = ExtractPipeline()
        assert not pipeline.mock_mode
        assert pipeline.router is not None

    def test_init_with_router(self):
        """Test pipeline initialization with custom router."""
        pipeline = ExtractPipeline(router=self.mock_router)
        assert pipeline.router == self.mock_router
        assert not pipeline.mock_mode

    def test_init_mock_mode(self):
        """Test pipeline initialization in mock mode."""
        pipeline = ExtractPipeline(mock_mode=True)
        assert pipeline.mock_mode

    def test_extract_txt_success(self):
        """Test successful text extraction from TXT file."""
        # Create a temporary text file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(
                "This is a test text file for testing extraction pipeline functionality.\nWith multiple lines and enough content to pass the minimum length check."
            )
            temp_path = f.name

        try:
            input_data = ExtractionInput(
                file_path=temp_path, mime_type="text/plain", detect_language=True
            )

            # Use non-mock pipeline for real file extraction
            pipeline = ExtractPipeline(router=self.mock_router, mock_mode=False)
            result = pipeline.run(input_data)

            assert isinstance(result, ExtractionResult)
            assert (
                result.raw_text
                == "This is a test text file for testing extraction pipeline functionality.\nWith multiple lines and enough content to pass the minimum length check."
            )
            assert result.language == "en"  # English detected
            assert result.page_count == 1
            assert not result.has_ocr
            assert result.ocr_page_ratio == 0.0
            assert result.warnings == []

        finally:
            os.unlink(temp_path)

    def test_extract_txt_too_short(self):
        """Test extraction with text too short triggers warning."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Short")
            temp_path = f.name

        try:
            input_data = ExtractionInput(
                file_path=temp_path, mime_type="text/plain", detect_language=True
            )

            # Use non-mock pipeline for real file extraction
            pipeline = ExtractPipeline(router=self.mock_router, mock_mode=False)
            result = pipeline.run(input_data)

            assert len(result.raw_text) > 0  # Raw text was extracted
            assert len(result.warnings) > 0  # Should warn about short text

        finally:
            os.unlink(temp_path)

    def test_detect_language_zh(self):
        """Test language detection for Chinese text."""
        chinese_text = "这是一个中文测试文本，包含足够的中文字符。"
        lang = self.pipeline._detect_language(chinese_text)
        assert lang == "zh"

    def test_detect_language_en(self):
        """Test language detection for English text."""
        english_text = "This is an English test text with sufficient characters."
        lang = self.pipeline._detect_language(english_text)
        assert lang == "en"

    def test_detect_language_mixed(self):
        """Test language detection for mixed text."""
        mixed_text = "这是一个混合text，包含中文和English。"
        lang = self.pipeline._detect_language(mixed_text)
        # Should be zh if Chinese chars > 30%
        assert lang in ["zh", "en"]

    def test_detect_language_empty(self):
        """Test language detection with empty text."""
        lang = self.pipeline._detect_language("")
        assert lang == "zh"  # Default fallback

    def test_extract_text_convenience_function(self):
        """Test the convenience extract_text function."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Convenience function test.")
            temp_path = f.name

        try:
            result = extract_text(
                file_path=temp_path,
                mime_type="text/plain",
                detect_language=True,
                mock_mode=True,
            )

            assert isinstance(result, ExtractionResult)
            # In mock_mode=True, it should return the mock text
            assert "用于测试的模拟提取文本" in result.raw_text

        finally:
            os.unlink(temp_path)


class TestExtractPipelineMockMode:
    """Test extract pipeline in mock mode."""

    def setup_method(self):
        self.pipeline = ExtractPipeline(mock_mode=True)

    def test_mock_mode_returns_expected_result(self):
        """Test that mock mode returns expected mock result."""
        input_data = ExtractionInput(
            file_path="/fake/path.txt", mime_type="text/plain", detect_language=True
        )

        result = self.pipeline.run(input_data)

        assert isinstance(result, ExtractionResult)
        assert result.language == "zh"
        assert result.page_count == 5
        assert not result.has_ocr
        assert result.ocr_page_ratio == 0.0
        assert result.warnings == []
        assert "模拟提取文本" in result.raw_text
        assert len(result.raw_text) > 50  # Should be substantial text


if __name__ == "__main__":
    pytest.main([__file__])


class TestExtractPipelineNonMock:  # noqa: E302
    """Test non-mock extraction paths for coverage."""

    def setup_method(self):
        """Setup test fixtures with real (non-mock) pipeline."""
        self.mock_router = Mock()
        self.pipeline = ExtractPipeline(router=self.mock_router, mock_mode=False)

    def test_extract_pdf_with_text_layer(self):
        """Test PDF extraction using pdfplumber text layer."""
        with patch(
            "src.audiobook_studio.pipeline.extract.pdfplumber.open"
        ) as mock_open:
            # Mock pdfplumber to return pages with text (enough to avoid OCR)
            mock_page1 = Mock()
            mock_page1.extract_text.return_value = (
                "Page 1 text content with sufficient length to exceed 100 characters. "
                * 2
            )
            mock_page2 = Mock()
            mock_page2.extract_text.return_value = (
                "Page 2 text content with sufficient length to exceed 100 characters. "
                * 2
            )
            mock_pdf = Mock()
            mock_pdf.pages = [mock_page1, mock_page2]
            mock_open.return_value.__enter__.return_value = mock_pdf

            # Also mock fitz to avoid any import issues
            with patch("src.audiobook_studio.pipeline.extract.fitz.open") as mock_fitz:
                text, page_count, has_ocr, ocr_ratio = self.pipeline._extract_pdf(
                    "test.pdf"
                )

                assert page_count == 2
                assert "Page 1 text content" in text
                assert "Page 2 text content" in text
                assert not has_ocr
                assert ocr_ratio == 0.0

    def test_extract_pdf_pdfplumber_failure(self):
        """Test PDF extraction when pdfplumber fails."""
        with patch(
            "src.audiobook_studio.pipeline.extract.pdfplumber.open",
            side_effect=Exception("pdfplumber failed"),
        ):
            with patch("src.audiobook_studio.pipeline.extract.fitz.open") as mock_fitz:
                # Use a regular object with __len__ implemented
                class MockDoc:
                    def __len__(self):
                        return 1

                    def __getitem__(self, key):
                        return Mock()

                    def __iter__(self):
                        return iter([0])

                    def close(self):
                        pass

                mock_doc = MockDoc()
                mock_page = Mock()
                mock_page.get_pixmap.return_value = Mock()  # noqa: F841
                mock_page.get_text.return_value = {"blocks": []}
                mock_doc.__getitem__ = lambda self, key: mock_page
                mock_fitz.return_value = mock_doc

                text, page_count, has_ocr, ocr_ratio = self.pipeline._extract_pdf(
                    "test.pdf"
                )

                assert page_count == 1
                assert has_ocr  # Should attempt OCR

    def test_extract_pdf_text_insufficient_triggers_ocr(self):
        """Test OCR fallback when extracted text is too short."""
        with patch(
            "src.audiobook_studio.pipeline.extract.pdfplumber.open"
        ) as mock_open:
            mock_page = Mock()
            mock_page.extract_text.return_value = "Short"  # < 100 chars
            mock_pdf = Mock()
            mock_pdf.pages = [mock_page]
            mock_open.return_value.__enter__.return_value = mock_pdf

            with patch("src.audiobook_studio.pipeline.extract.fitz.open") as mock_fitz:

                class MockDoc:
                    def __len__(self):
                        return 1

                    def __getitem__(self, key):
                        mock_item = Mock()
                        mock_item.get_pixmap.return_value = Mock()
                        # The code expects blocks with direct "text" key
                        blocks = [
                            {"text": "OCR extracted text"},
                            {"text": "More OCR text"},
                        ]
                        mock_item.get_text.return_value = {"blocks": blocks}
                        return mock_item

                    def __iter__(self):
                        return iter([0])

                    def close(self):
                        pass

                mock_fitz.return_value = MockDoc()

                text, page_count, has_ocr, ocr_ratio = self.pipeline._extract_pdf(
                    "test.pdf"
                )

                assert has_ocr
                assert page_count == 1
                assert "OCR extracted text" in text

    def test_extract_pdf_ocr_failure(self):
        """Test PDF when both pdfplumber and PyMuPDF fail."""
        with patch(
            "src.audiobook_studio.pipeline.extract.pdfplumber.open",
            side_effect=Exception("pdfplumber failed"),
        ):
            with patch(
                "src.audiobook_studio.pipeline.extract.fitz.open",
                side_effect=Exception("PyMuPDF failed"),
            ):
                text, page_count, has_ocr, ocr_ratio = self.pipeline._extract_pdf(
                    "test.pdf"
                )

                assert text == ""
                assert page_count == 0
                assert has_ocr  # Tried OCR
                assert ocr_ratio == 0.0

    def test_extract_epub_success(self):
        """Test EPUB extraction with BeautifulSoup."""
        with patch("src.audiobook_studio.pipeline.extract.epub.read_epub") as mock_read:
            mock_book = Mock()
            mock_item = Mock()
            mock_item.get_type.return_value = "application/xhtml+xml"  # document type
            mock_item.get_content.return_value = (
                b"<html><body><p>EPUB content</p></body></html>"
            )
            mock_book.get_items.return_value = [mock_item]
            mock_read.return_value = mock_book

            text, page_count, has_ocr, ocr_ratio = self.pipeline._extract_epub(
                "test.epub"
            )

            assert "EPUB content" in text
            assert page_count == 1
            assert not has_ocr
            assert ocr_ratio == 0.0

    def test_extract_epub_failure(self):
        """Test EPUB extraction failure."""
        with patch(
            "src.audiobook_studio.pipeline.extract.epub.read_epub",
            side_effect=Exception("EPUB failed"),
        ):
            text, page_count, has_ocr, ocr_ratio = self.pipeline._extract_epub(
                "test.epub"
            )

            assert text == ""
            assert page_count == 0
            assert not has_ocr
            assert ocr_ratio == 0.0

    def test_extract_docx_success(self):
        """Test DOCX extraction."""
        with patch("src.audiobook_studio.pipeline.extract.Document") as mock_doc_class:
            mock_doc = Mock()
            mock_para1 = Mock()
            mock_para1.text = "Paragraph 1"
            mock_para2 = Mock()
            mock_para2.text = "Paragraph 2"
            mock_doc.paragraphs = [mock_para1, mock_para2]
            mock_doc_class.return_value = mock_doc

            text, page_count, has_ocr, ocr_ratio = self.pipeline._extract_docx(
                "test.docx"
            )

            assert "Paragraph 1" in text
            assert "Paragraph 2" in text
            assert page_count == 2
            assert not has_ocr
            assert ocr_ratio == 0.0

    def test_extract_docx_failure(self):
        """Test DOCX extraction failure."""
        with patch(
            "src.audiobook_studio.pipeline.extract.Document",
            side_effect=Exception("DOCX failed"),
        ):
            text, page_count, has_ocr, ocr_ratio = self.pipeline._extract_docx(
                "test.docx"
            )

            assert text == ""
            assert page_count == 0
            assert not has_ocr
            assert ocr_ratio == 0.0

    def test_extract_txt_utf8(self):
        """Test TXT extraction with UTF-8 encoding."""
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("UTF-8 text content")
            temp_path = f.name

        try:
            text, page_count, has_ocr, ocr_ratio = self.pipeline._extract_txt(temp_path)
            assert text == "UTF-8 text content"
            assert page_count == 1
            assert not has_ocr
            assert ocr_ratio == 0.0
        finally:
            os.unlink(temp_path)

    def test_extract_txt_gbk_fallback(self):
        """Test TXT extraction with GBK fallback."""
        import tempfile

        # Create a file with GBK encoding
        gbk_content = "GBK 编码内容".encode("gbk")
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".txt", delete=False) as f:
            f.write(gbk_content)
            temp_path = f.name

        try:
            text, page_count, has_ocr, ocr_ratio = self.pipeline._extract_txt(temp_path)
            assert "GBK 编码内容" in text
            assert page_count == 1
        finally:
            os.unlink(temp_path)

    def test_run_pdf(self):
        """Test run method with PDF."""
        with patch.object(
            self.pipeline, "_extract_pdf", return_value=("PDF text", 3, False, 0.0)
        ):
            input_data = ExtractionInput(
                file_path="test.pdf", mime_type="application/pdf", detect_language=True
            )
            result = self.pipeline.run(input_data)

            assert result.raw_text == "PDF text"
            assert result.page_count == 3
            assert result.language == "en"  # PDF text is English

    def test_run_epub(self):
        """Test run method with EPUB."""
        with patch.object(
            self.pipeline, "_extract_epub", return_value=("EPUB text", 5, False, 0.0)
        ):
            input_data = ExtractionInput(
                file_path="test.epub",
                mime_type="application/epub+zip",
                detect_language=True,
            )
            result = self.pipeline.run(input_data)

            assert result.raw_text == "EPUB text"
            assert result.page_count == 5

    def test_run_docx(self):
        """Test run method with DOCX."""
        with patch.object(
            self.pipeline, "_extract_docx", return_value=("DOCX text", 2, False, 0.0)
        ):
            input_data = ExtractionInput(
                file_path="test.docx",
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                detect_language=True,
            )
            result = self.pipeline.run(input_data)

            assert result.raw_text == "DOCX text"
            assert result.page_count == 2

    def test_run_txt(self):
        """Test run method with TXT."""
        with patch.object(
            self.pipeline, "_extract_txt", return_value=("TXT text", 1, False, 0.0)
        ):
            input_data = ExtractionInput(
                file_path="test.txt", mime_type="text/plain", detect_language=True
            )
            result = self.pipeline.run(input_data)

            assert result.raw_text == "TXT text"
            assert result.page_count == 1

    def test_run_unsupported_mime_type(self):
        """Test run method with unsupported MIME type."""
        # Create input that bypasses schema validation (directly create invalid mime)
        import pytest
        from src.audiobook_studio.schemas import ExtractionInput

        input_data = ExtractionInput(
            file_path="test.xyz", mime_type="text/plain", detect_language=True
        )
        # Modify the mime_type after validation to test the run method logic
        input_data.mime_type = "application/unknown"
        with pytest.raises(ValueError, match="Unsupported MIME type"):
            self.pipeline.run(input_data)

    def test_run_short_text_warning(self):
        """Test run method warns when text is too short."""
        with patch.object(
            self.pipeline, "_extract_txt", return_value=("Short", 1, False, 0.0)
        ):
            input_data = ExtractionInput(
                file_path="test.txt", mime_type="text/plain", detect_language=True
            )
            result = self.pipeline.run(input_data)

            assert len(result.warnings) > 0
            assert "too short" in result.warnings[0].lower()

    def test_run_short_text_low_quality_score(self):
        """Test run method records low quality for short text."""
        recorded = {}

        def capture_record(*args, **kwargs):
            recorded.update(kwargs)

        with patch(
            "src.audiobook_studio.pipeline.extract.record_stage_performance",
            side_effect=capture_record,
        ):
            with patch.object(
                self.pipeline, "_extract_txt", return_value=("Short", 1, False, 0.0)
            ):
                input_data = ExtractionInput(
                    file_path="test.txt", mime_type="text/plain", detect_language=True
                )
                result = self.pipeline.run(input_data)

                assert recorded.get("quality_score") == 0.5
                assert recorded.get("success") is False

    def test_run_ocr_provider(self):
        """Test run method uses 'ocr' provider when OCR was used."""
        recorded = {}

        def capture_record(*args, **kwargs):
            recorded.update(kwargs)

        with patch(
            "src.audiobook_studio.pipeline.extract.record_stage_performance",
            side_effect=capture_record,
        ):
            with patch.object(
                self.pipeline, "_extract_pdf", return_value=("OCR text", 2, True, 0.5)
            ):
                input_data = ExtractionInput(
                    file_path="test.pdf",
                    mime_type="application/pdf",
                    detect_language=True,
                )
                result = self.pipeline.run(input_data)

                assert recorded.get("provider") == "ocr"
                assert recorded.get("cost_usd") == 0.005

    def test_run_local_provider(self):
        """Test run method uses 'local' provider when no OCR."""
        recorded = {}

        def capture_record(*args, **kwargs):
            recorded.update(kwargs)

        with patch(
            "src.audiobook_studio.pipeline.extract.record_stage_performance",
            side_effect=capture_record,
        ):
            with patch.object(
                self.pipeline,
                "_extract_pdf",
                return_value=("Local text", 2, False, 0.0),
            ):
                input_data = ExtractionInput(
                    file_path="test.pdf",
                    mime_type="application/pdf",
                    detect_language=True,
                )
                result = self.pipeline.run(input_data)

                assert recorded.get("provider") == "local"
                assert recorded.get("cost_usd") == 0.001

    def test_run_detect_language_false(self):
        """Test run method when detect_language is False."""
        with patch.object(
            self.pipeline, "_extract_txt", return_value=("English text", 1, False, 0.0)
        ):
            input_data = ExtractionInput(
                file_path="test.txt", mime_type="text/plain", detect_language=False
            )
            result = self.pipeline.run(input_data)

            assert result.language == "zh"  # Default when detect_language=False

    def test_mock_mode_records_performance(self):
        """Test mock mode records performance correctly."""
        recorded = {}

        def capture_record(*args, **kwargs):
            recorded.update(kwargs)

        with patch(
            "src.audiobook_studio.pipeline.extract.record_stage_performance",
            side_effect=capture_record,
        ):
            pipeline = ExtractPipeline(mock_mode=True)
            input_data = ExtractionInput(
                file_path="/fake/path.txt", mime_type="text/plain", detect_language=True
            )
            result = pipeline.run(input_data)

            assert recorded.get("stage") == "extract_mock"
            assert recorded.get("success") is True
            assert recorded.get("quality_score") == 1.0
            assert recorded.get("cost_usd") == 0.0
            assert recorded.get("provider") == "mock"
