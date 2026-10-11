"""Batch 3.1 — audio_director stage: LLM 音频导演 (逐句演绎建议).

链路: edit_for_tts 后的段落文本 → 预切句 (_split_sentences 同源) →
LLM 按 prompts/audio_director/vN.j2 生成 sentence_overrides →
(经 StageRegistry.apersist) 仅在 Paragraph.sentence_overrides 为空时落库
→ SynthesizePipeline 逐句合成消费 (人工编辑优先于导演建议)。

诚实性边界:
  - mock 模式 → 空 overrides (no_direction), 绝不伪造演绎参数
  - heuristic_fallback (Kill-Switch) → 空 overrides + confidence=0
  - idx 越界 / 全轴 None 的建议 → 丢弃并告警
  - LLM 建议数值一律 clamp 到合成引擎安全域
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional, Union

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..llm import LLMRouter, create_router
from ..schemas.audio_director import (
    AudioDirectorInput,
    AudioDirectorOutput,
    SentenceOverrideSuggestion,
)

logger = logging.getLogger(__name__)

# LLM 建议的安全 clamp 域 (schema 只做粗界, 这里收窄到合成引擎实测安全域)
_SPEED_RANGE = (0.6, 1.5)    # kokoro/edge 实测稳定域 (v6 校准 0.76-1.3)
_PITCH_RANGE = (-6.0, 6.0)   # ffmpeg 带式移位界
_GAIN_RANGE = (-6.0, 6.0)     # 与 schema 一致


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


class AudioDirectorPipeline:
    """LLM 音频导演: 段落文本 → 逐句演绎建议."""

    def __init__(
        self,
        router: Optional[LLMRouter] = None,
        prompt_dir: Optional[Union[str, Path]] = None,
        mock_mode: Optional[bool] = None,
    ):
        self.mock_mode = (
            mock_mode if mock_mode is not None
            else os.environ.get("MOCK_LLM", "false").lower() == "true"
        )
        if router is None:
            self.router = create_router(mock_mode=self.mock_mode)
        else:
            self.router = router

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

    def _load_few_shot(self, stage: str) -> str:
        examples_path = self.prompt_dir / stage / "few_shot.jsonl"
        if not examples_path.exists():
            return "(暂无示例)"
        formatted = []
        with open(examples_path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if line.strip() and i < 3:
                    ex = json.loads(line)
                    formatted.append(
                        f"### 示例 {i + 1}\n输入：{json.dumps(ex['input'], ensure_ascii=False)[:1500]}\n"
                        f"期望输出：{json.dumps(ex['expected_output'], ensure_ascii=False)[:2000]}"
                    )
        return "\n".join(formatted) if formatted else "(暂无示例)"

    def _build_prompt(self, input_data: AudioDirectorInput) -> str:
        template = self.jinja_env.get_template("audio_director/v1.j2")
        return template.render(
            paragraph_text=input_data.paragraph_text,
            sentences=input_data.sentences,
            speaker_name=input_data.speaker_name,
            emotion=input_data.emotion,
            emotion_intensity=input_data.emotion_intensity,
            is_dialogue=input_data.is_dialogue,
            language=input_data.language,
            voice_id=input_data.voice_id,
            schema_json=AudioDirectorOutput.model_json_schema(),
            few_shot_examples=self._load_few_shot("audio_director"),
        )

    def _sanitize(
        self, output: AudioDirectorOutput, n_sentences: int
    ) -> AudioDirectorOutput:
        """丢弃越界/空建议, clamp 数值 (LLM 输出不信任原则)."""
        clean: list[SentenceOverrideSuggestion] = []
        for ovr in output.sentence_overrides:
            if ovr.idx >= n_sentences:
                logger.warning(
                    "audio_director: 丢弃越界建议 idx=%d (共 %d 句)", ovr.idx, n_sentences
                )
                continue
            if all(
                getattr(ovr, f) is None
                for f in ("voice_id", "speed", "pitch_st", "gain_db", "pause_after_ms", "pause_category")
            ):
                continue  # 全轴缺省 = 无效建议
            if ovr.speed is not None:
                ovr.speed = round(_clamp(ovr.speed, *_SPEED_RANGE), 2)
            if ovr.pitch_st is not None:
                ovr.pitch_st = round(_clamp(ovr.pitch_st, *_PITCH_RANGE), 1)
            if ovr.gain_db is not None:
                ovr.gain_db = round(_clamp(ovr.gain_db, *_GAIN_RANGE), 1)
            clean.append(ovr)
        clean.sort(key=lambda o: o.idx)
        output.sentence_overrides = clean
        return output

    def run(self, input_data: AudioDirectorInput) -> AudioDirectorOutput:
        n = len(input_data.sentences)
        if n == 0:
            logger.info("audio_director: 段落无可切句, 无需导演")
            return AudioDirectorOutput(
                sentence_overrides=[], rationale="无可切句", confidence=0.0
            )
        if n == 1:
            # 单句段落: 段落级参数已足够, 演绎无逐句空间 (末句停顿由段落边界处理)
            logger.info("audio_director: 单句段落跳过 (段落级参数已覆盖)")
            return AudioDirectorOutput(
                sentence_overrides=[], rationale="单句段落无逐句演绎空间", confidence=0.0
            )

        if self.mock_mode:
            return AudioDirectorOutput(
                sentence_overrides=[], rationale="mock_mode_no_direction", confidence=0.0
            )

        prompt = self._build_prompt(input_data)
        messages = [
            {
                "role": "system",
                "content": "你是有声书音频导演。为段落标注逐句演绎参数，严格按 JSON Schema 输出。",
            },
            {"role": "user", "content": prompt},
        ]

        try:
            result = self.router.call(
                stage="audio_director",
                response_model=AudioDirectorOutput,
                messages=messages,
            )
            # Kill-Switch 兜底: 不产伪造演绎 (占位文本/空 overrides 不可信)
            if getattr(result, "model", "") == "heuristic_fallback":
                logger.warning(
                    "audio_director: heuristic fallback, 诚实返回空建议"
                )
                return AudioDirectorOutput(
                    sentence_overrides=[],
                    rationale="heuristic_fallback_no_direction",
                    confidence=0.0,
                )
            output: AudioDirectorOutput = result.output
            output = self._sanitize(output, n)
            logger.info(
                "audio_director: %d/%d 句获演绎建议 (confidence=%.2f, model=%s)",
                len(output.sentence_overrides), n, output.confidence, result.model,
            )
            from ..monitoring import record_stage_performance

            record_stage_performance(
                stage="audio_director",
                latency_ms=result.latency_ms,
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                cost_usd=result.cost_usd,
                success=True,
                provider=(result.model.split("/")[0] if "/" in result.model else result.model),
                model=result.model,
            )
            return output
        except Exception as e:  # noqa: BLE001
            # 导演是增强层: 失败不阻断管线, 诚实降级为无建议
            logger.warning("audio_director failed (%s); 降级为无演绎建议", e)
            return AudioDirectorOutput(
                sentence_overrides=[],
                rationale=f"director_failed: {str(e)[:120]}",
                confidence=0.0,
            )


def audio_director(
    paragraph_text: str,
    sentences: Optional[list[str]] = None,
    mock_mode: bool = True,
    **context,
) -> AudioDirectorOutput:
    """便捷入口: 自动切句 (与合成侧同源) 后运行导演."""
    if sentences is None:
        from .synthesize import _split_sentences

        sentences = _split_sentences(paragraph_text)
    input_data = AudioDirectorInput(
        paragraph_text=paragraph_text, sentences=sentences, **context
    )
    pipeline = AudioDirectorPipeline(mock_mode=mock_mode)
    return pipeline.run(input_data)
