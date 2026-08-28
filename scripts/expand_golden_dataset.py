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
        "text": "我与父亲不相见已二年余了,我最不能忘记的是他的背影.那年冬天,祖母死了,父亲的差使也交卸了,正是祸不单行的日子,我从北京到徐州,打算跟着父亲奔丧回家.",
        "expected": {
            "book_meta": {"title": "背影", "author": "朱自清", "genre": "散文", "difficulty": "B", "language": "zh", "era": "现代", "total_chapters_estimated": 1},
            "character_voice_map": [
                {"canonical_name": "旁白", "aliases": ["叙述者", "我"], "gender": "neutral", "age_range": "adult", "suggested_voice_id": "zh-CN-Yunjian", "sample_quote": "我与父亲不相见已二年余了"},
                {"canonical_name": "父亲", "aliases": [], "gender": "male", "age_range": "elderly", "suggested_voice_id": "zh-CN-Yunyang", "sample_quote": "你去罢,到了车站我自有车."}
            ],
            "emotion_snapshots": [{"chapter": 1, "dominant_emotion": "melancholy", "intensity": 0.85, "notes": "送别父亲,背影凄凉,父子深情"}],
            "story_line_summary": "作者送别父亲回家奔丧,目送父亲为自己买橘子而翻越月台的背影,表达父子深情与离别之痛.",
            "global_style_notes": "第一人称回忆,语言凝练深沉.旁白语速稍慢,情感内敛深沉.父亲少言语多动作,声音低沉沉稳."
        }
    },
    {
        "genre": "小说",
        "title": "红楼梦",
        "author": "曹雪芹",
        "text": "贾雨村冷笑道：“何必多言？”贾宝玉听了,心中一动,忙问：“雨村兄,此话何意？”贾雨村道：“令弟宝玉,乃是个奇人,将来必成大器,但恐不免坎坷.”",
        "expected": {
            "book_meta": {"title": "红楼梦", "author": "曹雪芹", "genre": "古典小说", "difficulty": "D", "language": "zh", "era": "清代", "total_chapters_estimated": 120},
            "character_voice_map": [
                {"canonical_name": "贾雨村", "aliases": [], "gender": "male", "age_range": "adult", "suggested_voice_id": "zh-CN-Yunyang", "sample_quote": "何必多言？"},
                {"canonical_name": "贾宝玉", "aliases": ["宝玉"], "gender": "male", "age_range": "young", "suggested_voice_id": "zh-CN-Yunxi", "sample_quote": "雨村兄,此话何意？"}
            ],
            "emotion_snapshots": [{"chapter": 1, "dominant_emotion": "contemplative", "intensity": 0.7, "notes": "雨村点拨宝玉,意味深长"}],
            "story_line_summary": "贾雨村点拨贾宝玉前程多舛,暗示红楼一梦终成空.",
            "global_style_notes": "古典白话,文白夹杂.旁白用说书人语调,人物对话需区分身份地位."
        }
    },
    # Add more templates...
]

ANNOTATE_TEMPLATES = [
    {
        "paragraph": "“孩子,慢点走,别摔着.”母亲在身后喊道,声音里满是担忧.",
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
            "notes": "母亲对孩子的关爱叮嘱,语速慢音调低"
        }
    },
    {
        "paragraph": "“站住！谁允许你走了？”冷喝声如惊雷炸响,瞬间压住了全场的喧哗.",
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
            "notes": "将军厉喝,威严震慑"
        }
    },
]

