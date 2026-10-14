"""Pipeline Stage: Text Clean — SRT/字幕文本清洗为可读版本.

运行时机：synthesize 阶段之后、quality 阶段之前
输入：SRT 文件路径（来自 export 阶段产出）
输出：清洗后的可读文本（段落结构、修正断词、人名规范化）

用法：
    pipeline = TextCleanPipeline()
    result = pipeline.run(srt_path="output/project_15.srt")
    # result.cleaned_text, result.paragraphs
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..export.srt_cleaner import clean_srt_to_readable_text
from ..schemas import TextCleanConfig, TextCleanInput, TextCleanResult

logger = logging.getLogger(__name__)


@dataclass
class TextCleanStageResult:
    """文本清洗阶段结果."""

    cleaned_text: str
    paragraphs: List[str]
    stats: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    output_path: str = ""


class TextCleanPipeline:
    """文本清洗 Pipeline（可作为独立 Stage 或工具类使用）."""

    def __init__(
        self,
        config: Optional[TextCleanConfig] = None,
        config_path: Optional[str] = None,
        mock_mode: Optional[bool] = None,
    ):
        """初始化文本清洗 Pipeline.

        Args:
            config: TextCleanConfig 对象
            config_path: YAML 配置文件路径
            mock_mode: 是否使用 Mock LLM
        """
        if mock_mode is not None:
            self.mock_mode = mock_mode
        else:
            self.mock_mode = os.environ.get("MOCK_LLM", "false").lower() == "true"

        # 加载配置
        if config is not None:
            self.config = config
        elif config_path:
            self.config = self._load_config(config_path)
        else:
            self.config = TextCleanConfig()

        logger.info(f"TextCleanPipeline initialized (mock_mode={self.mock_mode}, use_llm={self.config.use_llm})")

    def _load_config(self, config_path: str) -> TextCleanConfig:
        """从 YAML 文件加载配置."""
        import yaml

        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        tc = raw.get("text_clean", {})
        return TextCleanConfig(
            use_llm=tc.get("use_llm", False),
            llm_prompt_template=tc.get("llm_prompt_template"),
            name_normalization=tc.get("name_normalization", {}),
            protected_patterns=tc.get("protected_patterns", []),
        )

    def run(
        self,
        srt_path: Optional[str] = None,
        input_data: Optional[TextCleanInput] = None,
    ) -> TextCleanStageResult:
        """执行文本清洗.

        Args:
            srt_path: SRT 文件路径
            input_data: TextCleanInput 对象（优先级更高）

        Returns:
            TextCleanStageResult
        """
        # 解析输入
        if input_data is not None:
            srt_path = input_data.srt_path
            use_llm = input_data.use_llm or self.config.use_llm
            llm_prompt = input_data.llm_prompt or self.config.llm_prompt_template
        elif srt_path is not None:
            use_llm = self.config.use_llm
            llm_prompt = self.config.llm_prompt_template
        else:
            raise ValueError("Must provide srt_path or input_data")

        srt_path = Path(srt_path)
        if not srt_path.exists():
            raise FileNotFoundError(f"SRT file not found: {srt_path}")

        # 输出路径
        output_path = srt_path.with_suffix("_readable.txt")

        logger.info(f"Cleaning SRT: {srt_path} -> {output_path} (use_llm={use_llm})")

        # 执行清洗
        try:
            cleaned_text = clean_srt_to_readable_text(
                srt_path=srt_path,
                output_path=output_path,
                use_llm=use_llm,
                llm_prompt=llm_prompt,
            )

            # 统计信息
            paragraphs = [p.strip() for p in cleaned_text.split("\n\n") if p.strip()]
            stats = {
                "char_count": len(cleaned_text),
                "paragraph_count": len(paragraphs),
                "avg_paragraph_len": sum(len(p) for p in paragraphs) / max(len(paragraphs), 1),
                "use_llm": use_llm,
            }

            return TextCleanStageResult(
                cleaned_text=cleaned_text,
                paragraphs=paragraphs,
                stats=stats,
                output_path=str(output_path),
            )

        except Exception as e:
            logger.error(f"Text clean failed: {e}")
            raise

    def to_schema_result(self, result: TextCleanStageResult, input_data: TextCleanInput) -> TextCleanResult:
        """转换为 Schema 定义的结果对象."""
        return TextCleanResult(
            cleaned_text=result.cleaned_text,
            paragraphs=result.paragraphs,
            stats=result.stats,
            warnings=result.warnings,
            source_srt=input_data.srt_path,
            llm_used=self.config.use_llm,
        )


# ── 便捷函数 ─────────────────────────────────────────────────────────────


def clean_text(
    srt_path: str,
    use_llm: bool = False,
    config: Optional[TextCleanConfig] = None,
    mock_mode: bool = False,
) -> TextCleanStageResult:
    """便捷函数：直接清洗 SRT 文件."""
    pipeline = TextCleanPipeline(config=config, mock_mode=mock_mode)
    if config:
        pipeline.config.use_llm = use_llm
    return pipeline.run(srt_path=srt_path)


if __name__ == "__main__":  # pragma: no cover
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 2:
        print("Usage: python text_clean.py <input.srt> [--llm]")
        sys.exit(1)

    input_path = sys.argv[1]
    use_llm = "--llm" in sys.argv

    pipeline = TextCleanPipeline(mock_mode=False)
    result = pipeline.run(srt_path=input_path)
    print(f"Cleaned: {result.output_path}")
    print(f"Stats: {result.stats}")
    print(f"Preview: {result.cleaned_text[:500]}...")
