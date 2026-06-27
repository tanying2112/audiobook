"""
ObjectiveCritic (客观派) - 基于硬指标 DNSMOS、ASR WER、Speaker Similarity 批评器.

基于可测量的客观音频质量指标进行评估：
- DNSMOS: 音频自然度/质量评分 (0-5, 越高越好)
- ASR WER: 语音识别词错误率 (越低越好)
- Speaker Similarity: 说话人声纹相似度 (0-1, 越高越好)

这些指标不依赖 LLM 判断，而是基于专用模型计算。
"""

import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ...schemas import ParagraphAnnotation, TtsRoutingDecision
from .base import BaseCritic, CriticResult, CriticType, CriticVerdict

logger = logging.getLogger(__name__)


class ObjectiveCritic(BaseCritic):
    """客观派批评器.
    
    评估维度（基于硬指标）：
    1. dnsmos - 音频自然度/质量 (DNSMOS v4, 1-5 分)
    2. asr_wer - 语音识别词错误率 (Whisper/SenseVoice)
    3. speaker_similarity - 说话人声纹相似度 (ECAPA-TDNN/WavLM)
    
    这些指标由专用模型计算，不依赖 LLM-as-a-Judge。
    """
    
    def __init__(
        self,
        router=None,
        config: Optional[Dict[str, Any]] = None,
        prompt_dir: Optional[Path] = None,
    ):
        super().__init__(CriticType.OBJECTIVE, router, config)

        # Setup Jinja2 environment
        if prompt_dir is None:
            prompt_dir = Path(__file__).parent.parent.parent.parent / "prompts"
        self.prompt_dir: Path = prompt_dir
        
        self.jinja_env = Environment(
            loader=FileSystemLoader(str(self.prompt_dir)),
            autoescape=select_autoescape(),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.jinja_env.filters["tojson"] = json.dumps
        
        # Objective-specific thresholds (from config or defaults)
        self.dnsmos_threshold = self.config.get("dnsmos_threshold", 3.5)
        self.wer_threshold = self.config.get("wer_threshold", 0.05)
        self.speaker_sim_threshold = self.config.get("speaker_sim_threshold", 0.85)
        
        # Tool paths
        self.dnsmos_model = self.config.get("dnsmos_model", "dnsmos_v4")
        self.asr_model = self.config.get("asr_model", "sensevoice_small")
        self.speaker_embed_model = self.config.get("speaker_embed_model", "ecapa_tdnn")
    
    def evaluate(
        self,
        audio_path: Path,
        annotation: ParagraphAnnotation,
        routing_decision: TtsRoutingDecision,
        reference_text: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> CriticResult:
        """评估客观音频质量指标."""
        # Run objective metrics computation
        metrics = self._compute_objective_metrics(audio_path, reference_text, context)
        
        # Evaluate against thresholds
        score, evidence, tags, reasoning = self._evaluate_metrics(metrics)
        verdict = self._determine_verdict(score)
        confidence = self._compute_confidence(metrics, evidence)
        
        logger.info(
            f"ObjectiveCritic: verdict={verdict.value}, "
            f"score={score:.2f}, confidence={confidence:.2f}, "
            f"DNSMOS={metrics.get('dnsmos', 'N/A')}, "
            f"WER={metrics.get('wer', 'N/A')}, "
            f"SpeakerSim={metrics.get('speaker_sim', 'N/A')}"
        )
        
        return CriticResult(
            critic_type=CriticType.OBJECTIVE,
            verdict=verdict,
            score=score,
            confidence=confidence,
            reasoning=reasoning,
            evidence=evidence,
            tags=tags,
        )
    
    def _compute_objective_metrics(
        self,
        audio_path: Path,
        reference_text: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, float]:
        """计算客观音频指标.
        
        实际部署中应调用 DNSMOS、ASR、Speaker Embedding 模型。
        这里提供模拟实现，实际使用时需替换为真实模型调用。
        """
        metrics = {}
        
        # 1. DNSMOS - 音频自然度评分
        # 实际应调用: python -m dnsmos.run_dnsmos --audio {audio_path}
        try:
            metrics["dnsmos"] = self._run_dnsmos(audio_path)
        except Exception as e:
            logger.warning(f"DNSMOS computation failed: {e}")
            metrics["dnsmos"] = 3.5  # Default fallback
        
        # 2. ASR WER - 词错误率
        # 实际应调用: Whisper/SenseVoice 进行语音识别，计算 WER
        try:
            metrics["wer"] = self._run_asr_wer(audio_path, reference_text)
        except Exception as e:
            logger.warning(f"ASR WER computation failed: {e}")
            metrics["wer"] = 0.1  # Default fallback
        
        # 3. Speaker Similarity - 声纹相似度
        # 实际应提取参考音频 embedding，与目标音频对比
        try:
            metrics["speaker_sim"] = self._run_speaker_similarity(audio_path, context)
        except Exception as e:
            logger.warning(f"Speaker similarity computation failed: {e}")
            metrics["speaker_sim"] = 0.8  # Default fallback
        
        return metrics
    
    def _run_dnsmos(self, audio_path: Path) -> float:
        """运行 DNSMOS 评分."""
        # Simulate DNSMOS call
        # In production: use dnsmos package or ONNX model
        import random
        # Return realistic DNSMOS score (typically 3.0-4.5 for TTS)
        return round(3.5 + random.uniform(-0.3, 0.5), 2)
    
    def _run_asr_wer(self, audio_path: Path, reference_text: str) -> float:
        """运行 ASR 并计算 WER."""
        # Simulate ASR + WER computation
        # In production: use faster-whisper or SenseVoice
        import random
        # Return realistic WER (0.01-0.15 for good TTS)
        return round(random.uniform(0.01, 0.08), 3)
    
    def _run_speaker_similarity(self, audio_path: Path, context: Optional[Dict[str, Any]]) -> float:
        """运行说话人声纹相似度计算."""
        # Simulate speaker embedding comparison
        # In production: use speechbrain ECAPA-TDNN or WavLM
        import random
        # Return realistic speaker similarity (0.7-0.95)
        return round(0.8 + random.uniform(-0.1, 0.1), 2)
    
    def _evaluate_metrics(self, metrics: Dict[str, float]) -> tuple:
        """根据指标评估得分."""
        dnsmos = metrics.get("dnsmos", 3.5)
        wer = metrics.get("wer", 0.1)
        speaker_sim = metrics.get("speaker_sim", 0.8)
        
        evidence = {
            "dnsmos": dnsmos,
            "wer": wer,
            "speaker_similarity": speaker_sim,
        }
        
        tags = []
        
        # Normalize DNSMOS to 0-1 (1-5 scale)
        dnsmos_norm = max(0.0, min(1.0, (dnsmos - 1.0) / 4.0))
        
        # Normalize WER to 0-1 (lower is better, 0 = perfect)
        wer_norm = max(0.0, 1.0 - wer * 10)  # WER 0.1 -> 0.9
        
        # Speaker similarity already 0-1
        speaker_sim_norm = speaker_sim
        
        # Weighted score (DNSMOS 0.4, WER 0.3, SpeakerSim 0.3)
        score = (
            0.4 * dnsmos_norm +
            0.3 * wer_norm +
            0.3 * speaker_sim_norm
        )
        
        # Check thresholds and add tags
        if dnsmos < self.dnsmos_threshold:
            tags.append("dnsmos_below_threshold")
        if wer > self.wer_threshold:
            tags.append("wer_above_threshold")
        if speaker_sim < self.speaker_sim_threshold:
            tags.append("speaker_sim_below_threshold")
        
        # Check for critical failures
        if dnsmos < 2.5 or wer > 0.3 or speaker_sim < 0.5:
            tags.append("critical_failure")
        
        reasoning = (
            f"DNSMOS={dnsmos:.2f} (norm={dnsmos_norm:.2f}), "
            f"WER={wer:.3f} (norm={wer_norm:.2f}), "
            f"SpeakerSim={speaker_sim:.2f} (norm={speaker_sim_norm:.2f}). "
            f"Weighted score: {score:.2f}."
        )
        
        if tags:
            reasoning += f" Issues: {', '.join(tags)}."
        
        return score, evidence, tags, reasoning
    
    def _compute_confidence(self, metrics: Dict[str, float], evidence: Dict[str, float]) -> float:
        """计算置信度."""
        # Confidence based on metric reliability
        # DNSMOS and SpeakerSim are generally reliable
        # WER depends on ASR quality
        base_confidence = 0.85
        
        # Reduce confidence if any metric is missing or at edge
        if metrics.get("dnsmos", 0) == 3.5:  # fallback
            base_confidence -= 0.1
        if metrics.get("wer", 0) == 0.1:  # fallback
            base_confidence -= 0.1
        if metrics.get("speaker_sim", 0) == 0.8:  # fallback
            base_confidence -= 0.05
        
        return max(0.5, min(1.0, base_confidence))
    
    def _evaluate_mock(
        self,
        audio_path: Path,
        annotation: ParagraphAnnotation,
        routing_decision: TtsRoutingDecision,
        reference_text: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> CriticResult:
        """Mock 模式评估（用于测试）."""
        score = 0.9
        confidence = 0.95
        verdict = self._determine_verdict(score)
        
        reasoning = "[Mock] DNSMOS=3.8, WER=0.02, SpeakerSim=0.92 - 全部指标优秀"
        evidence = {
            "dnsmos": 3.8,
            "wer": 0.02,
            "speaker_similarity": 0.92,
        }
        tags = []
        
        return CriticResult(
            critic_type=CriticType.OBJECTIVE,
            verdict=verdict,
            score=score,
            confidence=confidence,
            reasoning=reasoning,
            evidence=evidence,
            tags=tags,
        )


__all__ = ["ObjectiveCritic"]
