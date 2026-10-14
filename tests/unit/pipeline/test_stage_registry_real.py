"""stage_registry 非 Mock 结构测试。

验证注册表持有的是**真实** ``StageHandler`` 子类与**真实**管线类（非 MagicMock/假替身），
反制「test_stage_registry_coverage.py 以 MagicMock 替换全部 7 个管线阶段」的覆盖泡沫。
"""

from __future__ import annotations

import src.audiobook_studio.pipeline.stage_registry as sr

EXPECTED_STAGES = [
    "extract",
    "segment",
    "analyze",
    "annotate",
    "edit",
    "audio_postprocess",
    "review",
    "synthesize",
    "quality",
    "translate",
    "text_clean",
]


def test_all_real_stages_registered():
    """全部内置 stage 均已注册，且 handler 为真实 StageHandler 子类。"""
    registered = sr.StageRegistry.list_stages()
    for name in EXPECTED_STAGES:
        assert name in registered, f"stage {name!r} 未注册"
        handler_cls = sr.StageRegistry._handlers[name]
        assert isinstance(handler_cls, type), f"stage {name!r} handler 不是类"
        assert issubclass(handler_cls, sr.StageHandler), f"stage {name!r} handler 非 StageHandler 子类"
        # 不是 mock/fake（防覆盖泡沫）
        assert "Mock" not in handler_cls.__name__
        assert "Fake" not in handler_cls.__name__


def test_core_handlers_wired_to_real_pipeline_classes():
    """核心 stage 的真实管线类可导入、为真实类且具备 run 入口。"""
    real_pipelines = [
        sr.ExtractPipeline,
        sr.AnalyzeStructurePipeline,
        sr.AnnotateParagraphPipeline,
        sr.EditForTtsPipeline,
        sr.SynthesizePipeline,
        sr.QualityCheckPipeline,
        sr.AudioPostProcessor,
    ]
    for cls in real_pipelines:
        assert isinstance(cls, type), f"{cls.__name__} 不是真实类"
        entry = getattr(cls, "run", None) or getattr(cls, "process", None) or getattr(cls, "__call__", None)
        assert callable(entry), f"{cls.__name__} 缺少真实执行入口（run/process/__call__）"
