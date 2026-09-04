"""Mock-driven coverage tests for bootstrap_fewshot.py.

These tests push bootstrap_fewshot.py toward the 85% production-coverage
target by exercising the dspy-backed optimizer paths and the file/IO
helpers, using the in-environment mock LM (dspy is available) and temp dirs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.feedback import bootstrap_fewshot as bf
from src.audiobook_studio.feedback.bootstrap_fewshot import (
    BootstrapFewShotOptimizer,
    CharacterRecognitionModule,
    OptimizationMetrics,
    VoiceDesignModule,
    configure_dspy_optimizer,
    extract_paragraphs_from_text,
    load_long_novel_data,
    load_training_examples,
    prepare_training_data_from_books,
    run_bootstrap_optimization,
    run_pipeline_on_book_data,
    save_optimized_prompt,
)


@pytest.fixture(autouse=True)
def _shim_litellm_supported_params(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shim ``litellm.get_supported_openai_params`` for dspy LM construction.

    dspy 3.3.1 calls ``litellm.get_supported_openai_params(model=..., custom_llm_provider=...)``
    when building an LM client (via the ``supported_params`` property). Some litellm builds
    (e.g. this sandbox) lack that attribute, which aborts LM construction before the mock LM
    can answer and fails the forward-pass tests. Provide a no-op shim so the mock-LM tests
    exercise the dspy modules regardless of the installed litellm version. This patches a
    dependency quirk, not the SUT (bootstrap_fewshot).
    """
    try:
        import litellm

        if not hasattr(litellm, "get_supported_openai_params"):
            # ``raising=False`` because a *prior* test (run earlier under
            # ``--random-order``) may have removed this attribute from the
            # ``litellm`` module without restoring it. With the default
            # ``raising=True`` monkeypatch would raise AttributeError on the
            # now-missing attribute and silently no-op (swallowed above), leaving
            # dspy's LM construction to fail with ``module 'litellm' has no
            # attribute 'get_supported_openai_params'``. ``raising=False`` makes
            # the shim self-healing regardless of upstream leaks.
            monkeypatch.setattr(
                litellm,
                "get_supported_openai_params",
                lambda model: [],  # type: ignore[attr-defined]
                raising=False,
            )
    except Exception:
        pass


# ── Pure helpers ─────────────────────────────────────────────────────────────


def test_extract_paragraphs_gutenberg_header_footer() -> None:
    text = (
        "START OF THE PROJECT GUTENBERG EBOOK\n"
        "Title: Test Book\n"
        "This is a long paragraph that should be extracted because it is over twenty characters.\n\n"
        "*** END\n"
        "This should not be extracted because it is after the end marker.\n"
    )
    paras = extract_paragraphs_from_text(text)
    assert paras, "expected paragraphs between markers"
    for p in paras:
        assert "should not be extracted" not in p["text"]
        assert "START OF THE PROJECT" not in p["text"]


def test_extract_paragraphs_metadata_skipped() -> None:
    text = (
        "Title: Foo\n"
        "Author: Bar\n"
        "Release date: 2020\n"
        "This is a real paragraph with enough length to be kept in the output.\n\n"
        "short\n"
    )
    paras = extract_paragraphs_from_text(text)
    texts = [p["text"] for p in paras]
    assert all(not t.startswith("Title:") for t in texts)
    assert any("real paragraph" in t for t in texts)
    assert all("short" not in t for t in texts)


def test_extract_paragraphs_max_paragraphs() -> None:
    text = "\n\n".join(f"Paragraph number {i} with enough text to pass the length filter." for i in range(20))
    paras = extract_paragraphs_from_text(text, max_paragraphs=5)
    assert len(paras) == 5


def test_extract_paragraphs_single_newline_fallback() -> None:
    # No double newlines -> falls back to single newline splitting
    text = "First long paragraph that should be kept here.\nSecond long paragraph that should also be kept."
    paras = extract_paragraphs_from_text(text)
    assert len(paras) == 2


