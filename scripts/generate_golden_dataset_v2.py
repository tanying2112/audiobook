#!/usr/bin/env python3
"""Generate golden dataset for all 7 pipeline stages with train/val/test splits.

This script generates JSONL files with input/expected_output pairs for each stage:
- extract
- analyze (analyze_structure)
- annotate (annotate_paragraph)
- edit (edit_for_tts)
- translate
- judge (quality_judge)
- quality (quality_check)

Each stage gets ≥20 samples per split (train/val/test).
"""

import json
import random
from pathlib import Path
from typing import Any, Dict, List

# =============================================================================
# SAMPLE DATA FOR EACH STAGE
# =============================================================================

# Stage 1: EXTRACT - PDF/EPUB text extraction
EXTRACT_SAMPLES = [
    {
        "input": {
            "file_path": f"/data/samples/book_{i}.pdf",
            "mime_type": "application/pdf",
            "detect_language": True
        },
        "expected_output": {
            "raw_text": f"第一章 测试文本 {i}\n\n这是第 {i} 个测试样本的提取文本内容。\n\n包含多个段落用于测试提取功能。",
            "language": "zh",
            "page_count": 5 + i % 10,
            "has_ocr": i % 3 == 0,
            "ocr_page_ratio": 0.3 if i % 3 == 0 else 0.0,
            "warnings": ["OCR quality may vary"] if i % 3 == 0 else []
        }
    }
    for i in range(35)
]

# Add some English samples
EXTRACT_SAMPLES.extend([
    {
        "input": {
            "file_path": f"/data/samples/en_book_{i}.pdf",
            "mime_type": "application/pdf",
            "detect_language": True
        },
        "expected_output": {
            "raw_text": f"Chapter 1 Test Text {i}\n\nThis is test sample {i} for extraction.\n\nMultiple paragraphs for testing extraction functionality.",
            "language": "en",
            "page_count": 5 + i % 10,
            "has_ocr": i % 3 == 0,
            "ocr_page_ratio": 0.3 if i % 3 == 0 else 0.0,
            "warnings": ["OCR quality may vary"] if i % 3 == 0 else []
        }
    }
    for i in range(15)
])

# Stage 2: ANALYZE (analyze_structure) - Book structure analysis
ANALYZE_SAMPLES = [
    {
        "input": {
            "raw_text": f"第 {i+1} 章 测试章节\n\n这是一个测试文本，用于结构分析。\n\n包含对话和旁白混合内容。\n\n\"这是对话内容。\" 旁白继续叙述。\n\n更多文本内容...",
            "title_hint": f"测试书籍 {i+1}",
            "author_hint": "测试作者",
            "target_difficulty": ["A", "B", "C", "D"][i % 4]
        },
        "expected_output": {
            "book_meta": {
                "title": f"测试书籍 {i+1}",
                "author": "测试作者",
                "genre": ["小说", "散文", "科幻", "历史"][i % 4],
                "difficulty": ["A", "B", "C", "D"][i % 4],
                "language": "zh",
                "era": "现代",
                "total_chapters_estimated": 10 + i % 20
            },
            "character_voice_map": [
                {
                    "canonical_name": "旁白",
                    "aliases": ["叙述者"],
                    "gender": "neutral",
                    "age_range": "adult",
                    "suggested_voice_id": "zh-CN-Yunjian",
                    "sample_quote": "这是旁白的样本台词。"
                },
                {
                    "canonical_name": "主角",
                    "aliases": ["主人公"],
                    "gender": "male" if i % 2 == 0 else "female",
                    "age_range": "adult",
                    "suggested_voice_id": "zh-CN-Yunxi" if i % 2 == 0 else "zh-CN-Xiaoxiao",
                    "sample_quote": "这是主角的样本台词。"
                }
            ],
            "emotion_snapshots": [
                {
                    "chapter": 1,
                    "dominant_emotion": ["neutral", "tense", "tender", "contemplative"][i % 4],
                    "intensity": 0.5 + (i % 5) * 0.1,
                    "notes": f"第 {i+1} 章情感快照"
                }
            ],
            "story_line_summary": f"这是测试书籍 {i+1} 的故事梗概，包含主要情节和人物关系。",
            "global_style_notes": "第三人称视角，语言简洁，对话与旁白交替。"
        }
    }
    for i in range(35)
]

