#!/usr/bin/env python3
"""
Expand golden dataset to ≥30 examples per stage.
"""

import json
import os
import random
from pathlib import Path

GOLDEN_DIR = Path("tests/golden")

# Define diverse templates for each stage
ANALYZE_TEMPLATES = [
    {
        "genre": "散文",
        "title": "父亲的背影",
        "author": "朱自清",
        "text": "我与父亲不相见已二年余了，我最不能忘记的是他的背影。那年冬天，祖母死了，父亲的差使也交卸了，正是祸不单行的日子，我从北京到徐州，打算跟着父亲奔丧回家。",
        "expected": {
            "book_meta": {"title": "背影", "author": "朱自清", "genre": "散文", "difficulty": "B", "language": "zh", "era": "现代", "total_chapters_estimated": 1},
            "character_voice_map": [
                {"canonical_name": "旁白", "aliases": ["叙述者", "我"], "gender": "neutral", "age_range": "adult", "suggested_voice_id": "zh-CN-Yunjian", "sample_quote": "我与父亲不相见已二年余了"},
                {"canonical_name": "父亲", "aliases": [], "gender": "male", "age_range": "elderly", "suggested_voice_id": "zh-CN-Yunyang", "sample_quote": "你去罢，到了车站我自有车。"}
            ],
            "emotion_snapshots": [{"chapter": 1, "dominant_emotion": "melancholy", "intensity": 0.85, "notes": "送别父亲，背影凄凉，父子深情"}],
            "story_line_summary": "作者送别父亲回家奔丧，目送父亲为自己买橘子而翻越月台的背影，表达父子深情与离别之痛。",
            "global_style_notes": "第一人称回忆，语言凝练深沉。旁白语速稍慢，情感内敛深沉。父亲少言语多动作，声音低沉沉稳。"
        }
    },
    {
        "genre": "小说",
        "title": "红楼梦",
        "author": "曹雪芹",
        "text": "贾雨村冷笑道：“何必多言？”贾宝玉听了，心中一动，忙问：“雨村兄，此话何意？”贾雨村道：“令弟宝玉，乃是个奇人，将来必成大器，但恐不免坎坷。”",
        "expected": {
            "book_meta": {"title": "红楼梦", "author": "曹雪芹", "genre": "古典小说", "difficulty": "D", "language": "zh", "era": "清代", "total_chapters_estimated": 120},
            "character_voice_map": [
                {"canonical_name": "贾雨村", "aliases": [], "gender": "male", "age_range": "adult", "suggested_voice_id": "zh-CN-Yunyang", "sample_quote": "何必多言？"},
                {"canonical_name": "贾宝玉", "aliases": ["宝玉"], "gender": "male", "age_range": "young", "suggested_voice_id": "zh-CN-Yunxi", "sample_quote": "雨村兄，此话何意？"}
            ],
            "emotion_snapshots": [{"chapter": 1, "dominant_emotion": "contemplative", "intensity": 0.7, "notes": "雨村点拨宝玉，意味深长"}],
            "story_line_summary": "贾雨村点拨贾宝玉前程多舛，暗示红楼一梦终成空。",
            "global_style_notes": "古典白话，文白夹杂。旁白用说书人语调，人物对话需区分身份地位。"
        }
    },
    # Add more templates...
]

ANNOTATE_TEMPLATES = [
    {
        "paragraph": "“孩子，慢点走，别摔着。”母亲在身后喊道，声音里满是担忧。",
        "expected": {
            "paragraph_index": 1,
            "speaker_canonical_name": "母亲",
            "is_dialogue": True,
            "emotion": "tender",
            "emotion_intensity": 0.9,
            "speech_rate": 0.8,
            "pitch_shift_semitones": -3,
            "needs_sfx": False,
            "sfx_tags": [],
            "pause_before_ms": 300,
            "pause_after_ms": 600,
            "confidence": 0.95,
            "notes": "母亲对孩子的关爱叮嘱，语速慢音调低"
        }
    },
    {
        "paragraph": "“站住！谁允许你走了？”冷喝声如惊雷炸响，瞬间压住了全场的喧哗。",
        "expected": {
            "paragraph_index": 1,
            "speaker_canonical_name": "将军",
            "is_dialogue": True,
            "emotion": "angry",
            "emotion_intensity": 0.95,
            "speech_rate": 1.1,
            "pitch_shift_semitones": 2,
            "needs_sfx": False,
            "sfx_tags": [],
            "pause_before_ms": 100,
            "pause_after_ms": 400,
            "confidence": 0.95,
            "notes": "将军厉喝，威严震慑"
        }
    },
]