# ── load_long_novel_data ─────────────────────────────────────────────────────


def test_load_long_novel_data_missing_dir(tmp_path: Path) -> None:
    result = load_long_novel_data(str(tmp_path / "does_not_exist"))
    assert result == []


def test_load_long_novel_data_empty_dir(tmp_path: Path) -> None:
    d = tmp_path / "novels"
    d.mkdir()
    result = load_long_novel_data(str(d))
    assert result == []


def test_load_long_novel_data_with_files(tmp_path: Path) -> None:
    d = tmp_path / "novels"
    d.mkdir()
    (d / "book1.txt").write_text(
        "START OF THE PROJECT GUTENBERG\nA long paragraph that is definitely over twenty characters.\n*** END",
        encoding="utf-8",
    )
    books = load_long_novel_data(str(d), max_books=1, max_paragraphs_per_book=3)
    assert len(books) == 1
    assert books[0].num_paragraphs >= 1
    assert books[0].book_name == "book1"


# ── save_optimized_prompt ────────────────────────────────────────────────────


def test_save_optimized_prompt_default_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    p = save_optimized_prompt("annotate_paragraph", "PROMPT TEXT", 3)
    assert p.exists()
    assert p.read_text(encoding="utf-8") == "PROMPT TEXT"
    assert p.name == "v3.j2"


def test_save_optimized_prompt_custom_dir(tmp_path: Path) -> None:
    out = tmp_path / "out"
    p = save_optimized_prompt("edit_for_tts", "X", 1, output_dir=str(out))
    assert p.exists()
    assert "edit_for_tts" in str(p)


# ── dspy module forward passes (mock LM) ─────────────────────────────────────


def test_character_module_forward() -> None:
    configure_dspy_optimizer(use_mock=True)
    mod = CharacterRecognitionModule(prompt_template="extract char")
    out = mod.forward(paragraph_text="Some text about 旁白 narrating.")
    assert isinstance(out, str)


def test_character_module_forward_kwargs() -> None:
    configure_dspy_optimizer(use_mock=True)
    mod = CharacterRecognitionModule()
    out = mod(paragraph_text="Another paragraph for voice design test.")
    assert isinstance(out, str)


def test_voice_module_forward() -> None:
    import dspy
    from dspy import LM

    class VoiceMockLM(LM):
        def __init__(self) -> None:
            super().__init__(model="mock", temperature=0.0)

        def basic_request(self, prompt: str, **kwargs: Any) -> list[dict[str, str]]:
            return [{"text": '{"voice_design": "narrator_male"}'}]

        def __call__(
            self,
            prompt: object | None = None,
            messages: object | None = None,
            **kwargs: Any,
        ) -> list[dict[str, str]]:
            return self.basic_request(str(prompt or ""), **kwargs)

    dspy.configure(lm=VoiceMockLM())
    mod = VoiceDesignModule(prompt_template="voice design")
    out = mod.forward(
        paragraph_text="A sentence with enough length for the mock to respond.",
        character_name="旁白",
        emotion="neutral",
    )
    assert isinstance(out, str)


# ── load_training_examples with temp golden files ────────────────────────────


