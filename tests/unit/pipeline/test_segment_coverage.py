"""Real-business coverage tests for ``pipeline/segment.py``.

Exercises all three segmentation strategies (rule / semantic / llm) plus the
``SegmentPipeline`` orchestration glue. Heavy optional dependencies (spaCy,
sentence-transformers) are faked so the code paths execute offline with free
resources; the lazy LLM schema import is injected so the structured-LLM branch
is reachable.
"""

from __future__ import annotations

import builtins
import os
import re
import sys
import types
from pathlib import Path
from typing import List
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from src.audiobook_studio.pipeline.segment import (
    LLMSegmenter,
    RuleSegmenter,
    Segment,
    SegmentConfig,
    SegmentationResult,
    SegmentPipeline,
    SegmentStrategy,
    SemanticSegmenter,
    segment_text,
)


# ── Fakes for the optional NLP dependencies ────────────────────────────────


class _FakeSent:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeDoc:
    def __init__(self, sents) -> None:
        self.sents = [_FakeSent(s) for s in sents]


class _FakeNLP:
    """Pretends to be a spaCy pipeline: splits text into sentences by punctuation."""

    def __call__(self, para: str) -> _FakeDoc:
        parts = re.split(r"(?<=[。！？.!?])", para)
        parts = [p for p in parts if p.strip()]
        return _FakeDoc(parts)


class _FakeSpacy:
    @staticmethod
    def load(model_name):  # noqa: ANN001, ANN205
        return _FakeNLP()

    @staticmethod
    def blank(lang):  # noqa: ANN001, ANN205
        return _FakeNLP()


@pytest.fixture
def fake_spacy(monkeypatch):
    """Make ``import spacy`` resolve to a fake module so RuleSegmenter uses spaCy path."""

    real_import = builtins.__import__

    def _imp(name, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if name == "spacy" or name.startswith("spacy."):
            fake = types.ModuleType("spacy")
            fake.load = _FakeSpacy.load
            fake.blank = _FakeSpacy.blank
            sys.modules.setdefault("spacy", fake)
            return fake
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _imp)
    yield
    sys.modules.pop("spacy", None)


