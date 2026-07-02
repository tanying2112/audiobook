#!/usr/bin/env python3
"""
Audiobook Studio — 多语言翻译配音系统
========================================
实现多语言翻译配音，保留角色/情绪映射并进行情感连续性检查。
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class EmotionType(Enum):
    """情感类型枚举"""

    NEUTRAL = "neutral"
    HAPPY = "happy"
    SAD = "sad"
    ANGRY = "angry"
    FEARFUL = "fearful"
    SURPRISED = "surprised"
    DISGUSTED = "disgusted"
    OTHER = "other"


@dataclass
class CharacterVoice:
    """角色声音配置"""

    name: str
    language: str
    voice_id: str
    style: str = "neutral"
    pitch_shift: float = 0.0
    speed_rate: float = 1.0
    volume: float = 1.0


@dataclass
class EmotionMapping:
    """情感到声音参数的映射"""

    emotion: EmotionType
    pitch_shift: float  # 半音
    speed_rate: float  # 倍率
    volume: float  # 音量
    energy: float  # 能量 (0-1)


@dataclass
class Segment:
    """音频片段"""

    id: str
    text: str
    character: str
    emotion: EmotionType
    language: str
    start_time: float
    end_time: float
    voice_id: Optional[str] = None
    pitch_shift: float = 0.0
    speed_rate: float = 1.0
    volume: float = 1.0


class MultilingualDubbingManager:
    """多语言翻译配音管理器"""

    def __init__(self):
        # 角色声音库：角色名 -> {语言码 -> 声音配置}
        self.character_voices: Dict[str, Dict[str, CharacterVoice]] = {}

        # 情感映射库
        self.emotion_mappings: Dict[EmotionType, EmotionMapping] = {}

        # 语言对之间的翻译质量矩阵
        self.translation_quality: Dict[Tuple[str, str], float] = {}

        # 初始化默认情感映射
        self._init_default_emotion_mappings()

        # 初始化一些示例角色声音
        self._init_sample_character_voices()

    def _init_default_emotion_mappings(self):
        """初始化默认情感到声音参数的映射"""
        self.emotion_mappings = {
            EmotionType.NEUTRAL: EmotionMapping(
                emotion=EmotionType.NEUTRAL,
                pitch_shift=0.0,
                speed_rate=1.0,
                volume=1.0,
                energy=0.5,
            ),
            EmotionType.HAPPY: EmotionMapping(
                emotion=EmotionType.HAPPY,
                pitch_shift=2.0,  # 提高音调
                speed_rate=1.1,  # 略快
                volume=1.05,  # 稍 loud
                energy=0.8,
            ),
            EmotionType.SAD: EmotionMapping(
                emotion=EmotionType.SAD,
                pitch_shift=-3.0,  # 降低音调
                speed_rate=0.9,  # 放慢
                volume=0.9,  # 更轻
                energy=0.3,
            ),
            EmotionType.ANGRY: EmotionMapping(
                emotion=EmotionType.ANGRY,
                pitch_shift=1.0,  # 轻微提高
                speed_rate=1.2,  # 更快
                volume=1.3,  # 更 loud
                energy=0.9,
            ),
            EmotionType.FEARFUL: EmotionMapping(
                emotion=EmotionType.FEARFUL,
                pitch_shift=-1.0,
                speed_rate=1.1,
                volume=0.8,
                energy=0.7,
            ),
            EmotionType.SURPRISED: EmotionMapping(
                emotion=EmotionType.SURPRISED,
                pitch_shift=3.0,
                speed_rate=1.15,
                volume=1.1,
                energy=0.85,
            ),
            EmotionType.DISGUSTED: EmotionMapping(
                emotion=EmotionType.DISGUSTED,
                pitch_shift=-2.0,
                speed_rate=0.95,
                volume=0.9,
                energy=0.4,
            ),
            EmotionType.OTHER: EmotionMapping(
                emotion=EmotionType.OTHER,
                pitch_shift=0.0,
                speed_rate=1.0,
                volume=1.0,
                energy=0.5,
            ),
        }

    def _init_sample_character_voices(self):
        """初始化示例角色声音库"""
        # 旁白角色
        self.character_voices["旁白"] = {
            "zh-CN": CharacterVoice("旁白", "zh-CN", "zh-CN-XiaoyiNeural", "neutral"),
            "en-US": CharacterVoice("旁白", "en-US", "en-US-JennyNeural", "neutral"),
            "es-ES": CharacterVoice("旁白", "es-ES", "es-ES-ElviraNeural", "neutral"),
            "ja-JP": CharacterVoice("旁白", "ja-JP", "ja-JP-NanamiNeural", "neutral"),
        }

        # 主角角色
        self.character_voices["主角"] = {
            "zh-CN": CharacterVoice("主角", "zh-CN", "zh-CN-YunyangNeural", "friendly"),
            "en-US": CharacterVoice("主角", "en-US", "en-US-GuyNeural", "friendly"),
            "es-ES": CharacterVoice("主角", "es-ES", "es-ES-AlvaroNeural", "friendly"),
            "ja-JP": CharacterVoice("主角", "ja-JP", "ja-JP-KeitaNeural", "friendly"),
        }

        # 反派角色
        self.character_voices["反派"] = {
            "zh-CN": CharacterVoice("反派", "zh-CN", "zh-CN-YunxiNeural", "evil"),
            "en-US": CharacterVoice("反派", "en-US", "en-US-DavisNeural", "evil"),
            "es-ES": CharacterVoice("反派", "es-ES", "es-ES-PabloNeural", "evil"),
            "ja-JP": CharacterVoice("反派", "ja-JP", "ja-JP-TakehitoNeural", "evil"),
        }

    def add_character_voice(self, character: str, language: str, voice_config: CharacterVoice):
        """添加角色声音配置"""
        if character not in self.character_voices:
            self.character_voices[character] = {}
        self.character_voices[character][language] = voice_config

    def add_emotion_mapping(self, emotion: EmotionType, mapping: EmotionMapping):
        """添加或更新情感映射"""
        self.emotion_mappings[emotion] = mapping

    def set_translation_quality(self, source_lang: str, target_lang: str, quality: float):
        """设置语言对之间的翻译质量评分 (0-1)"""
        self.translation_quality[(source_lang, target_lang)] = quality
        self.translation_quality[(target_lang, source_lang)] = quality  # 假设对称

    def get_character_voice(self, character: str, language: str) -> Optional[CharacterVoice]:
        """获取指定角色在指定语言中的声音配置"""
        if character in self.character_voices:
            return self.character_voices[character].get(language)
        return None

    def get_emotion_mapping(self, emotion: EmotionType) -> EmotionMapping:
        """获取情感映射"""
        return self.emotion_mappings.get(emotion, self.emotion_mappings[EmotionType.NEUTRAL])

    def translate_text_preserving_markup(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        character_emotion_pairs: List[Tuple[str, str]] = None,
    ) -> str:
        """
        翻译文本同时保留角色和情感标记

        假设输入文本包含如下格式的标记:
        [character:角色名]文本内容[/character]
        或
        (emotion:情感类型)文本内容(/emotion)
        """
        if character_emotion_pairs is None:
            character_emotion_pairs = []

        # 在这个简化实现中，我们模拟翻译过程
        # 实际实现 würde 调用翻译API (如Google Translate, DeepL等)

        # 保护特殊标记不被翻译
        protected_text = text
        placeholders = {}

        # 保护角色标记
        char_pattern = r"\[character:([^\]]+)\](.*?)\[/character\]"

        def char_replace(match):
            char_name = match.group(1)
            content = match.group(2)
            placeholder = f"__CHAR_PLACEHOLDER_{len(placeholders)}__"
            placeholders[placeholder] = (char_name, content, "character")
            return placeholder

        protected_text = re.sub(char_pattern, char_replace, protected_text, flags=re.DOTALL)

        # 保护情感标记
        emotion_pattern = r"\(emotion:([^)]+)\)(.*?)\(/emotion\)"

        def emotion_replace(match):
            emotion_name = match.group(1)
            content = match.group(2)
            placeholder = f"__EMOTION_PLACEHOLDER_{len(placeholders)}__"
            placeholders[placeholder] = (emotion_name, content, "emotion")
            return placeholder

        protected_text = re.sub(emotion_pattern, emotion_replace, protected_text, flags=re.DOTALL)

        # 调用 LLM 进行真实翻译
        translated_text = self._translate_with_llm(protected_text, source_lang, target_lang)

        # 恢复占位符
        for placeholder, (name, content, tag_type) in placeholders.items():
            if tag_type == "character":
                replacement = f"[character:{name}]{content}[/character]"
            else:  # emotion
                replacement = f"(emotion:{name}){content}(/emotion)"
            translated_text = translated_text.replace(placeholder, replacement)

        return translated_text

    def _translate_with_llm(self, text: str, source_lang: str, target_lang: str) -> str:
        """调用 LLM 进行真实翻译"""
        try:
            from ..llm import create_router

            lang_names = {
                "zh-CN": "中文",
                "en-US": "English",
                "es-ES": "Español",
                "ja-JP": "日本語",
                "fr-FR": "Français",
                "de-DE": "Deutsch",
            }
            target_name = lang_names.get(target_lang, target_lang)

            mock_mode = os.environ.get("MOCK_LLM", "false").lower() == "true"
            router = create_router(mock_mode=mock_mode)

            messages = [
                {
                    "role": "system",
                    "content": (
                        f"You are a professional literary translator. "
                        f"Translate the following text from {source_lang} to {target_name}. "
                        f"Preserve all placeholders like __CHAR_PLACEHOLDER_0__ and __EMOTION_PLACEHOLDER_0__. "
                        f"Only output the translated text, nothing else."
                    ),
                },
                {"role": "user", "content": text},
            ]

            from ..schemas.extraction import ExtractionResult

            result = router.call(
                stage="translate",
                response_model=ExtractionResult,
                messages=messages,
                temperature=0.3,
            )

            if result.output and result.output.raw_text:
                translated = result.output.raw_text.strip()
                if translated:
                    return translated

            return f"[{target_name} translation of: {text}]"
        except Exception as e:
            logger.error(f"LLM translation failed: {e}")
            lang_names = {
                "zh-CN": "中文",
                "en-US": "English",
                "es-ES": "Español",
                "ja-JP": "日本語",
                "fr-FR": "Français",
                "de-DE": "Deutsch",
            }
            target_name = lang_names.get(target_lang, target_lang)
            return f"[{target_name} translation of: {text}]"

    def check_emotional_continuity(
        self, original_segments: List[Segment], translated_segments: List[Segment]
    ) -> Tuple[bool, List[str]]:
        """
        检查翻译后的音频片段在情感上是否连续

        Returns:
            (是否连续, 问题列表)
        """
        issues = []

        if len(original_segments) != len(translated_segments):
            issues.append(f"片段数量不匹配: 原始 {len(original_segments)} vs 翻译 {len(translated_segments)}")
            return False, issues

        for i, (orig, trans) in enumerate(zip(original_segments, translated_segments)):
            # 检查角色是否一致
            if orig.character != trans.character:
                issues.append(f"片段 {i+1}: 角色不匹配 - 原始 '{orig.character}' vs 翻译 '{trans.character}'")

            # 检查情感是否一致
            if orig.emotion != trans.emotion:
                issues.append(f"片段 {i+1}: 情感不匹配 - 原始 '{orig.emotion.value}' vs 翻译 '{trans.emotion.value}'")

            # 检查文本长度合理性（翻译后不应异常变化）
            if orig.text and trans.text:
                length_ratio = len(trans.text) / len(orig.text)
                if length_ratio < 0.3 or length_ratio > 3.0:  # 极端变化
                    issues.append(
                        f"片段 {i+1}: 文本长度异常变化 - "
                        f"原始 {len(orig.text)} 字符 vs 翻译 {len(trans.text)} 字符 "
                        f"(比率: {length_ratio:.2f})"
                    )

        return len(issues) == 0, issues

    def process_multilingual_dubbing(
        self,
        source_segments: List[Segment],
        target_language: str,
        quality_threshold: float = 0.8,
    ) -> Tuple[List[Segment], Dict[str, any]]:
        """
        处理多语言翻译配音流程

        Returns:
            (翻译后的片段列表, 处理报告)
        """
        logger.info(f"🌍 开始多语言翻译配音: {len(source_segments)} 片段 → {target_language}")

        translated_segments = []
        report = {
            "source_segments": len(source_segments),
            "target_language": target_language,
            "successful_translations": 0,
            "failed_translations": 0,
            "warnings": [],
            "emotional_continuity_passed": False,
            "continuity_issues": [],
        }

        # 翻译每个片段
        for segment in source_segments:
            try:
                # 获取目标语言的角色声音
                target_voice = self.get_character_voice(segment.character, target_language)
                if not target_voice:
                    # 如果没有特定角色的声音，使用默认声音
                    report["warnings"].append(
                        f"未找到角色 '{segment.character}' 在语言 '{target_language}' 的声音配置，使用默认声音"
                    )
                    target_voice = CharacterVoice(
                        segment.character,
                        target_language,
                        f"{target_language}-default",
                        "neutral",
                    )

                # 翻译文本（保留标记）
                translated_text = self.translate_text_preserving_markup(
                    segment.text,
                    segment.language,
                    target_language,
                    [(segment.character, segment.emotion.value)],
                )

                # 获取情感映射并应用到声音参数
                emotion_mapping = self.get_emotion_mapping(segment.emotion)

                # 创建翻译后的片段
                translated_segment = Segment(
                    id=f"{segment.id}_{target_language}",
                    text=translated_text,
                    character=segment.character,
                    emotion=segment.emotion,
                    language=target_language,
                    start_time=segment.start_time,  # 时间戳保持不变
                    end_time=segment.end_time,
                    voice_id=target_voice.voice_id,
                    pitch_shift=target_voice.pitch_shift + emotion_mapping.pitch_shift,
                    speed_rate=target_voice.speed_rate * emotion_mapping.speed_rate,
                    volume=target_voice.volume * emotion_mapping.volume,
                )

                translated_segments.append(translated_segment)
                report["successful_translations"] += 1

            except Exception as e:
                report["failed_translations"] += 1
                report["warnings"].append(f"片段 {segment.id} 翻译失败: {str(e)}")

                # 即使翻译失败，也保留原始片段以防中断
                failed_segment = Segment(
                    id=f"{segment.id}_{target_language}_FAILED",
                    text=f"[翻译失败] {segment.text}",
                    character=segment.character,
                    emotion=segment.emotion,
                    language=target_language,
                    start_time=segment.start_time,
                    end_time=segment.end_time,
                )
                translated_segments.append(failed_segment)

        # 检查情感连续性
        continuity_passed, continuity_issues = self.check_emotional_continuity(source_segments, translated_segments)
        report["emotional_continuity_passed"] = continuity_passed
        report["continuity_issues"] = continuity_issues

        if continuity_passed:
            logger.info("✅ 情感连续性检查通过")
        else:
            logger.warning(f"⚠️ 情感连续性检查失败: {len(continuity_issues)} 个问题")
            for issue in continuity_issues[:3]:  # 只显示前3个问题
                logger.info(f"   - {issue}")

        logger.error(f"📊 翻译完成: {report['successful_translations']} 成功, {report['failed_translations']} 失败")

        return translated_segments, report


def main():
    """主函数 - 演示多语言翻译配音系统"""
    logger.info("=== Audiobook Studio 多语言翻译配音演示 ===\n")

    # 创建管理器
    dubbing_manager = MultilingualDubbingManager()

    # 设置一些翻译质量评分（示例）
    dubbing_manager.set_translation_quality("zh-CN", "en-US", 0.95)
    dubbing_manager.set_translation_quality("zh-CN", "es-ES", 0.90)
    dubbing_manager.set_translation_quality("en-US", "zh-CN", 0.93)

    # 创建示例音频片段
    sample_segments = [
        Segment(
            id="seg_001",
            text="[character:旁白](emotion:neutral)欢迎收听这个有声书。(/emotion)[/character]",
            character="旁白",
            emotion=EmotionType.NEUTRAL,
            language="zh-CN",
            start_time=0.0,
            end_time=5.0,
        ),
        Segment(
            id="seg_002",
            text="[character:主角](emotion:happy)今天真是个美好的日子！我感觉非常开心。(/emotion)[/character]",
            character="主角",
            emotion=EmotionType.HAPPY,
            language="zh-CN",
            start_time=5.0,
            end_time=12.0,
        ),
        Segment(
            id="seg_003",
            text="[character:反派](emotion:angry)你以为你能赢我吗？天真！(/emotion)[/character]",
            character="反派",
            emotion=EmotionType.ANGRY,
            language="zh-CN",
            start_time=12.0,
            end_time=18.0,
        ),
        Segment(
            id="seg_004",
            text="[character:旁白](emotion:sparse)然后，主角深吸一口气，准备迎接挑战。(/emotion)[/character]",
            character="旁白",
            emotion=EmotionType.NEUTRAL,  # 注意：这里故意设置为NEUTRAL来测试
            language="zh-CN",
            start_time=18.0,
            end_time=25.0,
        ),
    ]

    logger.info("📋 原始片段:")
    for seg in sample_segments:
        logger.info(f"   {seg.id}: [{seg.character}:{seg.emotion.value}] {seg.text[:30]}...")

    logger.info("\n" + "=" * 60)

    # 翻译到英文
    logger.info("\n🔄 翻译到英语 (en-US)...")
    en_segments, en_report = dubbing_manager.process_multilingual_dubbing(sample_segments, "en-US")

    logger.info("\n📋 英文翻译结果:")
    for seg in en_segments:
        if "_FAILED" not in seg.id:
            logger.info(f"   {seg.id}: [{seg.character}:{seg.emotion.value}] {seg.text[:40]}...")
            logger.info(
                f"      声音: {seg.voice_id}, 音调: {seg.pitch_shift:+.1f}半音, "
                f"速度: {seg.speed_rate:.2f}x, 音量: {seg.volume:.2f}"
            )

    logger.info("\n📊 英文翻译报告:")
    logger.info(f"   情感连续性: {'✅ 通过' if en_report['emotional_continuity_passed'] else '❌ 失败'}")
    if not en_report["emotional_continuity_passed"]:
        for issue in en_report["continuity_issues"][:2]:
            logger.info(f"   - {issue}")

    logger.info("\n" + "=" * 60)

    # 翻译到西班牙语
    logger.info("\n🔄 翻译到西班牙语 (es-ES)...")
    es_segments, es_report = dubbing_manager.process_multilingual_dubbing(sample_segments, "es-ES")

    logger.info("\n📋 西班牙语翻译结果:")
    for seg in es_segments:
        if "_FAILED" not in seg.id:
            logger.info(f"   {seg.id}: [{seg.character}:{seg.emotion.value}] {seg.text[:40]}...")

    logger.info("\n📊 西班牙语翻译报告:")
    logger.info(f"   情感连续性: {'✅ 通过' if es_report['emotional_continuity_passed'] else '❌ 失败'}")

    logger.info("\n" + "=" * 60)
    logger.info("🎉 多语言翻译配音演示完成")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
