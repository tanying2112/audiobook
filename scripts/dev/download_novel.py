#!/usr/bin/env python3
"""Download Chinese novels from Project Gutenberg"""

import os
import urllib.request

# Project Gutenberg URLs for Chinese novels
NOVELS = {
    "hongloumeng": "https://www.gutenberg.org/cache/epub/24264/pg24264.txt",  # 红楼梦
    "shuihuzhuan": "https://www.gutenberg.org/cache/epub/23863/pg23863.txt",  # 水浒传
    "xiyouji": "https://www.gutenberg.org/cache/epub/23962/pg23962.txt",  # 西游记
    "hongloumeng_alt": "https://www.gutenberg.org/cache/epub/9603/pg9603.txt",  # 红楼梦 (另一版本)
}

output_dir = "/Users/guwj/Desktop/AI_Lab/audiobook/data/long_novel"
os.makedirs(output_dir, exist_ok=True)

for name, url in NOVELS.items():
    output_path = os.path.join(output_dir, f"{name}.txt")
    print(f"Downloading {name} from {url}...")
    try:
        urllib.request.urlretrieve(url, output_path)
        size = os.path.getsize(output_path)
        print(f"  ✅ Saved to {output_path} ({size:,} bytes)")
    except Exception as e:
        print(f"  ❌ Failed: {e}")

# Also create a combined file with first 100K+ chars from 红楼梦
hongloumeng_path = os.path.join(output_dir, "hongloumeng.txt")
if os.path.exists(hongloumeng_path):
    with open(hongloumeng_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    # Take first ~150K characters for testing
    sample = content[:150000]
    sample_path = os.path.join(output_dir, "hongloumeng_150k.txt")
    with open(sample_path, "w", encoding="utf-8") as f:
        f.write(sample)
    print(f"\n✅ Created sample file: {sample_path} ({len(sample):,} chars)")
