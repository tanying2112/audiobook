"""Phase C structural tests for utils/stage_normalizer.py (pure logic)."""

from src.audiobook_studio.utils.stage_normalizer import (
    CHAPTER_STATUS_FIELDS,
    CanonicalStage,
    get_stage_display_name,
    get_stage_order,
    get_stage_short_name,
    infer_audio_postprocess_status,
    normalize_stage_name,
)


def test_canonical_stage_display_and_short_names():
    assert CanonicalStage.EXTRACT.display_name == "文本提取"
    assert CanonicalStage.EXTRACT.short_name == "提取"
    assert CanonicalStage.QUALITY.display_name == "质量检查"
    assert CanonicalStage.QUALITY.short_name == "质检"
    # Unknown values fall back to the raw value
    assert CanonicalStage.EXTRACT.display_name  # non-empty


def test_normalize_direct_alias():
    assert normalize_stage_name("extract") == "extract"
    assert normalize_stage_name("analyze") == "analyze_structure"
    assert normalize_stage_name("annotate") == "annotate_paragraph"
    assert normalize_stage_name("edit") == "edit_for_tts"
    assert normalize_stage_name("postprocess") == "audio_postprocess"
    assert normalize_stage_name("synthesize") == "synthesize"
    assert normalize_stage_name("quality") == "quality_check"
    assert normalize_stage_name("qc") == "quality_check"
    assert normalize_stage_name("judge") == "quality_check"


def test_normalize_whitespace_and_case():
    assert normalize_stage_name("  Annotate ") == "annotate_paragraph"
    assert normalize_stage_name("SYNTHESIZE") == "synthesize"


def test_normalize_no_underscore_fallback():
    # "annotate_paragraph" with underscores removed won't match a no-underscore
    # alias, but "editfortts" should match "edit_for_tts"
    assert normalize_stage_name("editfortts") == "edit_for_tts"
    assert normalize_stage_name("audiopostprocess") == "audio_postprocess"


def test_normalize_frontend_and_orm_aliases():
    assert normalize_stage_name("③") == "annotate_paragraph"
    assert normalize_stage_name("⑦") == "quality_check"
    assert normalize_stage_name("extract_status") == "extract"
    assert normalize_stage_name("route_status") == "audio_postprocess"


def test_normalize_unknown_passthrough():
    assert normalize_stage_name("custom_stage") == "custom_stage"
    assert normalize_stage_name("") == ""


def test_get_stage_order():
    order = get_stage_order()
    assert order == [
        "extract",
        "analyze_structure",
        "annotate_paragraph",
        "edit_for_tts",
        "audio_postprocess",
        "synthesize",
        "quality_check",
    ]


def test_get_stage_display_name():
    assert get_stage_display_name("qc") == "质量检查"
    assert get_stage_display_name("annotate") == "段落标注"
    assert get_stage_display_name("unknown_thing") == "unknown_thing"


def test_get_stage_short_name():
    assert get_stage_short_name("qc") == "质检"
    assert get_stage_short_name("annotate") == "标注"
    assert get_stage_short_name("unknown_thing") == "unknown_thing"


def test_infer_audio_postprocess_status_both_completed():
    data = {"edit_status": "completed", "route_status": "completed"}
    assert infer_audio_postprocess_status(data) == "completed"


def test_infer_audio_postprocess_status_running():
    assert infer_audio_postprocess_status({"edit_status": "running", "route_status": "pending"}) == "running"
    assert infer_audio_postprocess_status({"edit_status": "completed", "route_status": "running"}) == "running"


def test_infer_audio_postprocess_status_default():
    assert infer_audio_postprocess_status({"edit_status": "pending", "route_status": "failed"}) == "failed"
    assert infer_audio_postprocess_status({}) == "pending"


def test_chapter_status_fields_mapping():
    assert CHAPTER_STATUS_FIELDS["route_status"] is CanonicalStage.AUDIO_POSTPROCESS
    assert CHAPTER_STATUS_FIELDS["quality_status"] is CanonicalStage.QUALITY
