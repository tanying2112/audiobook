"""Pipeline Stage 2: Analyze Structure - God's Eye View Analysis.

Generates complete BookAnalysisOutput from raw text.
This is the core "context engineering" stage that provides context
for all downstream paragraph-level processing.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..llm import LLMRouter, create_router
from ..schemas import BookAnalysisInput, BookAnalysisOutput

logger = logging.getLogger(__name__)


class AnalyzeStructurePipeline:
    """Pipeline for book structure analysis (Stage 2)."""

    def __init__(
        self,
        router: Optional[LLMRouter] = None,
        prompt_dir: Optional[str] = None,
        mock_mode: Optional[bool] = None,
    ):
        self.mock_mode = (
            mock_mode
            if mock_mode is not None
            else os.environ.get("MOCK_LLM", "false").lower() == "true"
        )

        # Create router (mock mode passed directly to avoid thread-unsafe env manipulation)
        if router is None:
            self.router = create_router(mock_mode=self.mock_mode)
        else:
            self.router = router

        # Setup Jinja2 environment
        if prompt_dir is None:
            prompt_dir = Path(__file__).parent.parent.parent.parent / "prompts"
        self.prompt_dir = Path(prompt_dir)

        self.jinja_env = Environment(
            loader=FileSystemLoader(str(self.prompt_dir)),
            autoescape=select_autoescape(),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.jinja_env.filters["tojson"] = json.dumps

    def _load_few_shot_examples(self, stage: str) -> str:
        """Load few-shot examples from golden dataset."""
        examples_path = self.prompt_dir / stage / "few_shot.jsonl"
        if not examples_path.exists():
            return "（暂无示例）"

        examples = []
        with open(examples_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    examples.append(json.loads(line))

        # Format as readable examples
        formatted = []
        for i, ex in enumerate(examples[:1], 1):  # Limit to 3 examples
            formatted.append(f"### 示例 {i}\n")
            formatted.append(
                f"输入：{json.dumps(ex['input'], ensure_ascii=False, indent=2)[:2000]}...\n"
            )
            formatted.append(
                f"期望输出：{json.dumps(ex['expected_output'], ensure_ascii=False, indent=2)[:3000]}...\n"
            )
        return "\n".join(formatted)

    def _build_prompt(self, input_data: BookAnalysisInput) -> str:
        """Build the analysis prompt with context injection."""
        template = self.jinja_env.get_template("analyze_structure/v1.j2")

        # Get schema for injection
        schema_json = BookAnalysisOutput.model_json_schema()

        few_shot = self._load_few_shot_examples("analyze_structure")

        return template.render(
            schema_json=schema_json,
            raw_text=input_data.raw_text,
            title_hint=input_data.title_hint,
            author_hint=input_data.author_hint,
            target_difficulty=input_data.target_difficulty,
            few_shot_examples=few_shot,
        )

    def run(self, input_data: BookAnalysisInput) -> BookAnalysisOutput:
        """Execute the analysis pipeline."""
        logger.info(
            f"Starting structure analysis for: {input_data.title_hint or 'untitled'}"
        )

        # Build prompt
        prompt = self._build_prompt(input_data)

        messages = [
            {
                "role": "system",
                "content": "你是专业的有声书结构分析师。请严格按照 JSON Schema 输出分析结果。",
            },
            {"role": "user", "content": prompt},
        ]

        # Call LLM
        try:
            result = self.router.call(
                stage="analyze",
                response_model=BookAnalysisOutput,
                messages=messages,
            )

            # Track compliance
            compliance = result.schema_compliance
            logger.info(
                f"Structure analysis completed: "
                f"schema_compliance={compliance}, "
                f"model={result.model}, "
                f"cost=${result.cost_usd:.6f}, "
                f"latency={result.latency_ms}ms"
            )

            return result.output

        except Exception as e:
            logger.error(f"Structure analysis failed: {e}")
            raise


def analyze_structure(
    raw_text: str,
    title_hint: Optional[str] = None,
    author_hint: Optional[str] = None,
    target_difficulty: str = "B",
    mock_mode: bool = True,
) -> BookAnalysisOutput:
    """Convenience function for structure analysis."""
    input_data = BookAnalysisInput(
        raw_text=raw_text,
        title_hint=title_hint,
        author_hint=author_hint,
        target_difficulty=target_difficulty,
    )
    pipeline = AnalyzeStructurePipeline(mock_mode=mock_mode)
    return pipeline.run(input_data)


if __name__ == "__main__":  # pragma: no cover
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Analyze book structure from text")
    parser.add_argument("input", nargs="?", help="Input text file or direct text")
    parser.add_argument("--title", help="Book title hint")
    parser.add_argument("--author", help="Author hint")
    parser.add_argument(
        "--difficulty",
        default="B",
        choices=["A", "B", "C", "D"],
        help="Target difficulty",
    )
    parser.add_argument("--output", help="Output JSON file")

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    # Read input
    if args.input and Path(args.input).exists():
        with open(args.input, "r", encoding="utf-8") as f:
            test_text = f.read()
    else:
        test_text = args.input or "测试文本内容..."

    try:
        result = analyze_structure(
            test_text,
            title_hint=args.title,
            author_hint=args.author,
            target_difficulty=args.difficulty,
        )
        output_json = json.dumps(result.model_dump(), ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output_json)
        else:
            logger.info(output_json)
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)
