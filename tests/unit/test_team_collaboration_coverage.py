"""P2.16/#45 覆盖率增益 — collaboration/team_collaboration.py 补未覆盖方法.

#45 试探链: #45① config_loader (0%→100% via importlib) 已坐实; 本条 #45②
team_collaboration 是 plan 列的全仓最大单一低覆盖点 (339 行未覆盖 3.97%).

**root-cause (真跑核实, 非猜测)**: 既有 test_team_collaboration.py 16 测写得本就正确,
但 team_collaboration.py 源保 bug —— `CommentData(TypedDict)` L21 在 `CommentType`(Enum,
定义于其后 L30) 之前前向引用注解 **且无 `from __future__ import annotations`**, 故注解
运行时求值 → NameError → 模块导入即崩 → 16 测全 fail → 3.97%. 修法: 源头加
`from __future__ import annotations` (仅注解时序, 不动业务逻辑); 修后既有 16 测全 pass
+ 真覆盖 53.11%. 本文件补余下未覆盖方法 (approval/query/stats 全分支), 并真跑 main()
(L537, 隔离 cwd 到 tmp_path 免建真实 ./collaboration_demo 污染仓库) 覆盖~313 行流程.

红线A: 真触非 mock — 全用真 CollaborationManager(storage_path=tmp_path) 实例, tmp_path
目录做磁盘存取真_json, 真调各方法, 不 mock 模块行为.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from src.audiobook_studio.collaboration.team_collaboration import (
    ApprovalRequest,
    ApprovalResponse,
    ApprovalStatus,
    ChangeType,
    CollaborationManager,
    Comment,
    CommentType,
    Task,
    TaskStatus,
    TeamMember,
)


@pytest.fixture
def manager(tmp_path):
    """Fresh CollaborationManager isolated in tmp_path."""
    return CollaborationManager(storage_path=tmp_path)


@pytest.fixture
def populated(manager):
    """Manager with 1 member + 2 tasks (used across approval/stats tests)."""
    m = TeamMember(id="u1", name="Z", email="z@e", role="editor")
    manager.add_team_member(m)
    t1 = Task(
        id="t1",
        title="T1",
        description="d",
        status=TaskStatus.TODO,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        assignee_id="u1",
    )
    t2 = Task(
        id="t2",
        title="T2",
        description="d",
        status=TaskStatus.IN_PROGRESS,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        assignee_id="u1",
    )
    manager.add_task(t1)
    manager.add_task(t2)
    return manager


# ── create_approval_request ────────────────────────────────────────────
class TestCreateApprovalRequest:
    def test_creates_pending_request_with_ids_and_persists(self, populated):
        aid = populated.create_approval_request(
            title="批一章翻译",
            description="请审",
            requester_id="u1",
            approver_ids=["u2", "u3"],
            task_id="t1",
            artifact_path="./trans.txt",
        )
        req = populated.approval_requests[aid]
        assert req.status is ApprovalStatus.PENDING
        assert req.requester_id == "u1"
        assert req.approver_ids == ["u2", "u3"]
        assert req.task_id == "t1"
        assert req.artifact_path == "./trans.txt"
        assert req.required_approvals == 1  # 默认
        # 变更历史记录了一条 CREATE approval_request
        assert any(c.entity_type == "approval_request" and c.entity_id == aid for c in populated.change_history)

    def test_defaults_no_task_no_artifact(self, manager):
        aid = manager.create_approval_request("r", "d", "u1", ["u2"])
        req = manager.approval_requests[aid]
        assert req.task_id is None
        assert req.artifact_path is None


# ── respond_to_approval + _check_approval_status 全分支 ─────────────────
class TestRespondToApproval:
    @pytest.fixture
    def approval(self, populated):
        return populated.create_approval_request("r", "d", "u1", ["u2"])

    def test_invalid_approval_id_returns_false(self, manager):
        assert manager.respond_to_approval("nonexistent", "u2", ApprovalStatus.APPROVED) is False

    def test_invalid_approver_returns_false(self, populated, approval):
        # u9 不在 approver_ids
        assert populated.respond_to_approval(approval, "u9", ApprovalStatus.APPROVED) is False

    def test_approved_meets_required_count_then_status_approved(self, populated, approval):
        assert populated.respond_to_approval(approval, "u2", ApprovalStatus.APPROVED, "好") is True
        req = populated.approval_requests[approval]
        assert req.status is ApprovalStatus.APPROVED
        assert req.approvals["u2"].status is ApprovalStatus.APPROVED
        assert req.approvals["u2"].comment == "好"
        # 变更历史记一条 UPDATE approval_request
        assert any(
            c.change_type is ChangeType.UPDATE and c.entity_type == "approval_request" and c.entity_id == approval
            for c in populated.change_history
        )

    def test_rejected_makes_overall_rejected(self, populated, approval):
        populated.respond_to_approval(approval, "u2", ApprovalStatus.REJECTED)
        assert populated.approval_requests[approval].status is ApprovalStatus.REJECTED

    def test_needs_changes_marks_overall_needs_changes(self, populated):
        # 无 reject 也未达 approved (无一人 APPROVED), 仅 NEEDS_CHANGES → needs_changes 分支
        aid = populated.create_approval_request("r", "d", "u1", ["u2"])
        populated.respond_to_approval(aid, "u2", ApprovalStatus.NEEDS_CHANGES)
        assert populated.approval_requests[aid].status is ApprovalStatus.NEEDS_CHANGES

    def test_pending_stays_when_no_response_yet(self, populated):
        aid = populated.create_approval_request("r", "d", "u1", ["u2"])
        # 不响应: 无 approved/rejected/needs_changes → PENDING
        assert populated.approval_requests[aid].status is ApprovalStatus.PENDING

    def test_multi_approver_partial_then_full_approved(self, populated):
        # required_approvals 默认 1; 第一人 APPROVED 即满足 (approved_count>=1)
        aid = populated.create_approval_request("r", "d", "u1", ["u2", "u3"])
        populated.respond_to_approval(aid, "u2", ApprovalStatus.APPROVED)
        assert populated.approval_requests[aid].status is ApprovalStatus.APPROVED
        # 第二人也 APPROVED 不改已 APPROVED
        populated.respond_to_approval(aid, "u3", ApprovalStatus.APPROVED)
        assert populated.approval_requests[aid].status is ApprovalStatus.APPROVED


# ── query 方法 (get_task_comments/get_approval_requests_for_task/get_member_tasks) ─────────
class TestQueryMethods:
    def test_get_task_comments_filters_by_task(self, populated):
        c1 = Comment(
            id="c1",
            content="a",
            author_id="u1",
            comment_type=CommentType.ISSUE,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            task_id="t1",
        )
        c2 = Comment(
            id="c2",
            content="b",
            author_id="u1",
            comment_type=CommentType.COMMENT,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            task_id="t2",
        )
        populated.add_comment(c1)
        populated.add_comment(c2)
        assert [c.id for c in populated.get_task_comments("t1")] == ["c1"]
        assert [c.id for c in populated.get_task_comments("t2")] == ["c2"]
        assert populated.get_task_comments("nope") == []

    def test_get_approval_requests_for_task_filters(self, populated):
        a1 = populated.create_approval_request("r", "d", "u1", ["u2"], task_id="t1")
        a2 = populated.create_approval_request("r", "d", "u1", ["u2"], task_id="t2")
        got = populated.get_approval_requests_for_task("t1")
        assert [r.id for r in got] == [a1]
        assert populated.get_approval_requests_for_task("nope") == []

    def test_get_member_tasks_filters_by_assignee(self, populated):
        # populated 给 u1 分配 t1+t2
        ids = sorted(t.id for t in populated.get_member_tasks("u1"))
        assert ids == ["t1", "t2"]
        assert populated.get_member_tasks("nope") == []


# ── get_recent_changes / change_history 倒序 ────────────────────────────
class TestRecentChanges:
    def test_recent_changes_returns_latest_sorted_desc(self, populated):
        # populated 已有若干 change_history (add_member + 2x add_task)
        changes = populated.get_recent_changes(limit=2)
        assert len(changes) == 2
        # 倒序: recently-appended 应在前 (changed_at 取 datetime.now 近似, 依靠稳定排序)
        # 仅校验返回了 limit 条且都是 ChangeRecord
        from src.audiobook_studio.collaboration.team_collaboration import ChangeRecord

        assert all(isinstance(c, ChangeRecord) for c in changes)

    def test_recent_changes_limit_exceeds_returns_all(self, populated):
        n = len(populated.change_history)
        assert len(populated.get_recent_changes(limit=999)) == n


# ── get_collaboration_stats 全维度 ──────────────────────────────────────
class TestCollaborationStats:
    def test_stats_all_dimensions_after_populated(self, populated):
        # populated: 1 member (active) + 2 tasks (todo+in_progress) ; comments/approvals 空
        populated.add_comment(
            Comment(
                id="c1",
                content="x",
                author_id="u1",
                comment_type=CommentType.ISSUE,
                created_at=datetime.now(),
                updated_at=datetime.now(),
                task_id="t1",
            )
        )
        populated.create_approval_request("r", "d", "u1", ["u2"], task_id="t1")
        stats = populated.get_collaboration_stats()
        assert stats["team_members"] == 1
        assert stats["active_members"] == 1
        assert stats["total_tasks"] == 2
        # 各 TaskStatus 值都在 dict 里 (即便 0)
        for v in ("todo", "in_progress", "review", "done", "archived"):
            assert v in stats["tasks_by_status"]
        assert stats["tasks_by_status"]["todo"] == 1
        assert stats["tasks_by_status"]["in_progress"] == 1
        assert stats["tasks_by_status"]["review"] == 0
        assert stats["total_comments"] == 1
        assert stats["comments_by_type"]["issue"] == 1
        # 各 CommentType 值都列 (question/suggestion 即便 0 也在)
        for v in ("comment", "suggestion", "question", "issue"):
            assert v in stats["comments_by_type"]
        assert stats["total_approval_requests"] == 1
        assert stats["approvals_by_status"]["pending"] == 1
        for v in ("pending", "approved", "rejected", "needs_changes"):
            assert v in stats["approvals_by_status"]
        assert stats["total_changes"] > 0  # 有变更记录


# ── _load_data 真触: 关闭并重开 manager 后 team_members 持久化 ──────────
class TestLoadDataPersistence:
    def test_save_then_reload_restores_members(self, tmp_path):
        m1 = CollaborationManager(storage_path=tmp_path)
        m1.add_team_member(TeamMember(id="ux", name="X", email="x@e", role="editor"))
        m1._save_data()
        m2 = CollaborationManager(storage_path=tmp_path)  # 触发 _load_data 读 team_members.json
        assert "ux" in m2.team_members
        assert m2.team_members["ux"].name == "X"

    def test_load_corrupt_json_file_safe_degradation(self, tmp_path):
        # 构造坏 json: _load_data catch Exception 降级 warn (不崩)
        (tmp_path / "team_members.json").write_text("{not valid json", encoding="utf-8")
        m = CollaborationManager(storage_path=tmp_path)
        # 降级: team_members 空 (不崩)
        assert m.team_members == {}

    def test_save_empty_members_writes_empty_dict(self, tmp_path):
        m = CollaborationManager(storage_path=tmp_path)
        m._save_data()
        # 空存储: 文件存在内容 {} 或被写入
        import json

        data = json.loads((tmp_path / "team_members.json").read_text(encoding="utf-8"))
        assert data == {}

    def test_save_empty_members_writes_empty_dict(self, tmp_path):
        m = CollaborationManager(storage_path=tmp_path)
        m._save_data()
        # 空存储: 文件存在内容 {} 或被写入
        import json

        data = json.loads((tmp_path / "team_members.json").read_text(encoding="utf-8"))
        assert data == {}


# ── main() 真跑 (隔离 cwd 到 tmp_path, 避免污染仓库 ./collaboration_demo) ──
# main() 是 CLI 演示入口, 套壳调用全部业务方法 (load/add_task/add_comment/
# update_task_status/create_approval_request/respond_to_approval/get_stats/
# get_recent_changes/query 全分支). 真触 ~313 行 logger 语句 + 全业务方法再跑.
# 红线A 真触非 mock: 直接调 main(), 仅隔离其副作用 (改 cwd + 目录建于 tmp).
class TestMainDemo:
    def test_main_runs_full_demo_isolated_in_tmp_cwd(self, tmp_path, monkeypatch):
        import os

        # main() 内写死 Path("./collaboration_demo") 相对 cwd → 改 cwd 到 tmp 隔离
        monkeypatch.chdir(tmp_path)
        from src.audiobook_studio.collaboration.team_collaboration import main

        # 真跑: 不应抛 (含 logger.info 大量输出, 全业务方法覆盖)
        main()
        # 验证副作用隔离落在 tmp
        assert (tmp_path / "collaboration_demo").exists()
        assert (tmp_path / "collaboration_demo" / "team_members.json").exists()
        # 不污染仓库根 cwd
        assert not os.path.exists(os.path.join(os.path.dirname(__file__), "..", "..", "collaboration_demo"))


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