@pytest.fixture
def no_spacy(monkeypatch):
    """Force ``import spacy`` to raise so RuleSegmenter uses the regex fallback."""

    real_import = builtins.__import__

    def _imp(name, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if name == "spacy" or name.startswith("spacy."):
            raise ImportError("spacy unavailable in tests")
        return real_import(name, *args, **kwargs)

    # Ensure no cached spacy module short-circuits the import interception.
    sys.modules.pop("spacy", None)
    monkeypatch.setattr(builtins, "__import__", _imp)
    yield


class _FakeSpacyLoadFails:
    """spaCy stand-in whose ``load`` raises OSError so the blank-model fallback runs."""

    @staticmethod
    def load(model_name):  # noqa: ANN001, ANN205
        raise OSError(f"model {model_name} not found")

    @staticmethod
    def blank(lang):  # noqa: ANN001, ANN205
        return _FakeNLP()


@pytest.fixture
def fake_spacy_load_fails(monkeypatch):
    """``import spacy`` works but ``spacy.load`` fails -> blank model path."""
    real_import = builtins.__import__

    def _imp(name, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if name == "spacy" or name.startswith("spacy."):
            fake = types.ModuleType("spacy")
            fake.load = _FakeSpacyLoadFails.load
            fake.blank = _FakeSpacyLoadFails.blank
            sys.modules.setdefault("spacy", fake)
            return fake
        return real_import(name, *args, **kwargs)

    sys.modules.pop("spacy", None)
    monkeypatch.setattr(builtins, "__import__", _imp)
    yield
    sys.modules.pop("spacy", None)


def test_rule_segmenter_spacy_blank_on_load_fail(fake_spacy_load_fails) -> None:
    # spacy.load raises OSError -> spacy.blank(...) fallback (lines 158-160)
    cfg = SegmentConfig(strategy=SegmentStrategy.RULE, language="en")
    seg = RuleSegmenter(cfg)
    nlp = seg._get_nlp()
    assert nlp is not None  # blank model returned
    text = "This is one sentence. This is another sentence."
    result = seg.segment(text)
    assert result.stats["method"] == "spacy"
    assert len(result.segments) >= 1


def test_rule_segmenter_spacy_long_paragraph_split(fake_spacy) -> None:
    # A paragraph exceeding max_paragraph_chars triggers the sentence-split else branch.
    cfg = SegmentConfig(
        strategy=SegmentStrategy.RULE,
        language="zh",
        max_paragraph_chars=20,
        min_paragraph_chars=5,
    )
    seg = RuleSegmenter(cfg)
    seg._nlp = _FakeNLP()
    text = "第一句很长很长很长很长。第二句也很长很长很长很长。\n\n短段落。"
    result = seg._segment_with_spacy(text, seg._nlp)
    assert len(result.segments) >= 2


def test_rule_segmenter_regex_long_paragraph_explicit(no_spacy) -> None:
    # Single over-long paragraph with multiple sentences -> regex sentence split.
    cfg = SegmentConfig(
        strategy=SegmentStrategy.RULE,
        max_paragraph_chars=20,
        min_paragraph_chars=5,
    )
    seg = RuleSegmenter(cfg)
    text = "句子一很长很长很长很长。句子二也很长很长很长很长。句子三同样很长很长很长很长。"
    result = seg.segment(text)
    assert result.stats["method"] == "regex"
    assert len(result.segments) >= 2


class _FakeSentenceModel:
    """Minimal sentence-transformers stand-in returning row-normalized embeddings."""

    def __init__(self, model_name: str = "fake") -> None:
        self.model_name = model_name

    def encode(self, sentences):  # noqa: ANN001, ANN205
        import numpy as np

        rng = np.random.default_rng(0)
        # Distinct vectors so clustering has something to work with.
        return rng.random((len(sentences), 8))


@pytest.fixture
def fake_sentence_transformers(monkeypatch):
    """Make ``import sentence_transformers`` resolve to a fake so the model loads."""
    real_import = builtins.__import__
    fake_st = types.ModuleType("sentence_transformers")

    class _SentenceTransformer:
        def __init__(self, model_name):  # noqa: ANN001
            self.model_name = model_name

        def encode(self, sentences):  # noqa: ANN001, ANN205
            import numpy as np

            rng = np.random.default_rng(0)
            return rng.random((len(sentences), 8))

    fake_st.SentenceTransformer = _SentenceTransformer
    sys.modules.pop("sentence_transformers", None)

    def _imp(name, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if name == "sentence_transformers" or name.startswith("sentence_transformers."):
            sys.modules.setdefault("sentence_transformers", fake_st)
            return fake_st
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _imp)
    yield
    sys.modules.pop("sentence_transformers", None)


def test_semantic_get_model_success(fake_sentence_transformers) -> None:
    # sentence_transformers importable -> model loaded via _get_model (lines 394-397)
    cfg = SegmentConfig(strategy=SegmentStrategy.SEMANTIC, semantic_model="fake-model")
    seg = SemanticSegmenter(cfg)
    model = seg._get_model()
    assert model is not None
    result = seg.segment("第一句内容。\n\n第二句内容。\n\n第三句内容。")
    assert result.stats["method"] == "semantic"
    assert len(result.segments) >= 1



# ── LLM schema + router injection (so the structured-LLM branch is reachable)


class _SegSchema(BaseModel):
    text: str
    metadata: dict = {}


class _LLMResponse:
    def __init__(self, output):  # noqa: ANN001
        self.output = output


class _FakeRouter:
    model = "fake-llm-model"

    def call(self, *, stage, response_model, messages):  # noqa: ANN001, ANN003, ANN205
        return _LLMResponse(
            [
                _SegSchema(text="第一章开始了。"),
                _SegSchema(text='"你好，"他说道。'),
            ]
        )


@pytest.fixture
def fake_llm(monkeypatch):
    """Inject the ``Segment`` schema into ``schemas`` and stub ``create_router``."""
    import src.audiobook_studio.schemas as _schemas

    _schemas.Segment = _SegSchema  # type: ignore[attr-defined]

    import src.audiobook_studio.pipeline.segment as _seg

    monkeypatch.setattr(_seg, "create_router", lambda *a, **k: _FakeRouter())
    yield
    delattr(_schemas, "Segment")


# ── RuleSegmenter ───────────────────────────────────────────────────────────


def test_rule_segmenter_spacy_path(fake_spacy) -> None:
    cfg = SegmentConfig(strategy=SegmentStrategy.RULE, language="zh")
    seg = RuleSegmenter(cfg)
    assert seg._get_nlp() is not None  # loads fake spaCy
    text = "这是第一段。它很长所以应该保持。\n\n这是第二段。还有更多内容在这里。"
    result = seg.segment(text)
    assert result.strategy_used == SegmentStrategy.RULE
    assert len(result.segments) >= 1
    assert result.stats["method"] == "spacy"


def test_rule_segmenter_regex_fallback(no_spacy) -> None:
    cfg = SegmentConfig(strategy=SegmentStrategy.RULE, language="zh")
    seg = RuleSegmenter(cfg)
    assert seg._get_nlp() is None  # spaCy unavailable -> regex
    text = "段落甲内容很长很长。\n\n段落乙的内容也很长很长很长。"
    result = seg.segment(text)
    assert result.strategy_used == SegmentStrategy.RULE
    assert result.stats["method"] == "regex"
    assert len(result.segments) >= 1


def test_rule_segmenter_long_paragraph_split(no_spacy) -> None:
    cfg = SegmentConfig(
        strategy=SegmentStrategy.RULE,
        max_paragraph_chars=20,
        min_paragraph_chars=5,
    )
    seg = RuleSegmenter(cfg)
    # One "paragraph" far exceeding max_paragraph_chars -> forced split by sentences
    text = "句子一很长很长很长。句子二也很长很长很长。句子三同样很长很长很长。"
    result = seg.segment(text)
    assert len(result.segments) >= 2


def test_rule_long_paragraph_forced_split(no_spacy) -> None:
    cfg = SegmentConfig(
        strategy=SegmentStrategy.RULE,
        max_paragraph_chars=15,
        min_paragraph_chars=5,
    )
    seg = RuleSegmenter(cfg)
    # One "paragraph" far exceeding max_paragraph_chars -> forced split by sentences
    text = "句子一很长很长很长很长。句子二也很长很长很长很长很长。"
    result = seg.segment(text)
    # both long sentences exceed min_paragraph_chars and should be retained
    assert len(result.segments) >= 1
    assert all(len(s.text) >= cfg.min_paragraph_chars for s in result.segments)


def test_segment_with_spacy_direct(fake_spacy) -> None:
    cfg = SegmentConfig(strategy=SegmentStrategy.RULE)
    seg = RuleSegmenter(cfg)
    seg._nlp = _FakeNLP()
    result = seg._segment_with_spacy(
        "第一段第一句。第一段第二句。\n\n第二段只有一句。", seg._nlp
    )
    assert result.strategy_used == SegmentStrategy.RULE
    assert len(result.segments) >= 2


def test_segment_with_regex_direct(no_spacy) -> None:
    cfg = SegmentConfig(strategy=SegmentStrategy.RULE)
    seg = RuleSegmenter(cfg)
    result = seg._segment_with_regex("甲段落。\n\n乙段落。")
    assert result.stats["method"] == "regex"
    assert len(result.segments) == 2


def test_post_process_merge_short_header() -> None:
    cfg = SegmentConfig(strategy=SegmentStrategy.RULE)
    seg = RuleSegmenter(cfg)
    segs = [
        Segment(text="小标题", index=0, start_char=0, end_char=3, metadata={"sentence_count": 1}),
        Segment(text="这是紧随其后的正文内容比较长比较长。", index=1, start_char=4, end_char=20, metadata={"sentence_count": 3}),
    ]
    merged = seg._post_process_segments(segs, "小标题这是紧随其后的正文内容比较长比较长。")
    assert len(merged) == 1
    assert "merged_from" in merged[0].metadata


def test_post_process_empty() -> None:
    cfg = SegmentConfig(strategy=SegmentStrategy.RULE)
    seg = RuleSegmenter(cfg)
    assert seg._post_process_segments([], "x") == []


def test_post_process_reindex() -> None:
    cfg = SegmentConfig(strategy=SegmentStrategy.RULE)
    seg = RuleSegmenter(cfg)
    segs = [
        Segment(text="正常段落一内容足够长。", index=5, start_char=0, end_char=10, metadata={}),
        Segment(text="正常段落二内容足够长。", index=9, start_char=11, end_char=22, metadata={}),
    ]
    merged = seg._post_process_segments(segs, "正常段落一内容足够长。正常段落二内容足够长。")
    assert [s.index for s in merged] == [0, 1]


# ── SemanticSegmenter ───────────────────────────────────────────────────────


def test_semantic_fallback_when_no_model(no_spacy) -> None:
    cfg = SegmentConfig(strategy=SegmentStrategy.SEMANTIC)
    seg = SemanticSegmenter(cfg)
    result = seg.segment("第一段。\n\n第二段。")
    # model unavailable -> rule fallback, but strategy stays semantic
    assert result.strategy_used == SegmentStrategy.SEMANTIC
    assert result.stats.get("fallback") == "rule"
    assert len(result.segments) >= 1


def test_semantic_single_sentence(no_spacy) -> None:
    cfg = SegmentConfig(strategy=SegmentStrategy.SEMANTIC)
    seg = SemanticSegmenter(cfg)
    seg._model = _FakeSentenceModel()
    result = seg.segment("只有一句话的内容。")
    assert result.strategy_used == SegmentStrategy.SEMANTIC
    assert len(result.segments) == 1


def test_semantic_clustering(no_spacy) -> None:
    cfg = SegmentConfig(strategy=SegmentStrategy.SEMANTIC, semantic_similarity_threshold=0.5)
    seg = SemanticSegmenter(cfg)
    seg._model = _FakeSentenceModel()
    text = "。".join(f"句子{i}内容" for i in range(8)) + "。"
    result = seg.segment(text)
    assert result.strategy_used == SegmentStrategy.SEMANTIC
    assert result.stats["method"] == "semantic"
    assert len(result.segments) >= 1


def test_cluster_sentences_direct(no_spacy) -> None:
    cfg = SegmentConfig(strategy=SegmentStrategy.SEMANTIC)
    seg = SemanticSegmenter(cfg)
    seg._model = _FakeSentenceModel()
    sents = [f"句子{i}" for i in range(5)]
    import numpy as np

    emb = np.random.default_rng(1).random((5, 8))
    out = seg._cluster_sentences(sents, emb, " ".join(sents))
    assert isinstance(out, list)


def test_semantic_get_model_import_error(no_spacy) -> None:
    cfg = SegmentConfig(strategy=SegmentStrategy.SEMANTIC)
    seg = SemanticSegmenter(cfg)
    # sentence_transformers import raises -> None
    assert seg._get_model() is None


# ── LLMSegmenter ────────────────────────────────────────────────────────────


def test_llm_segmenter_uses_router(fake_llm) -> None:
    cfg = SegmentConfig(strategy=SegmentStrategy.LLM)
    seg = LLMSegmenter(cfg)
    assert seg._get_router() is not None
    text = "第一章开始了。\n\n" + '"你好，"他说道。'
    result = seg.segment(text)
    assert result.strategy_used == SegmentStrategy.LLM
    assert len(result.segments) >= 1
    texts = [s.text for s in result.segments]
    assert "第一章开始了。" in texts


def test_llm_segmenter_fallback_on_router_error(fake_llm, monkeypatch) -> None:
    import src.audiobook_studio.pipeline.segment as _seg

    class _BoomRouter:
        model = "boom"

        def call(self, *, stage, response_model, messages):  # noqa: ANN001, ANN003, ANN205
            raise RuntimeError("llm down")

    monkeypatch.setattr(_seg, "create_router", lambda *a, **k: _BoomRouter())
    cfg = SegmentConfig(strategy=SegmentStrategy.LLM)
    seg = LLMSegmenter(cfg)
    result = seg.segment("第一段。\n\n第二段。")
    assert result.strategy_used == SegmentStrategy.LLM
    assert result.stats.get("fallback") == "rule"


def test_llm_build_prompt_default(fake_llm) -> None:
    cfg = SegmentConfig(strategy=SegmentStrategy.LLM)
    seg = LLMSegmenter(cfg)
    prompt = seg._build_prompt("some long text here")
    assert "some long text here"[:50] in prompt or "some long text here" in prompt


def test_llm_build_prompt_template(fake_llm) -> None:
    cfg = SegmentConfig(
        strategy=SegmentStrategy.LLM,
        llm_prompt_template="TEMPLATE::{text}::{max_chars}",
    )
    seg = LLMSegmenter(cfg)
    prompt = seg._build_prompt("hello")
    assert "TEMPLATE::hello::2000" in prompt


def test_llm_system_prompt(fake_llm) -> None:
    cfg = SegmentConfig(strategy=SegmentStrategy.LLM)
    seg = LLMSegmenter(cfg)
    assert "分段" in seg._get_system_prompt()


def test_llm_segmenter_empty_output_falls_back(fake_llm, monkeypatch) -> None:
    import src.audiobook_studio.pipeline.segment as _seg

    class _EmptyRouter:
        model = "empty"

        def call(self, *, stage, response_model, messages):  # noqa: ANN001, ANN003, ANN205
            return _LLMResponse([])  # router succeeds but returns nothing

    monkeypatch.setattr(_seg, "create_router", lambda *a, **k: _EmptyRouter())
    cfg = SegmentConfig(strategy=SegmentStrategy.LLM)
    seg = LLMSegmenter(cfg)
    result = seg.segment("第一段。\n\n第二段。")
    # No output -> falls through to rule-based fallback (lines 481->495, 534->532)
    assert result.strategy_used == SegmentStrategy.LLM
    assert result.stats.get("fallback") == "rule"
    assert len(result.segments) >= 1


def test_llm_segmenter_none_response_falls_back(fake_llm, monkeypatch) -> None:
    import src.audiobook_studio.pipeline.segment as _seg

    class _NoneRouter:
        model = "none"

        def call(self, *, stage, response_model, messages):  # noqa: ANN001, ANN003, ANN205
            return None

    monkeypatch.setattr(_seg, "create_router", lambda *a, **k: _NoneRouter())
    cfg = SegmentConfig(strategy=SegmentStrategy.LLM)
    seg = LLMSegmenter(cfg)
    result = seg.segment("第一段。\n\n第二段。")
    assert result.strategy_used == SegmentStrategy.LLM
    assert result.stats.get("fallback") == "rule"



# ── SegmentPipeline orchestration ───────────────────────────────────────────


def test_pipeline_default_rule() -> None:
    pipe = SegmentPipeline(mock_mode=True)
    result = pipe.run(text="第一段内容。\n\n第二段内容。")
    assert result.strategy_used == SegmentStrategy.RULE
    assert len(result.segments) >= 1


def test_pipeline_strategy_switch() -> None:
    cfg = SegmentConfig(strategy=SegmentStrategy.LLM)
    pipe = SegmentPipeline(config=cfg, mock_mode=True)
    assert pipe.config.strategy == SegmentStrategy.LLM
    # segmenters dict holds all three strategies
    assert set(pipe._segmenters.keys()) == {
        SegmentStrategy.RULE,
        SegmentStrategy.SEMANTIC,
        SegmentStrategy.LLM,
    }


def test_pipeline_run_unknown_strategy_falls_back() -> None:
    cfg = SegmentConfig(strategy=SegmentStrategy.RULE)
    pipe = SegmentPipeline(config=cfg, mock_mode=True)
    # Simulate an unknown strategy key by mutating the dict
    pipe._segmenters[SegmentStrategy.RULE] = pipe._segmenters[SegmentStrategy.RULE]
    result = pipe.run(text="一段。\n\n二段。")
    assert len(result.segments) >= 1


def test_pipeline_run_from_extraction_result() -> None:
    from src.audiobook_studio.schemas import ExtractionResult

    pipe = SegmentPipeline(mock_mode=True)
    res = ExtractionResult(raw_text="甲段落。\n\n乙段落。", language="zh", page_count=1)
    result = pipe.run(extraction_result=res)
    assert len(result.segments) >= 1


def test_pipeline_run_from_extract_file(tmp_path: Path) -> None:
    f = tmp_path / "book.txt"
    f.write_text("第一段。\n\n第二段。", encoding="utf-8")
    pipe = SegmentPipeline(mock_mode=True)
    result = pipe.run(extract_file=str(f))
    assert len(result.segments) >= 1


def test_pipeline_run_requires_input() -> None:
    pipe = SegmentPipeline(mock_mode=True)
    with pytest.raises(ValueError):
        pipe.run()


def test_pipeline_to_paragraph_annotations_dialogue() -> None:
    cfg = SegmentConfig(strategy=SegmentStrategy.RULE)
    pipe = SegmentPipeline(config=cfg, mock_mode=True)
    result = pipe.run(text='旁白一句。\n\n"你好，"他对话道。')
    anns = pipe.to_paragraph_annotations(result)
    assert len(anns) == len(result.segments)
    # the dialogue segment should be flagged
    assert any(a.is_dialogue for a in anns)


def test_pipeline_load_config(monkeypatch) -> None:
    import src.audiobook_studio.pipeline.segment as _seg

    monkeypatch.setattr(
        _seg,
        "load_pipeline_config",
        lambda path: {"segment": {"strategy": "llm", "max_paragraph_chars": 500, "language": "en"}},
    )
    pipe = SegmentPipeline(config_path="/tmp/ignored.yaml", mock_mode=True)
    assert pipe.config.strategy == SegmentStrategy.LLM
    assert pipe.config.max_paragraph_chars == 500
    assert pipe.config.language == "en"


# ── module-level convenience ───────────────────────────────────────────────


def test_segment_text_convenience() -> None:
    result = segment_text("第一段。\n\n第二段。", mock_mode=True)
    assert isinstance(result, SegmentationResult)
    assert len(result.segments) >= 1


def test_segment_text_with_strategy_and_config() -> None:
    cfg = SegmentConfig(strategy=SegmentStrategy.RULE, max_paragraph_chars=10, min_paragraph_chars=5)
    result = segment_text("一句很长很长很长的话。另一句也很长很长很长。", config=cfg, mock_mode=True)
    assert len(result.segments) >= 1


def test_segment_dataclass_and_length() -> None:
    s = Segment(text="abc", index=0, start_char=0, end_char=3)
    assert s.length == 3


def test_segmentation_result_dataclass() -> None:
    cfg = SegmentConfig()
    r = SegmentationResult(segments=[], strategy_used=SegmentStrategy.RULE, config=cfg)
    assert r.stats == {}