def test_load_training_examples_from_few_shot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    golden = tmp_path / "tests" / "golden" / "annotate_paragraph"
    golden.mkdir(parents=True)
    (golden / "few_shot.jsonl").write_text(
        json.dumps(
            {
                "input": {
                    "paragraph_text": "Long paragraph text for the character extraction test.",
                    "character_voice_map": [{"canonical_name": "旁白", "suggested_voice_id": "zh_female_1"}],
                },
                "expected_output": {"speaker_canonical_name": "旁白"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    prompt, examples = load_training_examples("annotate_paragraph")
    assert examples
    text, gt = examples[0]
    assert gt["character"] == "旁白"
    assert gt["voice"] == "zh_female_1"
    assert prompt  # non-empty fallback or loaded


def test_load_training_examples_fallback_bootstrap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # No few_shot.jsonl; fall back to bootstrap_examples.json
    golden = tmp_path / "tests" / "golden"
    golden.mkdir(parents=True)
    (golden / "bootstrap_examples.json").write_text(
        json.dumps(
            {
                "examples": [
                    {
                        "text": "A long paragraph used as bootstrap training text.",
                        "character": "旁白",
                        "voice": "zh_male_1",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    prompt, examples = load_training_examples("annotate_paragraph")
    assert examples
    assert examples[0][1]["character"] == "旁白"
    assert examples[0][1]["voice"] == "zh_male_1"


# ── BootstrapFewShotOptimizer.optimize (mock LM + GEPA) ──────────────────────


def test_optimizer_optimize_empty_training() -> None:
    opt = BootstrapFewShotOptimizer("annotate_paragraph")
    res = opt.optimize("initial", [])
    assert res.iterations_completed == 0
    assert res.stopped_early is False
    assert res.optimized_prompt == "initial"


def test_optimizer_optimize_with_examples() -> None:
    configure_dspy_optimizer(use_mock=True)
    opt = BootstrapFewShotOptimizer("annotate_paragraph", budget_limit=10, early_stop_patience=2)
    training = [
        ("A long paragraph describing the narrator's voice.", {"character": "旁白", "voice": "zh_female_1"}),
        ("Another lengthy paragraph for character recognition.", {"character": "张三", "voice": "zh_male_2"}),
    ]
    res = opt.optimize("initial prompt", training)
    assert isinstance(res, bf.OptimizationResult)
    assert res.optimized_prompt
    assert res.metrics is not None
    assert res.improvement_ratio >= 0.0


def test_optimizer_improvement_negative_capped() -> None:
    opt = BootstrapFewShotOptimizer("annotate_paragraph")
    m = OptimizationMetrics(overall_score=0.1)
    assert opt._compute_improvement(m) == 0.0


def test_optimizer_improvement_positive() -> None:
    opt = BootstrapFewShotOptimizer("annotate_paragraph")
    m = OptimizationMetrics(overall_score=0.8)
    # baseline 0.5 -> (0.8-0.5)/0.5 = 0.6
    assert opt._compute_improvement(m) == pytest.approx(0.6)


def test_optimizer_extract_prompt_no_signature() -> None:
    opt = BootstrapFewShotOptimizer("annotate_paragraph")
    # Plain object without a `predict` attribute -> falls back
    fake = type("FakeModule", (), {})()
    assert opt._extract_prompt_from_module(fake, "fallback") == "fallback"


def test_optimizer_extract_prompt_with_detailed_results() -> None:
    opt = BootstrapFewShotOptimizer("annotate_paragraph")
    fake = MagicMock()
    fake.detailed_results = MagicMock(
        val_aggregate_scores=[0.5, 0.6],
        highest_score_achieved_per_val_task=[0.7],
    )
    frontier = opt._extract_pareto_frontier(fake)
    assert frontier is not None
    assert len(frontier) == 2


def test_optimizer_extract_prompt_no_frontier() -> None:
    opt = BootstrapFewShotOptimizer("annotate_paragraph")
    assert opt._extract_pareto_frontier(MagicMock(spec=[])) is None


def test_run_pipeline_on_book_data_pipeline_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    d = tmp_path / "novels"
    d.mkdir()
    (d / "b.txt").write_text(
        "START OF THE PROJECT GUTENBERG\nA long paragraph that is kept.\n*** END", encoding="utf-8"
    )
    books = load_long_novel_data(str(d))
    # Force pipeline import to raise so the except branch is covered
    with patch("src.audiobook_studio.feedback.bootstrap_fewshot.Path.read_text", side_effect=RuntimeError("boom")):
        result = run_pipeline_on_book_data(books[0])
    assert result.character_examples == []


def test_prepare_training_data_from_books_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    d = tmp_path / "empty"
    d.mkdir()
    monkeypatch.setattr(bf, "DEFAULT_LONG_NOVEL_DIR", str(d))
    examples = prepare_training_data_from_books(str(d))
    assert examples == []


# ── run_bootstrap_optimization ───────────────────────────────────────────────


def test_run_bootstrap_optimization_with_examples(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    golden = tmp_path / "tests" / "golden"
    golden.mkdir(parents=True)
    (golden / "bootstrap_examples.json").write_text(
        json.dumps(
            {
                "examples": [
                    {
                        "text": "A long paragraph for bootstrap optimization run.",
                        "character": "旁白",
                        "voice": "zh_female_1",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    configure_dspy_optimizer(use_mock=True)
    result = run_bootstrap_optimization("annotate_paragraph")
    assert result is not None
    assert isinstance(result.optimized_prompt, str)


def test_run_bootstrap_optimization_no_examples(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    golden = tmp_path / "golden" / "annotate_paragraph"
    golden.mkdir(parents=True)
    # few_shot.jsonl exists but empty -> no examples
    (golden / "few_shot.jsonl").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = run_bootstrap_optimization("annotate_paragraph")
    assert result is None


def test_run_bootstrap_optimization_exception(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    golden = tmp_path / "tests" / "golden" / "annotate_paragraph"
    golden.mkdir(parents=True)
    (golden / "few_shot.jsonl").write_text(
        json.dumps(
            {
                "input": {"paragraph_text": "Long paragraph text for exception test.", "character_voice_map": []},
                "expected_output": {"speaker_canonical_name": "旁白"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    # Inject a failure inside the optimizer.optimize to hit the except branch
    with patch.object(BootstrapFewShotOptimizer, "optimize", side_effect=RuntimeError("injected failure")):
        result = run_bootstrap_optimization("annotate_paragraph")
    assert result is None


def test_run_pipeline_on_book_data_success(tmp_path: Path) -> None:
    d = tmp_path / "novels"
    d.mkdir()
    book = d / "book1.txt"
    book.write_text(
        "START OF THE PROJECT GUTENBERG EBOOK\n"
        + "\n\n".join(
            f"Paragraph number {i} with enough length to be extracted as a real paragraph." for i in range(15)
        )
        + "\n*** END",
        encoding="utf-8",
    )
    books = load_long_novel_data(str(d))
    assert books
    result = run_pipeline_on_book_data(books[0], stage="annotate_paragraph", mock_mode=True)
    # In mock mode the pipeline should populate at least some examples
    assert result.num_paragraphs >= 1
    assert isinstance(result.character_examples, list)


def test_prepare_training_data_from_books_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    d = tmp_path / "novels"
    d.mkdir()
    (d / "book1.txt").write_text(
        "START OF THE PROJECT GUTENBERG EBOOK\n"
        + "\n\n".join(f"Paragraph {i} long enough to be kept by the extraction logic in mock mode." for i in range(10))
        + "\n*** END",
        encoding="utf-8",
    )
    monkeypatch.setattr(bf, "DEFAULT_LONG_NOVEL_DIR", str(d))
    examples = prepare_training_data_from_books(str(d), mock_mode=True, max_paragraphs_per_book=5)
    # May be empty if mock pipeline yields no characters, but must not raise
    assert isinstance(examples, list)


def test_optimizer_gepa_compile_exception() -> None:
    configure_dspy_optimizer(use_mock=True)
    opt = BootstrapFewShotOptimizer("annotate_paragraph", budget_limit=10)
    training = [
        ("A long paragraph describing the narrator's voice.", {"character": "旁白", "voice": "zh_female_1"}),
    ]
    with patch("dspy.teleprompt.gepa.GEPA.compile", side_effect=RuntimeError("gepa boom")):
        res = opt.optimize("initial", training)
    # Falls back to the initial module; must still return a result
    assert res is not None
    assert res.optimized_prompt == "initial"


def test_load_long_novel_data_read_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    d = tmp_path / "novels"
    d.mkdir()
    (d / "bad.txt").write_text("content", encoding="utf-8")
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError("read fail")))
    books = load_long_novel_data(str(d))
    assert books == []
