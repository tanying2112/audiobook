"""Unit tests for Task 4 多模态视觉理解.

Covers:
- ``MultimodalVisionClient``: provider discovery, mock_mode, honest degradation,
  per-provider failure fallback.
- ``_parse_visual_element``: robust JSON parsing of messy LLM output.
- ``_sniff_media_type``: byte-signature detection.
- extract.py integration: image path uses vision; honest raise when vision AND
  OCR unavailable; ``[插图: ...]`` merge into raw_text.

All network I/O is mocked — no external calls.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.pipeline.vision import (
    MultimodalVisionClient,
    _parse_visual_element,
    _sniff_media_type,
)
from src.audiobook_studio.schemas import VisualElement

# ── _parse_visual_element ─────────────────────────────────────────────────────


class TestParseVisualElement:
    def test_full_json(self):
        el = _parse_visual_element('{"kind":"figure","caption":"山","extracted_text":"abc"}')
        assert el is not None
        assert el.kind == "figure"
        assert el.caption == "山"
        assert el.extracted_text == "abc"

    def test_fenced_json(self):
        el = _parse_visual_element('```json\n{"kind":"table","caption":"表","extracted_text":"A|B"}\n```')
        assert el is not None
        assert el.kind == "table"

    def test_embedded_json_in_prose(self):
        el = _parse_visual_element('好的，解析如下：\n{"kind":"map","caption":"地图","extracted_text":"北"}')
        assert el is not None
        assert el.kind == "map"

    def test_invalid_kind_coerced_to_other(self):
        el = _parse_visual_element('{"kind":"banana","caption":"x","extracted_text":"y"}')
        assert el.kind == "other"

    def test_plain_text_fallback(self):
        el = _parse_visual_element("这就是一段普通描述，没有JSON")
        assert el is not None
        assert el.kind == "other"
        assert el.caption == "这就是一段普通描述，没有JSON"
        assert el.extracted_text == ""

    def test_empty_returns_none(self):
        assert _parse_visual_element("") is None
        assert _parse_visual_element("   ") is None


# ── _sniff_media_type ─────────────────────────────────────────────────────────


class TestSniffMediaType:
    def test_png(self):
        assert _sniff_media_type(b"\x89PNG\x0d\x0a") == "image/png"

    def test_jpeg(self):
        assert _sniff_media_type(b"\xff\xd8\xff\xe0") == "image/jpeg"

    def test_tiff_le_be(self):
        assert _sniff_media_type(b"II*\x00") == "image/tiff"
        assert _sniff_media_type(b"MM\x00*") == "image/tiff"

    def test_gif_webp(self):
        assert _sniff_media_type(b"GIF89a") == "image/gif"
        assert _sniff_media_type(b"RIFF\x00\x00\x00\x00WEBP") == "image/webp"

    def test_default_png(self):
        assert _sniff_media_type(b"\x00\x01\x02\x03") == "image/png"


# ── MultimodalVisionClient ────────────────────────────────────────────────────


def _client(providers=None, mock_mode=False):
    c = MultimodalVisionClient(mock_mode=mock_mode)
    if providers is not None:
        c.providers = providers
    return c


def _mock_prov(name: str):
    """Create a mock provider with name attribute."""
    from unittest.mock import MagicMock

    prov = MagicMock()
    prov.name = name
    return prov


class TestMultimodalVisionClient:
    def test_mock_mode_returns_mock_element(self):
        c = _client(mock_mode=True)
        el = c.understand_image(b"\x89PNG")
        assert el is not None
        assert "mock" in el.caption

    def test_no_providers_returns_none(self):
        c = _client(providers=[])
        assert c.available is False
        assert c.understand_image(b"\x89PNG") is None

    def test_provider_discovery_from_config(self):
        # Only providers with extra_params.vision=true are discovered as vision.
        vision_prov = _mock_prov("vision-prov")
        vision_prov.extra_params = {"vision": True}
        text_prov = _mock_prov("text-prov")
        text_prov.extra_params = {}
        fake_cfg = MagicMock()
        fake_cfg.get_all_enabled.return_value = [text_prov, vision_prov]

        with patch("src.audiobook_studio.llm.config_loader.LLMProvidersConfig.load", return_value=fake_cfg):
            c = MultimodalVisionClient()
        assert c.available is True
        assert c.provider_names == ["vision-prov"]  # text-prov 被过滤

    def test_success_returns_element(self):
        c = _client(providers=[_mock_prov("test-prov")])
        with patch.object(
            c, "_call_provider", return_value=VisualElement(kind="figure", caption="c", extracted_text="t")
        ):
            el = c.understand_image(b"\x89PNG")
        assert el is not None
        assert el.kind == "figure"
        assert el.extracted_text == "t"

    def test_all_fail_returns_none(self):
        c = _client(providers=[_mock_prov("fail-prov")])
        with patch.object(c, "_call_provider", side_effect=RuntimeError("boom")):
            assert c.understand_image(b"\x89PNG") is None

    def test_first_provider_wins(self):
        c = _client(providers=[_mock_prov("p1"), _mock_prov("p2")])
        seen = []

        def fake(prov, messages):
            seen.append(prov)
            return None if len(seen) == 1 else VisualElement(kind="other")

        with patch.object(c, "_call_provider", side_effect=fake):
            c.understand_image(b"\x89PNG")
        assert len(seen) == 2  # first returned None -> tried second


# ── extract.py integration ────────────────────────────────────────────────────


class TestExtractVisionIntegration:
    def test_image_path_uses_vision(self, tmp_path):
        from src.audiobook_studio.pipeline.extract import ExtractPipeline

        p = tmp_path / "a.png"
        p.write_bytes(b"\x89PNG\x0d\x0afakepngdata")
        pipe = ExtractPipeline(mock_mode=False)
        pipe._understand_image_bytes = MagicMock(
            return_value=VisualElement(kind="figure", caption="一张图", extracted_text="图内文字")
        )
        text, pages, has_ocr, ratio, elems = pipe._extract_image(str(p))
        # _extract_image joins extracted_text + caption with "\n"
        assert text == "图内文字\n一张图"
        assert elems and elems[0].kind == "figure"
        assert has_ocr is False  # 视觉，非 OCR
        pipe._understand_image_bytes.assert_called_once()

    def test_image_path_raises_when_vision_and_ocr_unavailable(self, tmp_path):
        from src.audiobook_studio.pipeline import extract as extract_mod
        from src.audiobook_studio.pipeline.extract import ExtractPipeline

        p = tmp_path / "b.png"
        p.write_bytes(b"x")
        pipe = ExtractPipeline(mock_mode=False)
        pipe._understand_image_bytes = MagicMock(return_value=None)
        with patch.object(extract_mod, "OCR_AVAILABLE", False):
            with pytest.raises(ValueError, match="Image understanding unavailable"):
                pipe._extract_image(str(p))

    def test_merge_visual_into_text(self):
        from src.audiobook_studio.pipeline.extract import ExtractPipeline

        pipe = ExtractPipeline()
        merged = pipe._merge_visual_into_text(
            "正文",
            [VisualElement(kind="figure", caption="插图说明", extracted_text="图内字")],
        )
        assert "插图说明" in merged
        assert "图内字" in merged
        assert merged.startswith("正文")

    def test_run_sets_multimodal_used(self, tmp_path):
        from src.audiobook_studio.pipeline.extract import ExtractPipeline
        from src.audiobook_studio.schemas import ExtractionInput

        p = tmp_path / "c.png"
        p.write_bytes(b"x")
        pipe = ExtractPipeline(mock_mode=False)
        pipe._extract_image = MagicMock(return_value=("图内文字", 1, False, 0.0, [VisualElement(kind="figure")]))
        pipe._detect_language = MagicMock(return_value="zh")
        inp = ExtractionInput(file_path=str(p), mime_type="image/png")
        res = pipe.run(inp)
        assert res.multimodal_used is True
        assert len(res.visual_descriptions) == 1
        assert "图内文字" in res.raw_text