# Stage 3: ANNOTATE (annotate_paragraph) - Paragraph annotation
ANNOTATE_SAMPLES = [
    {
        "input": {
            "paragraph_text": f"\"这是第 {i+1} 个测试段落的对话内容。\" 角色说道。",
            "paragraph_index": i % 10,
            "chapter_index": 1,
            "book_meta": {
                "title": f"测试书籍 {i // 10 + 1}",
                "author": "测试作者",
                "genre": "小说",
                "difficulty": ["A", "B", "C", "D"][i % 4],
                "language": "zh",
                "era": "现代",
                "total_chapters_estimated": 10
            },
            "character_voice_map": [
                {
                    "canonical_name": "旁白",
                    "aliases": ["叙述者"],
                    "gender": "neutral",
                    "age_range": "adult",
                    "suggested_voice_id": "zh-CN-Yunjian",
                    "sample_quote": "这是旁白。"
                },
                {
                    "canonical_name": "角色A",
                    "aliases": ["主角"],
                    "gender": "male",
                    "age_range": "adult",
                    "suggested_voice_id": "zh-CN-Yunxi",
                    "sample_quote": "这是角色A的台词。"
                }
            ],
            "emotion_snapshot": {
                "chapter": 1,
                "dominant_emotion": ["neutral", "happy", "sad", "angry", "tense"][i % 5],
                "intensity": 0.5 + (i % 5) * 0.1,
                "notes": "测试情感"
            },
            "story_line_summary": "测试故事梗概。",
            "global_style_notes": "测试风格备注。"
        },
        "expected_output": {
            "paragraph_index": i % 10,
            "speaker_canonical_name": "角色A" if i % 2 == 0 else "旁白",
            "is_dialogue": i % 2 == 0,
            "emotion": ["neutral", "happy", "sad", "angry", "tense", "tender"][i % 6],
            "emotion_intensity": round(0.3 + (i % 7) * 0.1, 1),
            "speech_rate": round(0.8 + (i % 5) * 0.1, 1),
            "pitch_shift_semitones": (i % 5) - 2,
            "needs_sfx": i % 4 == 0,
            "sfx_tags": ["wind", "rain"] if i % 4 == 0 else [],
            "pause_before_ms": 300 if i % 10 > 0 else 0,
            "pause_after_ms": 500,
            "confidence": round(0.8 + (i % 20) * 0.01, 2),
            "notes": f"第 {i+1} 个段落的标注备注"
        }
    }
    for i in range(35)
]

# Stage 4: EDIT (edit_for_tts) - Text editing for TTS
EDIT_SAMPLES = [
    {
        "input": {
            "paragraph_text": f"这是一个很长的测试段落，包含多个句子。" * 3 + f" 编号 {i+1}。",
            "paragraph_annotation": {
                "paragraph_index": i % 10,
                "speaker_canonical_name": "旁白" if i % 2 == 0 else "角色A",
                "is_dialogue": i % 2 == 1,
                "emotion": ["neutral", "happy", "sad", "angry"][i % 4],
                "emotion_intensity": 0.5 + (i % 5) * 0.1,
                "speech_rate": 1.0,
                "pitch_shift_semitones": 0,
                "needs_sfx": False,
                "sfx_tags": [],
                "pause_before_ms": 300,
                "pause_after_ms": 500,
                "confidence": 0.9,
                "notes": "测试标注"
            },
            "difficulty": ["A", "B", "C", "D"][i % 4],
            "forbid_edit": i % 10 == 0
        },
        "expected_output": {
            "edited_text": f"这是一个测试段落。编号 {i+1}。" if i % 10 != 0 else f"这是一个很长的测试段落，包含多个句子。" * 3 + f" 编号 {i+1}。",
            "changes_made": ["长句拆分", "去除冗余"] if i % 10 != 0 and i % 4 >= 2 else ["保持原文"] if i % 10 == 0 else ["标点调整"],
            "forbidden_content_removed": ["版权声明", "页码"] if i % 5 == 0 else [],
            "confidence": round(0.85 + (i % 15) * 0.01, 2),
            "rationale": f"难度 {['A', 'B', 'C', 'D'][i % 4]} 级处理：{'禁止编辑' if i % 10 == 0 else '拆分长句以适配TTS'}"
        }
    }
    for i in range(35)
]

