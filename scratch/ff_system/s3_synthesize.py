"""Step 3: 真实系统管线合成 Run A (ground truth 文本 + s2 标注 → 音频).

DRY=1: 仅打印 35 段路由决策 (升级点 #2 实证: en→kokoro+am_adam)。
全量: synthesize_paragraphs 真实合成 (kokoro 本地端口 + 质检门 + 交叉淡出拼章)
      → finalize_audio audiobook 档 (-23 LUFS)。
"""
import json, os, sys
from pathlib import Path

sys.path.insert(0, "src")
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("ENABLE_LOCAL_TTS", "true")
os.environ.setdefault("EDGE_TTS_ENABLED", "false")

DRY = os.environ.get("DRY", "0") == "1"
WORK = Path("scratch/ff_system")
OUT = Path("output/football_forever_ch1/system_run")


def build_inputs():
    from audiobook_studio.schemas.book import CharacterVoiceBinding
    from audiobook_studio.schemas.paragraph import ParagraphAnnotation
    from audiobook_studio.schemas.tts_routing import TtsRoutingInput

    d = json.loads((WORK / "run_a_annotations.json").read_text())
    book, records = d["book"], d["records"]
    cvm = [CharacterVoiceBinding.model_validate(c) for c in book["character_voice_map"]]
    inputs = []
    for r in sorted(records, key=lambda x: x["idx"]):
        ann = ParagraphAnnotation.model_validate(r["annotation"])
        ovr = (r.get("director") or {}).get("sentence_overrides") or None
        inputs.append(TtsRoutingInput(
            paragraph_annotation=ann, text=r["synth_text"], character_voice_map=cvm,
            book_id="football_forever", chapter_index=1, paragraph_index=r["idx"],
            language="en", prefer_local=True, sentence_overrides=ovr,
        ))
    return inputs


def main():
    from audiobook_studio.pipeline.synthesize import make_tts_routing_decision

    inputs = build_inputs()
    print(f"[s3] {len(inputs)} 段输入构建完成; DRY={DRY}")
    engines, voices = {}, {}
    for inp in inputs:
        dec = make_tts_routing_decision(inp)
        engines[dec.engine_choice] = engines.get(dec.engine_choice, 0) + 1
        voices[dec.voice_id] = voices.get(dec.voice_id, 0) + 1
        if inp.paragraph_index < 3:
            print(f"[s3] p{inp.paragraph_index}: engine={dec.engine_choice} voice={dec.voice_id}")
            print(f"     {dec.reasoning[:180]}")
    print(f"[s3] 路由分布: engines={engines} voices={voices}")
    if DRY:
        print("[s3] DRY 结束"); return

    from audiobook_studio.pipeline.synthesize import synthesize_paragraphs
    segs = synthesize_paragraphs(inputs, output_dir=str(OUT))
    total_ms = sum(s.duration_ms or 0 for s in segs)
    print(f"[s3] 合成完成: {len(segs)} 段, 总时长 {total_ms/1000:.1f}s")

    manifest = {
        "n_segments": len(segs), "total_duration_ms": total_ms,
        "segments": [{
            "segment_id": s.segment_id, "file": str(s.file_path),
            "duration_ms": s.duration_ms,
        } for s in segs],
    }
    (OUT / "s3_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))

    # finalize: 拼章文件 → audiobook 响度档 (-23 LUFS / TP -3)
    from audiobook_studio.pipeline.audio_finalize import finalize_audio
    from audiobook_studio.schemas.audio_finalize import AudioFinalizeParams
    stitched = OUT / "football_forever_ch1.mp3"
    if not stitched.exists():
        print(f"[s3] WARN: 拼章文件不存在 {stitched}, 跳过 finalize"); return
    final = OUT / "football_forever_ch1_final.mp3"
    res = finalize_audio(
        stitched, final,
        params=AudioFinalizeParams(loudness_preset="audiobook"),
        sfx_tags=None, scene_tags=None,
    )
    print(f"[s3] finalize 完成: {final} ({res.final_duration_ms/1000:.1f}s, "
          f"lufs={getattr(res, 'measured_lufs', None)})")


if __name__ == "__main__":
    main()
