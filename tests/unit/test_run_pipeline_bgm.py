"""Tests for Module 4.2 — ``--bg-music``/``--bg-volume`` CLI wiring + BGM export block.

覆盖三条主线，均为行为断言（非刷覆盖率）:
  * CLI 解析: ``parse_arguments`` 接受 ``--bg-music``/``--bg-volume`` 及其默认值。
  * 透传: ``main()`` 把这两个参数转发给 ``run_book_pipeline``。
  * 导出块: 当提供 ``bgm_path`` 时，``run_book_pipeline`` 用真实 ``MixConfig``/
    ``ExportJob`` 构造对象并调用 ``export_project``，且 BGM 路径与音量正确落到 job 上。

  —— 顺带锁住两条修复:
    Bug A (run_book_pipeline 调用 async 编排器却无 await): 用 ``AsyncMock`` + ``asyncio.run``
       驱动；若有人删掉 ``asyncio.run`` 包裹，``results`` 变为协程，``len(results)`` 立即
       TypeError → 本测试红。
    Bug B (``MixConfig`` 被传 schema 不支持的字段 ``speech_volume_db``/``fade_in_ms``/
       ``fade_out_ms``): 用真实 ``MixConfig``（非 mock），若有人加回这些 kwargs 立即 TypeError → 红。

run_pipeline.py 内部用裸 ``from audiobook_studio.*`` 导入（无 ``src`` 前缀），因此本测试把
``src/`` 放上 ``sys.path``，直接以 ``audiobook_studio.`` 命名空间导入/patch——无需 stub 任何
子模块（规避 ``test_run_pipeline.py`` 里 ``_stub_run_pipeline_deps`` 的脆性 stub）。
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 让裸 ``audiobook_studio.*`` 绝对导入解析到 src/audiobook_studio。
_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import audiobook_studio.run_pipeline as rp  # noqa: E402
from audiobook_studio.export import ExportFormat  # noqa: E402
from audiobook_studio.export.audio_ducking import MixConfig  # noqa: E402


# ── CLI 解析 ──────────────────────────────────────────────────────────────────


class TestBgmCliParsing:
    def test_explicit_bgm_flags(self, monkeypatch):
        monkeypatch.setattr(
            sys,
            "argv",
            ["run_pipeline", "--books", "红楼梦",
             "--bg-music", "/music/bgm.wav", "--bg-volume", "-18.5"],
        )
        args = rp.parse_arguments()
        assert args.bg_music == "/music/bgm.wav"
        assert args.bg_volume == -18.5
        assert args.books == ["红楼梦"]

    def test_bgm_defaults(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["run_pipeline"])
        args = rp.parse_arguments()
        assert args.bg_music is None
        assert args.bg_volume == -20.0


# ── main() 透传 ──────────────────────────────────────────────────────────────


class TestMainBgmWiring:
    def test_main_forwards_bgm_flags_to_run_book_pipeline(self, monkeypatch):
        monkeypatch.setattr(
            sys,
            "argv",
            ["run_pipeline", "--bg-music", "/bgm.wav", "--bg-volume", "-12",
             "--books", "红楼梦"],
        )
        with patch.object(rp, "run_book_pipeline") as mock_run:
            rp.main()
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        assert kwargs.get("bgm_path") == "/bgm.wav"
        assert kwargs.get("bg_volume") == -12.0
        # 未指定 --quick → 走完整阶段表
        assert kwargs.get("stages") == rp.STAGES


# ── BGM 导出块集成 ───────────────────────────────────────────────────────────


class TestRunBookPipelineBgmExport:
    def test_bgm_export_invokes_export_project_with_correct_job(self, tmp_path):
        """run_book_pipeline 在 bgm_path 给定时，应以合法 MixConfig/ExportJob 调用
        export_project，且 CLI 音量正确落到 job.mix_config.bgm_volume_db。

        同时锁住 Bug A（asyncio.run）与 Bug B（MixConfig schema）——任一回归本测试红。
        """
        bg_volume = -18.0
        chap_file = tmp_path / "chapter_01.txt"
        chap_file.write_text("章节占位文本，供 run_book_pipeline 读取。", encoding="utf-8")
        bgm = tmp_path / "bgm.wav"

        # 主 DB 会话：唯一的真实查询是段落后查询 Chapter，返回 None 以跳过段落级循环、
        # 直奔导出块；commit/close 作为 no-op。
        db_mock = MagicMock()
        db_mock.query.return_value.filter.return_value.first.return_value = None

        project = MagicMock(id=42)
        cp_mgr = MagicMock()
        cp_mgr.last_completed_stage.return_value = None  # has_incomplete 保持 False，免触发交互输入
        captured = {}

        def fake_export(project_id, session, job):
            captured["job"] = job
            done = MagicMock()
            done.progress.value = "complete"
            done.output_paths = {"m4b": str(tmp_path / "out.m4b")}
            done.error = None
            return done

        orchestrator_mock = AsyncMock(return_value=[])

        with patch.object(rp, "orchestrator_run_pipeline", new=orchestrator_mock), \
             patch.object(rp, "_get_chapter_files", return_value=[(1, chap_file)]), \
             patch.object(rp, "_find_project", return_value=project), \
             patch.object(rp, "SessionLocal", return_value=db_mock), \
             patch.object(rp, "CheckpointManager", return_value=cp_mgr), \
             patch("audiobook_studio.export.batch_exporter.export_project",
                   side_effect=fake_export):
            pid = rp.run_book_pipeline(
                "红楼梦", stages=["extract"], bgm_path=str(bgm), bg_volume=bg_volume,
            )

        # 编排器被 asyncio.run 真正驱动过（Bug A 回归保护：删 asyncio.run 则永不调用）
        orchestrator_mock.assert_called_once()
        # 返回 project.id
        assert pid == 42

        # Bug B 回归保护：真实 MixConfig 成功构造并携带 CLI 音量
        job = captured.get("job")
        assert job is not None, "export_project 未被调用——导出块未抵达"
        assert job.mix_config is not None
        assert job.mix_config.bgm_volume_db == bg_volume
        # BGM 路径由 ExportJob 承载（batch_exporter 从 job.bgm_path 取，见 batch_exporter:318/349）
        assert job.bgm_path == str(bgm)
        # 默认导出格式 M4B+SRT
        assert ExportFormat.M4B_SRT in job.formats


# ── MixConfig schema 文档化（Bug B 根因） ────────────────────────────────────


class TestMixConfigSchema:
    def test_invalid_fade_and_speech_kwargs_raise(self):
        """锁死 MixConfig schema：bgm 淡入淡出 / 语音音量并非该 dataclass 支持
        的参数。若未来 audio_ducking 补上这些字段，此处再同步调整——在此之前它们
        必须被拒绝，避免主路径悄悄回退到这一坏构造。
        """
        with pytest.raises(TypeError):
            MixConfig(bgm_volume_db=-18.0, speech_volume_db=0.0,
                      fade_in_ms=2000, fade_out_ms=3000)

    def test_bgm_volume_only_constructs(self):
        """run_book_pipeline 导出块使用的唯一有效构造，必须成立。"""
        cfg = MixConfig(bgm_volume_db=-18.0)
        assert cfg.bgm_volume_db == -18.0