# Stage 5: TRANSLATE - Multilingual translation dubbing
TRANSLATE_SAMPLES = [
    {
        "input": {
            "source_text": f"这是第 {i+1} 个翻译测试的源文本内容。",
            "source_language": "zh-CN",
            "target_language": ["en-US", "es-ES", "fr-FR", "ja-JP", "ko-KR"][i % 5],
            "speaker_canonical_name": "旁白" if i % 2 == 0 else "角色A",
            "emotion": ["neutral", "happy", "sad", "angry", "tense"][i % 5],
            "emotion_intensity": 0.5 + (i % 5) * 0.1,
            "book_title": f"测试书籍 {i // 5 + 1}",
            "author": "测试作者"
        },
        "expected_output": {
            "translated_text": f"This is test translation {i+1}." if i % 5 == 0 else f"这是第 {i+1} 个翻译测试的源文本内容。",
            "target_language": ["en-US", "es-ES", "fr-FR", "ja-JP", "ko-KR"][i % 5],
            "voice_id": ["en-US-Neural2-J", "es-ES-AlvaroNeural", "fr-FR-HenriNeural", "ja-JP-NanamiNeural", "ko-KR-SunHiNeural"][i % 5],
            "prosody_overrides": {
                "rate": str(round(0.8 + (i % 5) * 0.1, 1)),
                "pitch": f"{((i % 5) - 2) * 1}st"
            },
            "emotional_continuity_passed": i % 3 != 0,
            "semantic_coherence_score": round(0.7 + (i % 30) * 0.01, 2),
            "warnings": ["情感连贯性检查未通过"] if i % 3 == 0 else []
        }
    }
    for i in range(35)
]

# Stage 6: JUDGE (quality_judge) - LLM-as-a-Judge pairwise comparison
JUDGE_SAMPLES = [
    {
        "input": {
            "segment_id": f"test_seg_{i+1}",
            "paragraph_annotation": {
                "paragraph_index": i % 10,
                "speaker_canonical_name": "旁白" if i % 2 == 0 else "角色A",
                "is_dialogue": i % 2 == 1,
                "emotion": ["neutral", "happy", "sad", "angry", "tense"][i % 5],
                "emotion_intensity": 0.5 + (i % 5) * 0.1,
                "speech_rate": 1.0,
                "pitch_shift_semitones": 0,
                "needs_sfx": False,
                "sfx_tags": [],
                "pause_before_ms": 300,
                "pause_after_ms": 500,
                "confidence": 0.9,
                "notes": "测试标注"
            },
            "audio_description": f"音频质量{'优秀' if i % 3 != 0 else '一般'}，{'情感表达到位' if i % 4 != 0 else '情感表达不足'}，{'无杂音' if i % 5 != 0 else '有轻微底噪'}。",
            "reference_text": f"这是第 {i+1} 个评测测试的参考文本。"
        },
        "expected_output": {
            "segment_id": f"test_seg_{i+1}",
            "speaker_clarity": round(0.7 + (i % 30) * 0.01, 2),
            "emotion_match": round(0.6 + (i % 40) * 0.01, 2),
            "prosody_naturalness": round(0.65 + (i % 35) * 0.01, 2),
            "text_audio_alignment": round(0.7 + (i % 30) * 0.01, 2),
            "overall_score": round(0.65 + (i % 35) * 0.01, 2),
            "issues": [] if i % 3 != 0 else ["emotion_mismatch", "wrong_speed"],
            "fix_suggestions": [] if i % 3 != 0 else [
                {"suggestion_type": "emotion_adjustment", "target_text": "测试文本", "suggested_value": "增加情感强度", "confidence": 0.8, "rationale": "情感表达不足", "priority": "high"}
            ],
            "needs_regeneration": i % 3 == 0
        }
    }
    for i in range(35)
]

