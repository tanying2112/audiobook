"""M1 提示词版本化闭环门面测试（复用现有 VersionStore）。"""

from __future__ import annotations

from pathlib import Path

from audiobook_studio.feedback.prompt_store import PromptStore


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_prompts(tmp_path: Path) -> Path:
    _write(tmp_path / "annotate_paragraph" / "v1.j2", "SYS v1 {{ schema_json }}")
    _write(tmp_path / "annotate_paragraph" / "v2.j2", "SYS v2 {{ schema_json }}")
    _write(tmp_path / "edit_for_tts" / "v1.j2", "EDIT v1")
    return tmp_path


def test_active_version_and_list(tmp_path: Path):
    ps = PromptStore(prompts_dir=_make_prompts(tmp_path))
    assert ps.active_version("annotate") == 2  # max(v1,v2)
    assert ps.list_versions("annotate") == [1, 2]
    assert ps.active_version("edit") == 1


def test_load_version_and_active(tmp_path: Path):
    ps = PromptStore(prompts_dir=_make_prompts(tmp_path))
    assert ps.load_version("annotate", 1) == "SYS v1 {{ schema_json }}"
    assert ps.load_active("annotate") == "SYS v2 {{ schema_json }}"  # 当前生效为 v2
    assert ps.load_version("annotate", 99) is None
    assert ps.load_active("translate") is None  # 未配置 stage


def test_promote_and_rollback(tmp_path: Path):
    ps = PromptStore(prompts_dir=_make_prompts(tmp_path))
    # 新增 v3 并晋升
    _write(tmp_path / "annotate_paragraph" / "v3.j2", "SYS v3")
    assert ps.promote("annotate", 3) is True
    assert ps.active_version("annotate") == 3
    assert ps.load_active("annotate") == "SYS v3"
    # promote 低版本应失败
    assert ps.promote("annotate", 1) is False
    # 回滚到 v1
    assert ps.rollback("annotate", 1) is True
    assert ps.active_version("annotate") == 1
    assert ps.load_active("annotate") == "SYS v1 {{ schema_json }}"
    # 回滚到 >= 当前版本应失败
    assert ps.rollback("annotate", 1) is False


def test_status_reports_current_versions(tmp_path: Path):
    ps = PromptStore(prompts_dir=_make_prompts(tmp_path))
    status = ps.status()
    assert "current_versions" in status
    assert status["current_versions"]["annotate_paragraph"] == 2
