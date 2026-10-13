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
OUT = Path("output/football_forever_ch1/system_run_b")


def build_inputs():
    from audiobook_studio.schemas.book import CharacterVoiceBinding
    from audiobook_studio.schemas.paragraph import ParagraphAnnotation
    from audiobook_studio.schemas.tts_routing import TtsRoutingInput

    d = json.loads((WORK / "run_b_annotations.json").read_text())
    book, records = d["book"], d["records"]
    cvm = [CharacterVoiceBinding.model_validate(c) for c in book["character_voice_map"]]
    difficulty = (book["book_meta"].get("difficulty") or "A").strip() or None  # Gap D 传导
    inputs = []
    for r in sorted(records, key=lambda x: x["idx"]):
        ann = ParagraphAnnotation.model_validate(r["annotation"])
        ovr = (r.get("director") or {}).get("sentence_overrides") or None
        # 清洗导演 voice_id: 只保留引擎合法 kokoro 音色 (am_/af_/zf_/zm_ 开头),
        # 其余语义标签 (coach/lenda/captain 等) 置 null → 走路由层 fallback am_adam
        if ovr:
            cleaned_ovr = []
            for o in ovr:
                o2 = dict(o)
                vid = o2.get("voice_id")
                if vid and not (vid.startswith(("am_", "af_", "zf_", "zm_")) or "+" in vid):
                    o2["voice_id"] = None
                cleaned_ovr.append(o2)
            ovr = cleaned_ovr

        inputs.append(TtsRoutingInput(
            paragraph_annotation=ann, text=r["synth_text"], character_voice_map=cvm,
            book_id="football_forever", chapter_index=1, paragraph_index=r["idx"],
            language="en", prefer_local=True, sentence_overrides=ovr,
            difficulty=difficulty,
        ))
    return inputs


def main():
    from audiobook_studio.pipeline.synthesize import make_tts_routing_decision

    inputs = build_inputs()
    print(f"[s3b] {len(inputs)} 段输入构建完成; DRY={DRY}")
    engines, voices = {}, {}
    for inp in inputs:
        dec = make_tts_routing_decision(inp)
        engines[dec.engine_choice] = engines.get(dec.engine_choice, 0) + 1
        voices[dec.voice_id] = voices.get(dec.voice_id, 0) + 1
        if inp.paragraph_index < 3:
            print(f"[s3b] p{inp.paragraph_index}: engine={dec.engine_choice} voice={dec.voice_id}")
            print(f"     {dec.reasoning[:180]}")
    print(f"[s3b] 路由分布: engines={engines} voices={voices}")
    if DRY:
        print("[s3b] DRY 结束"); return

    from audiobook_studio.pipeline.synthesize import synthesize_paragraphs
    segs = synthesize_paragraphs(inputs, output_dir=str(OUT))
    total_ms = sum(s.duration_ms or 0 for s in segs)
    print(f"[s3b] 合成完成: {len(segs)} 段, 总时长 {total_ms/1000:.1f}s")

    manifest = {
        "n_segments": len(segs), "total_duration_ms": total_ms,
        "segments": [{
            "segment_id": s.segment_id, "file": str(s.file_path),
            "duration_ms": s.duration_ms,
        } for s in segs],
    }
    (OUT / "s3b_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))

    # finalize: 拼章文件 → audiobook 响度档 (-23 LUFS / TP -3)
    from audiobook_studio.pipeline.audio_finalize import finalize_audio
    from audiobook_studio.schemas.audio_finalize import AudioFinalizeParams
    stitched = OUT / "football_forever_ch1.mp3"
    if not stitched.exists():
        print(f"[s3b] WARN: 拼章文件不存在 {stitched}, 跳过 finalize"); return
    final = OUT / "football_forever_ch1_final.mp3"
    res = finalize_audio(
        stitched, final,
        params=AudioFinalizeParams(loudness_preset="audiobook"),
        sfx_tags=None, scene_tags=None,
    )
    print(f"[s3b] finalize 完成: {final} ({res.duration_ms/1000:.1f}s, "
          f"lufs={res.measured_i}, lra={res.measured_lra}, tp={res.measured_tp}, "
          f"preset={res.preset_applied}, meta={res.metadata_embedded}, warn={res.warnings}")


if __name__ == "__main__":
    main()
