"""Unit tests for main-content trimming (pipeline/main_content.py).

Drives the real shipped functions with a synthetic book layout
(publishing info + contents + intro + story + activities + back matter)
and with the real Football Forever extraction path.
"""

import os

import pytest

from audiobook_studio.pipeline.main_content import extract_main_content, split_blocks

FRONT = """Football Forever

John Smith

OXFORD UNIVERSITY PRESS

Great Clarendon Street, Oxford, United Kingdom

This eBook edition © Oxford University Press 2016
ISBN: 978 0 19 461346 0
All rights reserved. No part of this publication may be reproduced.

Contents

Chapter 1 The beginning ........ 1
Chapter 2 The middle .......... 9

BEFORE READING

1 Complete the sentences with the names.
a LJ Tom b LJ Sara c LJ the dog
"""

STORY_PARAS = [
    "'Run!' Tom shouted at the top of his voice. The ball was "
    "rolling fast across the wet grass towards the empty goal.",
    "Sara picked it up and laughed. It was the first game of the "
    "season, and nobody wanted to lose on a morning like this.",
    "The crowd went quiet when the captain walked onto the pitch. "
    "He looked tired, but his eyes were bright and full of hope.",
    "By half time the score was two all, and both teams walked "
    "slowly back to the changing rooms without saying a word.",
    "In the last minute Tom kicked the ball high over the keeper, "
    "and the whole town seemed to cheer at exactly the same time.",
]

INLINE_ACTIVITY = """ACTIVITIES

1 Complete the sentences with the words in the box.
2 Match the words with the definitions.
3 Tick the boxes. True or False?

GUESS WHAT

What do you think happens in the next chapter?
"""

BACK = """Read Dominoes for pleasure, or to develop language skills.

If you liked this book, read these other titles in the series.

Word count 5,389

CEFR A2-B1  IELTS 4.0  TOEFL 500

www.oup.com/elt
"""

SAMPLE = (
    FRONT
    + "\n\n"
    + "\n\n".join(STORY_PARAS[:2])
    + "\n\n"
    + INLINE_ACTIVITY
    + "\n\n"
    + "\n\n".join(STORY_PARAS[2:])
    + "\n\n"
    + BACK
)


class TestHeuristicTrimming:
    def test_removes_front_and_back_matter(self):
        result = extract_main_content(SAMPLE)
        assert not result.degraded
        out = result.text
        # front matter gone
        assert "OXFORD" not in out
        assert "ISBN" not in out
        assert "Contents" not in out
        assert "BEFORE READING" not in out
        # back matter gone
        assert "Dominoes" not in out
        assert "Word count" not in out
        assert "CEFR" not in out
        assert "oup.com" not in out

    def test_removes_inline_activities(self):
        result = extract_main_content(SAMPLE)
        out = result.text
        assert "ACTIVITIES" not in out
        assert "Complete the sentences" not in out
        assert "Tick the boxes" not in out
        assert "GUESS WHAT" not in out

    def test_story_preserved_verbatim(self):
        result = extract_main_content(SAMPLE)
        for para in STORY_PARAS:
            assert para in result.text, f"story paragraph lost: {para[:40]}"

    def test_story_is_prefix(self):
        """Output starts with the first story sentence, not front matter."""
        result = extract_main_content(SAMPLE)
        assert result.text.startswith("'Run!'")

    def test_short_text_passthrough(self):
        short = "PDF text"
        result = extract_main_content(short)
        assert result.text == short
        assert result.method == "passthrough"

    def test_disabled_switch_passthrough(self, monkeypatch):
        monkeypatch.setenv("MAIN_CONTENT_FILTER_ENABLED", "false")
        result = extract_main_content(SAMPLE)
        assert result.text == SAMPLE
        assert result.method == "passthrough"


class TestLLMRefinement:
    def test_llm_boundaries_merge(self):
        start = SAMPLE.index("'Run!'")
        end = SAMPLE.index("same time.") + len("same time.")
        fn = lambda text: (start, end)  # noqa: E731
        result = extract_main_content(SAMPLE, llm_boundary_fn=fn)
        assert result.method == "heuristic+llm"
        assert "'Run!'" in result.text

    def test_llm_failure_degrades_to_heuristic(self):
        def boom(text):
            raise RuntimeError("provider down")

        result = extract_main_content(SAMPLE, llm_boundary_fn=boom)
        # honest degrade: heuristic result, non-empty, story intact
        assert result.method == "heuristic"
        assert result.text.strip()
        assert "'Run!'" in result.text

    def test_llm_garbage_boundaries_ignored(self):
        result = extract_main_content(SAMPLE, llm_boundary_fn=lambda t: (10, 20))
        assert result.method == "heuristic"
        assert "'Run!'" in result.text


class TestExtractPipelineIntegration:
    """Drive the real ExtractPipeline.run() with a TXT file carrying
    front/back matter, asserting the trimmed story reaches raw_text."""

    def test_txt_extraction_trims_to_story(self, tmp_path):
        from audiobook_studio.pipeline.extract import ExtractPipeline
        from audiobook_studio.schemas import ExtractionInput

        book = tmp_path / "book.txt"
        book.write_text(SAMPLE, encoding="utf-8")

        pipe = ExtractPipeline(mock_mode=False)
        result = pipe.run(ExtractionInput(file_path=str(book), mime_type="text/plain"))
        assert result.raw_text.startswith("'Run!'")
        assert "OXFORD" not in result.raw_text
        assert "ACTIVITIES" not in result.raw_text
        for para in STORY_PARAS:
            assert para in result.raw_text


class TestRealBook:
    """Real-data assertions on the Football Forever extraction."""

    BOOK = os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "data",
        "mock_data",
        "Football Forever",
        "chapter_01.txt",
    )

    @pytest.fixture(scope="class")
    def trimmed(self, request):
        if not os.path.exists(self.BOOK):
            pytest.skip("Football Forever extraction not present")
        with open(self.BOOK, encoding="utf-8") as f:
            request.cls._trimmed = extract_main_content(f.read())
        return request.cls._trimmed

    def test_no_front_or_back_markers(self, trimmed):
        out = trimmed.text
        for marker in (
            "Oxford University Press",
            "ISBN",
            "BEFORE READING",
            "READING CHECK",
            "GUESS WHAT",
            "Word count",
            "CEFR",
            "Read Dominoes",
            "Complete the sentences",
            "Tick the boxes",
        ):
            assert marker not in out, marker

    def test_story_boundaries(self, trimmed):
        assert trimmed.text.lstrip().startswith("‘Bad! Very bad!’")
        assert trimmed.text.rstrip().endswith("go crazy.")
        for chapter in ("Chapter Two", "Chapter Three", "Chapter Four", "Chapter Five", "Chapter Six"):
            assert chapter in trimmed.text

    def test_story_not_truncated(self, trimmed):
        assert len(trimmed.text) > 20000
        assert not trimmed.degraded