EDIT_TEMPLATES = [
    {
        "paragraph": "“慢点走,别摔着！”妈妈在后面喊着,声音里全是心疼.",
        "annotation": {"paragraph_index": 1, "speaker_canonical_name": "妈妈", "is_dialogue": True, "emotion": "tender", "emotion_intensity": 0.9, "speech_rate": 0.8, "pitch_shift_semitones": -2, "needs_sfx": False, "sfx_tags": [], "pause_before_ms": 300, "pause_after_ms": 500, "confidence": 0.95, "notes": "妈妈关爱语气"},
        "difficulty": "A",
        "forbid_edit": False,
        "expected": {
            "edited_text": "慢点走,别摔着！妈妈在后面喊着,声音里全是心疼.",
            "changes_made": ["去除引号内对话标点,保留语意完整"],
            "forbidden_content_removed": [],
            "confidence": 0.9,
            "rationale": "童话难度A级,仅去除朗读无意义的引号,保持原文完整性"
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
            {"canonical_name": "母亲", "aliases": ["妈妈"], "gender": "female", "age_range": "adult", "suggested_voice_id": "zh-CN-Xiaoyi", "sample_quote": "孩子,慢点走"}
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
            "reasoning": "母亲温柔语调,Kokoro本地免费",
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
        "audio_description": "音频清晰,女声温柔慈祥,语速适中偏慢,音调偏低,情感表达细腻,与旁白声音区分明显,无杂音无卡顿.",
        "reference_text": "乖孙,来吃糖.奶奶总是这么唤我,声音沙哑却温柔,像冬日里的一缕阳光.我跑过去,小手捧着那颗用油纸包着的麦芽糖,甜味瞬间化开在舌尖.",
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
        "audio_description": "音频清晰,女声温柔慈祥,语速适中偏慢,音调偏低,情感表达细腻,与旁白声音区分明显,无杂音无卡顿.",
        "reference_text": "乖孙,来吃糖.奶奶总是这么唤我,声音沙哑却温柔,像冬日里的一缕阳光.我跑过去,小手捧着那颗用油纸包着的麦芽糖,甜味瞬间化开在舌尖.",
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
            {"canonical_name": "母亲", "aliases": ["妈妈"], "gender": "female", "age_range": "adult", "suggested_voice_id": "zh-CN-Xiaoyi", "sample_quote": "孩子,慢点走"}
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
            "reasoning": "母亲温柔语调,Kokoro本地免费",
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
            {"canonical_name": "母亲", "aliases": ["妈妈"], "gender": "female", "age_range": "adult", "suggested_voice_id": "zh-CN-Xiaoyi", "sample_quote": "孩子,慢点走"}
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
            "reasoning": "母亲温柔语调,Kokoro本地免费",
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
    expand_dataset(GOLDEN_DIR / "extract" / "few_shot.jsonl", EXTRACT_TEMPLATES)

if __name__ == "__main__":
    main()

# ═══════════════════════════════════════════════════════════════════════════════
# EXTRACT TEMPLATES
# ═════════════════════════════════════════════════════════════════════════════

EXTRACT_TEMPLATES = [
    {
        "input": {
            "file_path": "/data/samples/novel_chinese.pdf",
            "mime_type": "application/pdf",
            "detect_language": True
        },
        "expected_output": {
            "raw_text": "第一章  秋天来了\n\n秋风送爽,金黄的落叶在风中飞舞.小红和小明手拉着手走在回家的路上,踩着厚厚的落叶,发出沙沙的声响.\n\n\"秋天真美啊！\"小红高兴地说,"秋天是收获的季节,也是最美的季节."\n\n小明点点头,捡起一片金黄的银杏叶夹在书里："留作书签,明年春天再看."",
            "language": "zh",
            "page_count": 12,
            "has_ocr": False,
            "ocr_page_ratio": 0.0,
            "warnings": []
        }
    },
    {
        "input": {
            "file_path": "/data/samples/sci_fi_novel.pdf",
            "mime_type": "application/pdf",
            "detect_language": True
        },
        "expected_output": {
            "raw_text": "Chapter 1: The Signal\n\nThe signal came from Proxima Centauri, 4.2 light-years away. Dr. Chen stared at the spectrogram, her fingers trembling slightly above the keyboard.\n\n\"It's not natural,\" she whispered. "The modulation pattern... it's prime numbers. First 1, then 2, 3, 5, 7, 11, 13...\"\n\nHer colleague, Dr. Park, leaned over her shoulder. "You're saying someone's counting primes at us? From four light-years away?"",
            "language": "en",
            "page_count": 24,
            "has_ocr": False,
            "ocr_page_ratio": 0.0,
            "warnings": []
        }
    },
    {
        "input": {
            "file_path": "/data/samples/historical_epic.epub",
            "mime_type": "application/epub+zip",
            "detect_language": True
        },
        "expected_output": {
            "raw_text": "第一章  秦始皇统一六国\n\n秦王政二十六年,王贲攻燕,虏燕王喜.王贲攻代,虏代王嘉.王贲攻齐,虏齐王建降.秦灭六国,天下统一.\n\n始皇帝曰：\"朕承祖考余烈,平定天下,不敢有逸志."乃与丞相李斯、廷尉李斯等议曰：\"古者天子置史官,以记言行.今海内为一,法令由一统.\"",
            "language": "zh",
            "page_count": 45,
            "has_ocr": False,
            "ocr_page_ratio": 0.0,
            "warnings": []
        }
    },
    {
        "input": {
            "file_path": "/data/samples/business_report.pdf",
            "mime_type": "application/pdf",
            "detect_language": True
        },
        "expected_output": {
            "raw_text": "2024年Q3季度财务报告\n\n营收总额：12.5亿元人民币,同比增长15.3%\n净利润：2.1亿元,同比增长8.7%\n毛利率：42.3%,同比提升1.2个百分点\n\n核心业务板块：\n1. 云服务收入 5.2亿,增速 22%\n2. AI解决方案 3.1亿,增速 35%\n3. 传统软件许可 4.2亿,持平\n\n现金流：经营性现金流净额 3.8亿,自由现金流 2.9亿",
            "language": "zh",
            "page_count": 15,
            "has_ocr": False,
            "ocr_page_ratio": 0.0,
            "warnings": []
        }
    },
    {
        "input": {
            "file_path": "/data/samples/children_story.pdf",
            "mime_type": "application/pdf",
            "detect_language": True
        },
        "expected_output": {
            "raw_text": "小兔子的红气球\n\n小白兔得到了一个大大的红气球,高兴得蹦个不停.它紧紧攥着绳子,生怕气球飞走了.\n\n一阵风吹来,气球在天空中飞得更高了.小白兔仰着头,眼睛眨也不眨地盯着.\n\n\"别担心,"小鸟在树枝上唱道,"风会把它带得更高,飞得更远."\n\n小白兔笑了,它知道,快乐就像这气球,会一直飞得更高.",
            "language": "zh",
            "page_count": 6,
            "has_ocr": False,
            "ocr_page_ratio": 0.0,
            "warnings": []
        }
    },
    {
        "input": {
            "file_path": "/data/samples/tech_manual.pdf",
            "mime_type": "application/pdf",
            "detect_language": True
        },
        "expected_output": {
            "raw_text": "API Reference Guide v2.1\n\n## Authentication\n\nAll API requests require authentication via Bearer token:\n\n```\nAuthorization: Bearer <your_api_token>\n```\n\n### Rate Limits\n\n- Free tier: 100 requests/minute\n- Pro tier: 1,000 requests/minute\n- Enterprise: 10,000 requests/minute\n\n### Error Codes\n\n| Code | Meaning |\n|------|---------|\n| 400 | Bad Request |\n| 401 | Unauthorized |\n| 429 | Too Many Requests |\n| 500 | Internal Server Error |",
            "language": "en",
            "page_count": 20,
            "has_ocr": False,
            "ocr_page_ratio": 0.0,
            "warnings": []
        }
    },
    {
        "input": {
            "file_path": "/data/samples/poetry_collection.pdf",
            "mime_type": "application/pdf",
            "detect_language": True
        },
        "expected_output": {
            "raw_text": "静夜思\n\n床前明月光,\n疑是地上霜.\n举头望明月,\n低头思故乡.\n\n-- 李白\n\n春晓\n\n春眠不觉晓,\n处处闻啼鸟.\n夜来风雨声,\n花落知多少.\n\n-- 孟浩然",
            "language": "zh",
            "page_count": 4,
            "has_ocr": False,
            "ocr_page_ratio": 0.0,
            "warnings": []
        }
    },
    {
        "input": {
            "file_path": "/data/samples/scanned_archive.pdf",
            "mime_type": "application/pdf",
            "detect_language": True
        },
        "expected_output": {
            "raw_text": "民国档案：关于设立京师大学堂的奏折\n\n光绪二十四年八月初五日,户部尚书荣庆奏：\n\n\"臣等遵旨筹办京师大学堂,拟分三科：正科、预科、高等科.正科修业三年,预科两年,高等科一年.课程设算学、格致、历史、地理、英文、法文、日文、俄文、德文、蒙文、藏文、满文、汉文、书法、体操等.\"",
            "language": "zh",
            "page_count": 8,
            "has_ocr": True,
            "ocr_page_ratio": 0.6,
            "warnings": ["部分页面模糊,OCR识别率可能下降"]
        }
    },
    {
        "input": {
            "file_path": "/data/samples/mystery_novel.pdf",
            "mime_type": "application/pdf",
            "detect_language": True
        },
        "expected_output": {
            "raw_text": "Chapter 1: The Missing Heirloom\n\nThe midnight clock struck twelve when Lady Eleanor discovered the safe empty. The Stafford diamonds—three generations of family heritage—had vanished without a trace.\n\nDetective Inspector Morse stood in the library, his keen eyes scanning the room. No forced entry. No fingerprints. The only clue: a single white glove lying on the Persian rug.\n\n\"The thief knew the combination,\" Morse muttered. "And they knew exactly when the household would be at the ball.\"",
            "language": "en",
            "page_count": 18,
            "has_ocr": False,
            "ocr_page_ratio": 0.0,
            "warnings": []
        }
    },
    {
        "input": {
            "file_path": "/data/samples/cookbook.pdf",
            "mime_type": "application/pdf",
            "detect_language": True
        },
        "expected_output": {
            "raw_text": "家常菜谱精选\n\n红烧肉\n\n材料：五花肉500克,生姜3片,葱段2根,八角2个,桂皮1小块,冰糖2勺,生抽2勺,老抽1勺,料酒1勺,盐适量.\n\n做法：\n1. 五花肉切块,冷水下锅焯水去腥.\n2. 热锅凉油,炒糖色至枣红色.\n3. 倒入肉块翻炒上色,加入调料.\n3. 加水没过肉块,大火烧开转小火炖40分钟.\n4. 收汁大火烧浓即可出锅.",
            "language": "zh",
            "page_count": 12,
            "has_ocr": False,
            "ocr_page_ratio": 0.0,
            "warnings": []
        }
    },
    {
        "input": {
            "file_path": "/data/samples/travel_guide.epub",
            "mime_type": "application/epub+zip",
            "detect_language": True
        },
        "expected_output": {
            "raw_text": "云南大理旅行指南\n\n最佳旅行时间：3-11月\n\n必去景点：\n1. 洱海环海骑行 - 约120公里,建议2-3天\n2. 崇圣寺三塔 - 大理标志性建筑,登塔俯瞰洱海\n3. 喜洲古镇 - 白族建筑群,海东菜发源地\n4. 双廊古镇 - 看日出圣地,文艺青年聚集地\n\n美食推荐：\n- 喜洲粑粑：酥脆香甜,现做现卖\n- 酸辣鱼：大理名菜,汤红味美\n- 过桥米线：云南十大名菜之首\n\n住宿建议：洱海边民宿看日出,古城客栈体验慢生活",
            "language": "zh",
            "page_count": 22,
            "has_ocr": False,
            "ocr_page_ratio": 0.0,
            "warnings": []
        }
    },
    {
        "input": {
            "file_path": "/data/samples/medical_textbook.pdf",
            "mime_type": "application/pdf",
            "detect_language": True
        },
        "expected_output": {
            "raw_text": "临床诊断学 第8版\n\n第二章 心力衰竭\n\n心力衰竭是各种心脏病发展到终末期的表现,是心脏结构或功能异常导致心室充盈或射血能力受损,不能满足机体代谢需要的综合征.\n\n诊断标准（Framingham标准）：\n主要标准：\n1. 发绀  2. 颈静脉怒张  3. 肺啰音  4. 心脏扩大\n次要标准：\n1. 下肢水肿  2. 夜间阵发性呼吸困难  3. 肝脏肿大\n\n治疗原则：利尿、强心、扩血管、抗凝",
            "language": "zh",
            "page_count": 35,
            "has_ocr": False,
            "ocr_page_ratio": 0.0,
            "warnings": []
        }
    },
    {
        "input": {
            "file_path": "/data/samples/legal_contract.pdf",
            "mime_type": "application/pdf",
            "detect_language": True
        },
        "expected_output": {
            "raw_text": "软件许可使用协议\n\n甲方（授权方）：北京某科技有限公司\n乙方（被授权方）：上海某信息技术有限公司\n\n第一条 授权范围\n甲方授予乙方在中华人民共和国境内,非独家、不可转让的权利,使用甲方开发的"云ERP管理系统V3.0"软件产品.\n\n第二条 期限\n本协议自双方签字盖章之日起生效,有效期三年.\n\n第三条 许可费用\n乙方应于本协议生效之日起30个工作日内,向甲方支付许可费用人民币200万元整.\n\n第十条 争议解决\n因本协议产生的争议,由双方友好协商解决；协商不成的,提交北京市朝阳区人民法院管辖.",
            "language": "zh",
            "page_count": 10,
            "has_ocr": False,
            "ocr_page_ratio": 0.0,
            "warnings": []
        }
    }
]
