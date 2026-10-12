"""探针：验证系统 UTMOS（torch.hub 已缓存权重）与 faster-whisper CER 能否在本机独立脚本跑通。
被评音频：A/B 样本（espeak vs misaki 前端）。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

wavs = [
    ("espeak", "output/howtolivebetter_ch23/ab_test_espeak.wav"),
    ("misaki", "output/howtolivebetter_ch23/ab_test_misaki.wav"),
]

# 1) UTMOS via system metric
from src.audiobook_studio.quality.metrics import UTMOSMetric
um = UTMOSMetric()
for name, path in wavs:
    score = um.compute(Path(path))
    print(f"UTMOS[{name}] = {score:.4f}")

# 2) CER via system ASRMetric (faster-whisper base, cached)
from src.audiobook_studio.quality.metrics import ASRMetric
asr = ASRMetric(backend="whisper", model_name="base", use_faster_whisper=True)
refs = [
    "二十三，学什么技能划算。这一节算的是钱和时间。第 2 条算读书和寿命的关系：每多受一年教育，死亡风险平均下降 1.9%。一份纳入 59 项研究的多层荟萃分析显示，交错练习相对于分块练习的总体效应属于中等。",
] * 2
for (name, path), ref in zip(wavs, refs):
    res = asr.compute(Path(path), reference_text=ref, language="zh")
    print(f"ASR[{name}] wer={res.wer:.3f} cer={res.cer:.3f} ok={res.success}")
    if not res.success:
        print("  err:", getattr(res, "error_message", None) or res.to_dict())