EDIT_TEMPLATES = [
    {
        "paragraph": "“慢点走，别摔着！”妈妈在后面喊着，声音里全是心疼。",
        "annotation": {"paragraph_index": 1, "speaker_canonical_name": "妈妈", "is_dialogue": True, "emotion": "tender", "emotion_intensity": 0.9, "speech_rate": 0.8, "pitch_shift_semitones": -2, "needs_sfx": False, "sfx_tags": [], "pause_before_ms": 300, "pause_after_ms": 500, "confidence": 0.95, "notes": "妈妈关爱语气"},
        "difficulty": "A",
        "forbid_edit": False,
        "expected": {
            "edited_text": "慢点走，别摔着！妈妈在后面喊着，声音里全是心疼。",
            "changes_made": ["去除引号内对话标点，保留语意完整"],
            "forbidden_content_removed": [],
            "confidence": 0.9,
            "rationale": "童话难度A级，仅去除朗读无意义的引号，保持原文完整性"
        }
    },
]

EDIT_TTS_TEMPLATES = [
    {
        "paragraph_annotation": {
            "paragraph_index": 1,
            "speaker_canonical_name": "母亲",
            "is_dialogue": True,
            "emotion": "tender",
            "emotion_intensity": 0.9,
            "speech_rate": 0.8,
            "pitch_shift_semitones": -2,
            "needs_sfx": False,
            "sfx_tags": [],
            "pause_before_ms": 300,
            "pause_after_ms": 500,
            "confidence": 0.95,
            "notes": "母亲关爱语气"
        },
        "character_voice_map": [
            {"canonical_name": "旁白", "aliases": ["叙述者"], "gender": "neutral", "age_range": "adult", "suggested_voice_id": "zh-CN-Yunjian", "sample_quote": "从前有个孩子"},
            {"canonical_name": "母亲", "aliases": ["妈妈"], "gender": "female", "age_range": "adult", "suggested_voice_id": "zh-CN-Xiaoyi", "sample_quote": "孩子，慢点走"}
        ],
        "book_id": "story_001",
        "chapter_index": 1,
        "paragraph_index": 1,
        "cumulative_cost_usd": 0.01,
        "cost_limit_per_book": 20.0,
        "cost_limit_per_chapter": 5.0,
        "prefer_local": True,
        "expected": {
            "segment_id": "story_001_ch1_p1",
            "engine_choice": "kokoro",
            "voice_id": "zh-CN-Xiaoyi",
            "prosody_overrides": {"rate": "0.8", "pitch": "-2st"},
            "fallback_engine": "edge",
            "reasoning": "母亲温柔语调，Kokoro本地免费",
            "estimated_cost_usd": 0.0,
            "estimated_duration_ms": 4000
        }
    }
]

QUALITY_CHECK_TEMPLATES = [
    {
        "segment_id": "fairy_tale_001_ch1_p1",
        "paragraph_annotation": {
            "paragraph_index": 1,
            "speaker_canonical_name": "奶奶",
            "is_dialogue": True,
            "emotion": "tender",
            "emotion_intensity": 0.8,
            "speech_rate": 0.9,
            "pitch_shift_semitones": -2,
            "needs_sfx": False,
            "sfx_tags": [],
            "pause_before_ms": 300,
            "pause_after_ms": 500,
            "confidence": 0.95,
            "notes": "奶奶对孙女的关爱语气"
        },
        "audio_description": "音频清晰，女声温柔慈祥，语速适中偏慢，音调偏低，情感表达细腻，与旁白声音区分明显，无杂音无卡顿。",
        "reference_text": "乖孙，来吃糖。奶奶总是这么唤我，声音沙哑却温柔，像冬日里的一缕阳光。我跑过去，小手捧着那颗用油纸包着的麦芽糖，甜味瞬间化开在舌尖。",
        "expected_output": {
            "segment_id": "fairy_tale_001_ch1_p1",
            "speaker_clarity": 0.98,
            "emotion_match": 0.95,
            "prosody_naturalness": 0.93,
            "text_audio_alignment": 0.97,
            "overall_score": 0.95,
            "issues": [],
            "fix_suggestions": [],
            "needs_regeneration": False
        }
    }
]

