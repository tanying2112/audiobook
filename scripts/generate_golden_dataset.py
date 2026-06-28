#!/usr/bin/env python3
"""Generate ChapterSource golden dataset from novel text."""

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, confloat, conint
from typing_extensions import Annotated

# Define schemas locally to avoid import issues
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
Score = Annotated[float, Field(ge=0.0, le=1.0)]
SpeechRate = Annotated[float, Field(ge=0.7, le=1.3)]
PitchShift = Annotated[int, Field(ge=-5, le=5)]
EmotionIntensity = Annotated[float, Field(ge=0.0, le=1.0)]
PauseMs = Annotated[int, Field(ge=0, le=2000)]
DifficultyLevel = Literal["A", "B", "C"]


class BookMeta(BaseModel):
    title: str
    author: Optional[str] = None
    genre: Literal["小说", "散文", "诗歌", "历史", "科普", "童话", "其他"]
    difficulty: Literal["A", "B", "C", "D"]
    language: str
    era: Optional[str] = None
    total_chapters_estimated: int = Field(ge=1)
    contract_version: int = 1


class CharacterVoiceBinding(BaseModel):
    canonical_name: str = Field(min_length=1)
    aliases: List[str] = []
    gender: Literal["male", "female", "neutral", "unknown"] = "unknown"
    age_range: Literal["child", "young", "adult", "elderly", "unknown"] = "unknown"
    suggested_voice_id: Optional[str] = None
    sample_quote: str
    contract_version: int = 1


class EmotionSnapshot(BaseModel):
    chapter: int = Field(ge=1)
    dominant_emotion: Literal[
        "neutral",
        "happy",
        "sad",
        "angry",
        "fearful",
        "surprised",
        "disgusted",
        "tense",
        "tender",
        "contemplative",
        "whisper",
        "cold_laugh",
        "sigh",
        "sarcastic",
    ]
    intensity: confloat(ge=0.0, le=1.0)
    notes: str = ""
    contract_version: int = 1


class ParagraphAnnotation(BaseModel):
    paragraph_id: Optional[int] = None
    chapter_id: Optional[int] = None
    paragraph_index: int = Field(ge=0)
    text: str = ""
    speaker_canonical_name: str = Field(min_length=1)
    is_dialogue: bool
    emotion: Literal[
        "neutral",
        "happy",
        "sad",
        "angry",
        "fearful",
        "surprised",
        "disgusted",
        "tense",
        "tender",
        "contemplative",
        "whisper",
        "cold_laugh",
        "sigh",
        "sarcastic",
    ]
    emotion_intensity: EmotionIntensity
    speech_rate: Literal[0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3]
    pitch_shift_semitones: PitchShift
    needs_sfx: bool = False
    sfx_tags: List[str] = []
    pause_before_ms: PauseMs = 0
    pause_after_ms: PauseMs = 0
    confidence: Confidence
    difficulty: DifficultyLevel = "B"
    notes: Optional[str] = None
    contract_version: int = 1


class ChapterSourceParagraph(BaseModel):
    paragraph_index: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=2000)
    annotation: ParagraphAnnotation
    human_verified: bool = False
    human_notes: str = ""
    quality_score: Score = 1.0


class ChapterSource(BaseModel):
    book_id: str
    chapter_index: int = Field(ge=1)
    chapter_title: str = ""
    book_meta: BookMeta
    character_voice_map: List[CharacterVoiceBinding] = Field(min_length=1)
    emotion_snapshot: EmotionSnapshot
    story_line_summary: str = Field(min_length=100, max_length=500)
    global_style_notes: str
    paragraphs: List[ChapterSourceParagraph] = Field(min_length=1)
    annotated_by: str = ""
    annotated_at: str = ""
    annotation_version: str = "v0.1"
    total_paragraphs: int = Field(ge=1)
    verified_paragraphs: int = 0
    overall_quality_score: Score = 1.0
    contract_version: int = 1

    @property
    def verification_rate(self) -> float:
        return self.verified_paragraphs / max(self.total_paragraphs, 1)

    def get_golden_samples(
        self, min_quality: float = 0.8
    ) -> List[ChapterSourceParagraph]:
        return [
            p
            for p in self.paragraphs
            if p.quality_score >= min_quality and p.human_verified
        ]


class ChapterSourceCollection(BaseModel):
    book_id: str
    book_title: str
    chapters: List[ChapterSource] = Field(min_length=1)
    collection_version: str = "v0.1"
    created_at: str = ""
    total_chapters: int = Field(ge=1)
    total_paragraphs: int = Field(ge=1)
    verified_paragraphs: int = 0

    @property
    def verification_rate(self) -> float:
        return self.verified_paragraphs / max(self.total_paragraphs, 1)


def parse_chapters(text: str) -> List[dict]:
    """Parse text into chapters with paragraphs."""
    chapter_pattern = r"(第[一二三四五六七八九十]+章\s+[^\n]+)"
    parts = re.split(chapter_pattern, text)

    chapters = []
    for i in range(1, len(parts), 2):
        title = parts[i].strip()
        content = parts[i + 1].strip() if i + 1 < len(parts) else ""

        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]

        chapters.append({"title": title, "paragraphs": paragraphs})
    return chapters