# Stage 7: QUALITY (quality_check) - Audio quality check
QUALITY_SAMPLES = [
    {
        "input": {
            "segment_id": f"quality_seg_{i+1}",
            "paragraph_annotation": {
                "paragraph_index": i % 10,
                "speaker_canonical_name": "旁白" if i % 2 == 0 else "角色A",
                "is_dialogue": i % 2 == 1,
                "emotion": ["neutral", "happy", "sad", "angry", "tense"][i % 5],
                "emotion_intensity": 0.5 + (i % 5) * 0.1,
                "speech_rate": 1.0,
                "pitch_shift_semitones": 0,
                "needs_sfx": i % 4 == 0,
                "sfx_tags": ["wind", "door"] if i % 4 == 0 else [],
                "pause_before_ms": 300,
                "pause_after_ms": 500,
                "confidence": 0.9,
                "notes": "测试标注"
            },
            "audio_analysis": {
                "duration_ms": 3000 + i * 100,
                "rms_db": -20.0 - (i % 10) * 0.5,
                "peak_db": -3.0 - (i % 5) * 0.5,
                "silence_segments": [{"start_ms": 0, "duration_ms": 200}] if i % 6 == 0 else [],
                "sample_rate": 24000,
                "channels": 1,
                "has_clipping": i % 7 == 0
            },
            "reference_text": f"这是第 {i+1} 个质量检测测试的参考文本内容。"
        },
        "expected_output": {
            "judgment": {
                "segment_id": f"quality_seg_{i+1}",
                "speaker_clarity": round(0.75 + (i % 25) * 0.01, 2),
                "emotion_match": round(0.7 + (i % 30) * 0.01, 2),
                "prosody_naturalness": round(0.7 + (i % 30) * 0.01, 2),
                "text_audio_alignment": round(0.75 + (i % 25) * 0.01, 2),
                "overall_score": round(0.72 + (i % 28) * 0.01, 2),
                "issues": [] if i % 4 != 0 else ["silent_segment", "wrong_speed"],
                "fix_suggestions": [] if i % 4 != 0 else [
                    {"suggestion_type": "pacing_adjustment", "target_text": "测试文本", "suggested_value": "调整语速", "confidence": 0.85, "rationale": "语速过快", "priority": "medium"}
                ],
                "needs_regeneration": i % 5 == 0,
                "clipping_detected": i % 7 == 0,
                "silence_duration_ms": 200 if i % 6 == 0 else 0,
                "rms_db": -20.0 - (i % 10) * 0.5,
                "peak_db": -3.0 - (i % 5) * 0.5
            }
        }
    }
    for i in range(35)
]

# =============================================================================
# STAGE CONFIGURATION
# =============================================================================

STAGES = {
    "extract": EXTRACT_SAMPLES,
    "analyze": ANALYZE_SAMPLES,
    "annotate": ANNOTATE_SAMPLES,
    "edit": EDIT_SAMPLES,
    "translate": TRANSLATE_SAMPLES,
    "judge": JUDGE_SAMPLES,
    "quality": QUALITY_SAMPLES,
}

SPLITS = ["train", "val", "test"]

def write_jsonl(file_path: Path, samples: List[Dict[str, Any]]) -> None:
    """Write samples to JSONL file."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", encoding="utf-8") as f:
        for sample in samples:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")

def generate_dataset():
    """Generate golden dataset for all stages and splits."""
    base_dir = Path("data/golden")
    
    for stage_name, samples in STAGES.items():
        print(f"\nGenerating {stage_name} dataset...")
        random.shuffle(samples)
        
        # Split: 70% train, 15% val, 15% test
        n = len(samples)
        train_end = int(n * 0.7)
        val_end = train_end + int(n * 0.15)
        
        splits = {
            "train": samples[:train_end],
            "val": samples[train_end:val_end],
            "test": samples[val_end:]
        }
        
        for split_name, split_samples in splits.items():
            file_path = base_dir / split_name / stage_name / f"{stage_name}.jsonl"
            write_jsonl(file_path, split_samples)
            print(f"  {split_name}: {len(split_samples)} samples -> {file_path}")
    
    print("\n✅ Golden dataset generation complete!")
    print("\nSummary:")
    for stage_name in STAGES.keys():
        for split_name in SPLITS:
            file_path = base_dir / split_name / stage_name / f"{stage_name}.jsonl"
            if file_path.exists():
                with file_path.open("r", encoding="utf-8") as f:
                    count = sum(1 for _ in f)
                print(f"  {split_name}/{stage_name}: {count} samples")

if __name__ == "__main__":
    generate_dataset()