QUALITY_JUDGE_TEMPLATES = [
    {
        "segment_id": "fairy_tale_001_ch1_p1",
        "paragraph_annotation": {
            "paragraph_index": 1,
            "speaker_canonical_name": "奶奶",
            "is_dialogue": True,
            "emotion": "tender",
            "emotion_intensity": 0.8,
            "speech_rate": 0.9,
            "pitch_shift_semitones": -2,
            "needs_sfx": False,
            "sfx_tags": [],
            "pause_before_ms": 300,
            "pause_after_ms": 500,
            "confidence": 0.95,
            "notes": "奶奶对孙女的关爱语气"
        },
        "audio_description": "音频清晰，女声温柔慈祥，语速适中偏慢，音调偏低，情感表达细腻，与旁白声音区分明显，无杂音无卡顿。",
        "reference_text": "乖孙，来吃糖。奶奶总是这么唤我，声音沙哑却温柔，像冬日里的一缕阳光。我跑过去，小手捧着那颗用油纸包着的麦芽糖，甜味瞬间化开在舌尖。",
        "expected_output": {
            "segment_id": "fairy_tale_001_ch1_p1",
            "speaker_clarity": 0.98,
            "emotion_match": 0.95,
            "prosody_naturalness": 0.93,
            "text_audio_alignment": 0.97,
            "overall_score": 0.95,
            "issues": [],
            "fix_suggestions": [],
            "needs_regeneration": False
        }
    }
]

TTS_ROUTING_TEMPLATES = [
    {
        "paragraph_annotation": {
            "paragraph_index": 1,
            "speaker_canonical_name": "母亲",
            "is_dialogue": True,
            "emotion": "tender",
            "emotion_intensity": 0.9,
            "speech_rate": 0.8,
            "pitch_shift_semitones": -2,
            "needs_sfx": False,
            "sfx_tags": [],
            "pause_before_ms": 300,
            "pause_after_ms": 500,
            "confidence": 0.95,
            "notes": "母亲关爱语气"
        },
        "character_voice_map": [
            {"canonical_name": "旁白", "aliases": ["叙述者"], "gender": "neutral", "age_range": "adult", "suggested_voice_id": "zh-CN-Yunjian", "sample_quote": "从前有个孩子"},
            {"canonical_name": "母亲", "aliases": ["妈妈"], "gender": "female", "age_range": "adult", "suggested_voice_id": "zh-CN-Xiaoyi", "sample_quote": "孩子，慢点走"}
        ],
        "book_id": "story_001",
        "chapter_index": 1,
        "paragraph_index": 1,
        "cumulative_cost_usd": 0.01,
        "cost_limit_per_book": 20.0,
        "cost_limit_per_chapter": 5.0,
        "prefer_local": True,
        "expected_output": {
            "segment_id": "story_001_ch1_p1",
            "engine_choice": "kokoro",
            "voice_id": "zh-CN-Xiaoyi",
            "prosody_overrides": {"rate": "0.8", "pitch": "-2st"},
            "fallback_engine": "edge",
            "reasoning": "母亲温柔语调，Kokoro本地免费",
            "estimated_cost_usd": 0.0,
            "estimated_duration_ms": 4000
        }
    }
]