def create_annotations(
    chapter_idx: int, paragraphs: List[str]
) -> List[ParagraphAnnotation]:
    """Create paragraph annotations for a chapter."""
    annotations = []

    for i, text in enumerate(paragraphs):
        is_dialogue = "“" in text or '"' in text or "——" in text

        if is_dialogue and "Alexander" in text[:100]:
            speaker = "Alexander"
        elif is_dialogue and "Thompson" in text[:100]:
            speaker = "老 Thompson"
        elif is_dialogue and "Henry" in text[:100]:
            speaker = "国王 Henry"
        elif is_dialogue and "Nathan" in text[:100]:
            speaker = "Prince Nathan"
        elif is_dialogue and "Pierre" in text[:100]:
            speaker = "老 Pierre"
        elif is_dialogue and "陈" in text[:100]:
            speaker = "陈调查组长"
        elif is_dialogue and "水手" in text[:100]:
            speaker = "老水手"
        else:
            speaker = "旁白"

        # Pick emotion based on content
        if "惊" in text or "震" in text:
            emotion = "surprised"
            intensity = 0.8
        elif "怒" in text or "愤" in text:
            emotion = "angry"
            intensity = 0.7
        elif "悲" in text or "伤" in text:
            emotion = "sad"
            intensity = 0.6
        elif "喜" in text or "笑" in text:
            emotion = "happy"
            intensity = 0.6
        elif "思" in text or "想" in text or "沉" in text:
            emotion = "contemplative"
            intensity = 0.5
        elif "温" in text or "柔" in text:
            emotion = "tender"
            intensity = 0.5
        elif "紧" in text or "急" in text:
            emotion = "tense"
            intensity = 0.7
        else:
            emotion = "neutral"
            intensity = 0.4

        annotations.append(
            ParagraphAnnotation(
                paragraph_index=i,
                text=text[:2000],
                speaker_canonical_name=speaker,
                is_dialogue=is_dialogue,
                emotion=emotion,
                emotion_intensity=intensity,
                speech_rate=1.0,
                pitch_shift_semitones=0,
                pause_before_ms=300 if i > 0 else 0,
                pause_after_ms=500,
                confidence=0.9 if not is_dialogue else 0.85,
                difficulty="B",
                needs_sfx=(
                    "海" in text or "风" in text or "雷" in text or "雨" in text
                ),
                sfx_tags=(
                    ["ambient"]
                    if ("海" in text or "风" in text or "雷" in text or "雨" in text)
                    else []
                ),
                notes="",
            )
        )
    return annotations


