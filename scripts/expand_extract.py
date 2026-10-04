#!/usr/bin/env python3
"""Expand extract golden dataset."""

import json
from pathlib import Path

EXTRACT_TEMPLATES = [
    {
        "input": {
            "file_path": "/data/samples/novel_chinese.pdf",
            "mime_type": "application/pdf",
            "detect_language": True
        },
        "expected_output": {
            "raw_text": "第一章  秋天来了\n\n秋风送爽，金黄的落叶在风中飞舞。小红和小明手拉着手走在回家的路上，踩着厚厚的落叶，发出沙沙的声响。\n\n\"秋天真美啊！\"小红高兴地说，\"秋天是收获的季节，也是最美的季节。\"\n\n小明点点头，捡起一片金黄的银杏叶夹在书里：\"留作书签，明年春天再看。\"",
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
            "raw_text": "Chapter 1: The Signal\n\nThe signal came from Proxima Centauri, 4.2 light-years away. Dr. Chen stared at the spectrogram, her fingers trembling slightly above the keyboard.\n\n\"It's not natural,\" she whispered. \"The modulation pattern... it's prime numbers. First 1, then 2, 3, 5, 7, 11, 13...\"\n\nHer colleague, Dr. Park, leaned over her shoulder. \"You're saying someone's counting primes at us? From four light-years away?\"",
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
            "raw_text": "第一章  秦始皇统一六国\n\n秦王政二十六年，王贲攻燕，虏燕王喜。王贲攻代，虏代王嘉。王贲攻齐，虏齐王建降。秦灭六国，天下统一。\n\n始皇帝曰：\"朕承祖考余烈，平定天下，不敢有逸志。\"乃与丞相李斯、廷尉李斯等议曰：\"古者天子置史官，以记言行。今海内为一，法令由一统。\"",
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
            "raw_text": "2024年Q3季度财务报告\n\n营收总额：12.5亿元人民币，同比增长15.3%\n净利润：2.1亿元，同比增长8.7%\n毛利率：42.3%，同比提升1.2个百分点\n\n核心业务板块：\n1. 云服务收入 5.2亿，增速 22%\n2. AI解决方案 3.1亿，增速 35%\n3. 传统软件许可 4.2亿，持平\n\n现金流：经营性现金流净额 3.8亿，自由现金流 2.9亿",
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
            "raw_text": "小兔子的红气球\n\n小白兔得到了一个大大的红气球，高兴得蹦个不停。它紧紧攥着绳子，生怕气球飞走了。\n\n一阵风吹来，气球在天空中飞得更高了。小白兔仰着头，眼睛眨也不眨地盯着。\n\n\"别担心，\"小鸟在树枝上唱道，\"风会把它带得更高，飞得更远。\"\n\n小白兔笑了，它知道，快乐就像这气球，会一直飞得更高。",
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
            "raw_text": "静夜思\n\n床前明月光，\n疑是地上霜。\n举头望明月，\n低头思故乡。\n\n-- 李白\n\n春晓\n\n春眠不觉晓，\n处处闻啼鸟。\n夜来风雨声，\n花落知多少。\n\n-- 孟浩然",
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
            "raw_text": "民国档案：关于设立京师大学堂的奏折\n\n光绪二十四年八月初五日，户部尚书荣庆奏：\n\n\"臣等遵旨筹办京师大学堂，拟分三科：正科、预科、高等科。正科修业三年，预科两年，高等科一年。课程设算学、格致、历史、地理、英文、法文、日文、俄文、德文、蒙文、藏文、满文、汉文、书法、体操等。\"",
            "language": "zh",
            "page_count": 8,
            "has_ocr": True,
            "ocr_page_ratio": 0.6,
            "warnings": ["部分页面模糊，OCR识别率可能下降"]
        }
    },
    {
        "input": {
            "file_path": "/data/samples/mystery_novel.pdf",
            "mime_type": "application/pdf",
            "detract_language": True
        },
        "expected_output": {
            "raw_text": "Chapter 1: The Missing Heirloom\n\nThe midnight clock struck twelve when Lady Eleanor discovered the safe empty. The Stafford diamonds—three generations of family heritage—had vanished without a trace.\n\nDetective Inspector Morse stood in the library, his keen eyes scanning the room. No forced entry. No fingerprints. The only clue: a single white glove lying on the Persian rug.\n\n\"The thief knew the combination,\" Morse muttered. \"And they knew exactly when the household would be at the ball.\"",
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
            "raw_text": "家常菜谱精选\n\n红烧肉\n\n材料：五花肉500克，生姜3片，葱段2根，八角2个，桂皮1小块，冰糖2勺，生抽2勺，老抽1勺，料酒1勺，盐适量。\n\n做法：\n1. 五花肉切块，冷水下锅焯水去腥。\n2. 热锅凉油，炒糖色至枣红色。\n3. 倒入肉块翻炒上色，加入调料。\n3. 加水没过肉块，大火烧开转小火炖40分钟。\n4. 收汁大火烧浓即可出锅。",
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
            "raw_text": "云南大理旅行指南\n\n最佳旅行时间：3-11月\n\n必去景点：\n1. 洱海环海骑行 - 约120公里，建议2-3天\n2. 崇圣寺三塔 - 大理标志性建筑，登塔俯瞰洱海\n3. 喜洲古镇 - 白族建筑群，海东菜发源地\n4. 双廊古镇 - 看日出圣地，文艺青年聚集地\n\n美食推荐：\n- 喜洲粑粑：酥脆香甜，现做现卖\n- 酸辣鱼：大理名菜，汤红味美\n- 过桥米线：云南十大名菜之首\n\n住宿建议：洱海边民宿看日出，古城客栈体验慢生活",
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
            "raw_text": "临床诊断学 第8版\n\n第二章 心力衰竭\n\n心力衰竭是各种心脏病发展到终末期的表现，是心脏结构或功能异常导致心室充盈或射血能力受损，不能满足机体代谢需要的综合征。\n\n诊断标准（Framingham标准）：\n主要标准：\n1. 发绀  2. 颈静脉怒张  3. 肺啰音  4. 心脏扩大\n次要标准：\n1. 下肢水肿  2. 夜间阵发性呼吸困难  3. 肝肿大\n\n治疗原则：利尿、强心、扩血管、抗凝",
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
            "raw_text": "软件许可使用协议\n\n甲方（授权方）：北京某科技有限公司\n乙方（被授权方）：上海某信息技术有限公司\n\n第一条 授权范围\n甲方授予乙方在中华人民共和国境内，非独家、不可转让的权利，使用甲方开发的\"云ERP管理系统V3.0\"软件产品。\n\n第二条 许可期限\n本协议自双方签字盖章之日起生效，有效期三年。\n\n第三条 许可费用\n乙方应于本协议生效之日起30个工作日内，向甲方支付许可费用人民币200万元整。\n\n第十条 争议解决\n因本协议产生的争议，由双方友好协商解决；协商不成的，提交北京市朝阳区人民法院管辖。",
            "language": "zh",
            "page_count": 10,
            "has_ocr": False,
            "ocr_page_ratio": 0.0,
            "warnings": []
        }
    }
]