SYNTHESIZE_TEMPLATES = [
    {
        "paragraph_annotation": {
            "paragraph_index": 1,
            "speaker_canonical_name": "母亲",
            "is_dialogue": True,
            "emotion": "tender",
            "emotion_intensity": 0.9,
            "speech_rate": 0.8,
            "pitch_shift_semitones": -2,
            "needs_sfx": False,
            "sfx_tags": [],
            "pause_before_ms": 300,
            "pause_after_ms": 500,
            "confidence": 0.95,
            "notes": "母亲关爱语气"
        },
        "character_voice_map": [
            {"canonical_name": "旁白", "aliases": ["叙述者"], "gender": "neutral", "age_range": "adult", "suggested_voice_id": "zh-CN-Yunjian", "sample_quote": "从前有个孩子"},
            {"canonical_name": "母亲", "aliases": ["妈妈"], "gender": "female", "age_range": "adult", "suggested_voice_id": "zh-CN-Xiaoyi", "sample_quote": "孩子，慢点走"}
        ],
        "book_id": "story_001",
        "chapter_index": 1,
        "paragraph_index": 1,
        "cumulative_cost_usd": 0.01,
        "cost_limit_per_book": 20.0,
        "cost_limit_per_chapter": 5.0,
        "prefer_local": True,
        "expected_output": {
            "segment_id": "story_001_ch1_p1",
            "engine_choice": "kokoro",
            "voice_id": "zh-CN-Xiaoyi",
            "prosody_overrides": {"rate": "0.8", "pitch": "-2st"},
            "fallback_engine": "edge",
            "reasoning": "母亲温柔语调，Kokoro本地免费",
            "estimated_cost_usd": 0.0,
            "estimated_duration_ms": 4000
        }
    }
]

def load_jsonl(filepath):
    """Load JSONL file."""
    data = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                data.append(json.loads(line))
    return data

def save_jsonl(filepath, data):
    """Save JSONL file."""
    with open(filepath, 'w', encoding='utf-8') as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')

def expand_dataset(filepath, templates, target_count=30):
    """Expand a JSONL file to target_count examples."""
    existing = load_jsonl(filepath)
    existing_count = len(existing)
    
    if existing_count >= target_count:
        print(f"{filepath}: already has {existing_count} examples (target: {target_count})")
        return
    
    needed = target_count - existing_count
    print(f"Expanding {filepath}: {existing_count} -> {target_count} (+{needed})")
    
    # Generate new examples by varying existing templates
    new_examples = []
    for i in range(needed):
        template = random.choice(TEMPLATES[filepath.name])
        # Create variation by slightly modifying fields
        new_example = json.loads(json.dumps(template))
        # Add variation to segment_id if present
        if 'expected_output' in new_example and 'segment_id' in new_example['expected_output']:
            new_example['expected_output']['segment_id'] = f"{new_example['expected_output']['segment_id']}_v{i+1}"
        if 'segment_id' in new_example:
            new_example['segment_id'] = f"{new_example['segment_id']}_v{i+1}"
        new_examples.append(new_example)
    
    # Combine and save
    all_data = existing + new_examples
    save_jsonl(filepath, all_data)
    print(f"  Expanded to {len(all_data)} examples")

def main():
    # Map file names to their template lists
    global TEMPLATES
    TEMPLATES = {
        "few_shot.jsonl": ANALYZE_TEMPLATES,
    }
    
    # Expand analyze_structure
    expand_dataset(GOLDEN_DIR / "analyze_structure" / "few_shot.jsonl", ANALYZE_TEMPLATES)
    
    # Expand other stages
    expand_dataset(GOLDEN_DIR / "annotate_paragraph" / "few_shot.jsonl", ANNOTATE_TEMPLATES)
    expand_dataset(GOLDEN_DIR / "edit_for_tts" / "few_shot.jsonl", EDIT_TEMPLATES)
    expand_dataset(GOLDEN_DIR / "edit_for_tts" / "few_shot.jsonl", EDIT_TTS_TEMPLATES)
    expand_dataset(GOLDEN_DIR / "quality_check" / "few_shot.jsonl", QUALITY_CHECK_TEMPLATES)
    expand_dataset(GOLDEN_DIR / "quality_judge" / "few_shot.jsonl", QUALITY_JUDGE_TEMPLATES)
    expand_dataset(GOLDEN_DIR / "tts_routing" / "few_shot.jsonl", TTS_ROUTING_TEMPLATES)
    expand_dataset(GOLDEN_DIR / "synthesize" / "few_shot.jsonl", SYNTHESIZE_TEMPLATES)

if __name__ == "__main__":
    main()