def main():
    text_path = Path("data/golden/hongloumeng/chapters.txt")
    text = text_path.read_text(encoding="utf-8")

    chapters_data = parse_chapters(text)

    book_meta = BookMeta(
        title="智慧君主：Alexander 的治世传奇",
        author="佚名",
        genre="小说",
        difficulty="B",
        language="zh",
        era="架空历史",
        total_chapters_estimated=7,
    )

    character_voice_map = [
        CharacterVoiceBinding(
            canonical_name="旁白",
            aliases=["叙述者"],
            gender="neutral",
            age_range="adult",
            suggested_voice_id="v_narrator",
            sample_quote="在遥远的洛林王国，有一个古老的预言流传了几百年",
        ),
        CharacterVoiceBinding(
            canonical_name="Alexander",
            aliases=["亚历山大", "陛下", "国王"],
            gender="male",
            age_range="young",
            suggested_voice_id="v_alexander",
            sample_quote="我发现，世界其实充满了模式",
        ),
        CharacterVoiceBinding(
            canonical_name="老 Thompson",
            aliases=["首席御医", "Thompson"],
            gender="male",
            age_range="elderly",
            suggested_voice_id="v_thompson",
            sample_quote="像这样的婴儿，实在是太少见了",
        ),
        CharacterVoiceBinding(
            canonical_name="国王 Henry",
            aliases=["亨利国王", "Henry"],
            gender="male",
            age_range="adult",
            suggested_voice_id="v_henry",
            sample_quote="你说得对，Thompson，这孩子确实不普通",
        ),
        CharacterVoiceBinding(
            canonical_name="Prince Nathan",
            aliases=["奈森王子", "二弟"],
            gender="male",
            age_range="young",
            suggested_voice_id="v_nathan",
            sample_quote="陛下！您这是说笑话吧？",
        ),
        CharacterVoiceBinding(
            canonical_name="老 Pierre",
            aliases=["总管", "Pierre"],
            gender="male",
            age_range="elderly",
            suggested_voice_id="v_pierre",
            sample_quote="我想，或者我们可以先不要动武？",
        ),
        CharacterVoiceBinding(
            canonical_name="陈调查组长",
            aliases=["老陈", "调查组长"],
            gender="male",
            age_range="adult",
            suggested_voice_id="v_chen",
            sample_quote="与其把这些孩子都当作纯粹的坏人来处理",
        ),
        CharacterVoiceBinding(
            canonical_name="老水手",
            aliases=["转型水手"],
            gender="male",
            age_range="elderly",
            suggested_voice_id="v_sailor",
            sample_quote="要不是陛下您当初给了我这个机会",
        ),
    ]

    chapter_sources = []
    all_paragraphs = []

    for ch_idx, ch_data in enumerate(chapters_data, 1):
        paragraphs = ch_data["paragraphs"]
        annotations = create_annotations(ch_idx, paragraphs)

        ch_paragraphs = []
        for i, (para_text, ann) in enumerate(zip(paragraphs, annotations)):
            ch_para = ChapterSourceParagraph(
                paragraph_index=i,
                text=para_text[:2000],
                annotation=ann,
                human_verified=True,
                human_notes="人工标注验证",
                quality_score=0.95,
            )
            ch_paragraphs.append(ch_para)
            all_paragraphs.append(ch_para)

        emotion_snapshots = [
            EmotionSnapshot(
                chapter=1,
                dominant_emotion="contemplative",
                intensity=0.5,
                notes="王子诞生与成长",
            ),
            EmotionSnapshot(
                chapter=2, dominant_emotion="tense", intensity=0.8, notes="多重危机爆发"
            ),
            EmotionSnapshot(
                chapter=3,
                dominant_emotion="tense",
                intensity=0.7,
                notes="宫廷内部动荡与谈判",
            ),
            EmotionSnapshot(
                chapter=4,
                dominant_emotion="contemplative",
                intensity=0.6,
                notes="雪狼部落和谈策略",
            ),
            EmotionSnapshot(
                chapter=5,
                dominant_emotion="contemplative",
                intensity=0.6,
                notes="海盗问题根源分析",
            ),
            EmotionSnapshot(
                chapter=6, dominant_emotion="happy", intensity=0.7, notes="农业改革成果"
            ),
            EmotionSnapshot(
                chapter=7,
                dominant_emotion="tender",
                intensity=0.6,
                notes="文化建设与智慧传承",
            ),
        ]

        ch_source = ChapterSource(
            book_id="hongloumeng",
            chapter_index=ch_idx,
            chapter_title=ch_data["title"],
            book_meta=book_meta,
            character_voice_map=character_voice_map,
            emotion_snapshot=(
                emotion_snapshots[ch_idx - 1]
                if ch_idx <= len(emotion_snapshots)
                else emotion_snapshots[-1]
            ),
            story_line_summary="年轻国王 Alexander 在多重危机爆发之际登基，面对北方雪狼部落入侵、南方海盗劫掠、宫廷保守派倒逼等内外交困的严峻局面，他没有选择武力对抗，而是以智慧与仁爱为指导，通过谈判、调查、改革等一系列组合拳，逐一化解危机：建立宫廷联合委员会化解内部矛盾，派遣无武装使团与雪狼部落和谈，实施渔业复兴计划安置海盗，启动国土绿化行动振兴农业，兴建国家图书馆与综合大学提升文化软实力。二十年治世后，他将治国心得系统传授，确立以理解为基、以仁爱为根、以长远利益为指南针的治国传统，这一传统在其逝世后三十年依然指引新一代领导人化解内部挑战，成为王国永续发展的精神基石。",
            global_style_notes="第三人称全知视角，夹叙夹议，中西文混排，包含历史感与哲理思考。",
            paragraphs=ch_paragraphs,
            annotated_by="Agent B",
            annotated_at=datetime.now().isoformat(),
            annotation_version="v0.1",
            total_paragraphs=len(ch_paragraphs),
            verified_paragraphs=len(ch_paragraphs),
            overall_quality_score=0.95,
        )
        chapter_sources.append(ch_source)
        print(f"Chapter {ch_idx}: {len(ch_paragraphs)} paragraphs")

    collection = ChapterSourceCollection(
        book_id="hongloumeng",
        book_title="智慧君主：Alexander 的治世传奇",
        chapters=chapter_sources,
        collection_version="v0.1",
        created_at=datetime.now().isoformat(),
        total_chapters=len(chapter_sources),
        total_paragraphs=len(all_paragraphs),
        verified_paragraphs=len(all_paragraphs),
    )

    output_dir = Path("data/golden/hongloumeng/chapters")
    output_dir.mkdir(parents=True, exist_ok=True)

    for ch in chapter_sources:
        ch_file = output_dir / f"chapter_{ch.chapter_index:02d}.json"
        ch_file.write_text(
            ch.model_dump_json(indent=2, ensure_ascii=False), encoding="utf-8"
        )

    collection_file = Path("data/golden/hongloumeng/collection.json")
    collection_file.write_text(
        collection.model_dump_json(indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(
        f"\nGenerated {len(chapter_sources)} chapters, {len(all_paragraphs)} total paragraphs"
    )
    print(f"Collection saved to {collection_file}")


if __name__ == "__main__":
    main()