def load_jsonl(filepath):
    data = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                data.append(json.loads(line))
    return data

def save_jsonl(filepath, data):
    with open(filepath, 'w', encoding='utf-8') as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')

def expand_extract():
    filepath = Path("tests/golden/extract/few_shot.jsonl")
    existing = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                existing.append(json.loads(line))
    
    existing_count = len(existing)
    target = 30
    
    if existing_count >= 30:
        print(f"Already has {existing_count} examples")
        return
    
    needed = 30 - existing_count
    print(f"Expanding extract: {existing_count} -> 30 (+{30-existing_count})")
    
    # Create variations by modifying existing examples
    new_examples = []
    for i in range(30 - len(existing)):
        base = EXTRACT_TEMPLATES[i % len(EXTRACT_TEMPLATES)]
        new_ex = json.loads(json.dumps(base))
        # Add variation to file_path
        new_ex['input']['file_path'] = new_ex['input']['file_path'].replace('.pdf', f'_v{i+1}.pdf')
        new_examples.append(new_ex)
    
    all_data = existing + new_examples
    with open(filepath, 'w', encoding='utf-8') as f:
        for item in all_data:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
    
    print(f"  Expanded to {len(all_data)} examples")

if __name__ == "__main__":
    import json
    from pathlib import Path
    import sys
    sys.path.insert(0, str(Path.cwd()))
    
    expand_extract()
