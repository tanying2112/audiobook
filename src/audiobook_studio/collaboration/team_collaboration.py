#!/usr/bin/env python3
"""
Audiobook Studio — 团队协作系统
========================================
实现评论/审批/任务状态/变更历史的团队协作功能。
"""

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class CommentType(Enum):
    """评论类型"""

    COMMENT = "comment"
    SUGGESTION = "suggestion"
    QUESTION = "question"
    ISSUE = "issue"


class TaskStatus(Enum):
    """任务状态"""

    TODO = "todo"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    DONE = "done"
    ARCHIVED = "archived"


class ApprovalStatus(Enum):
    """审批状态"""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_CHANGES = "needs_changes"


class ChangeType(Enum):
    """变更类型"""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    MOVE = "move"


@dataclass
class TeamMember:
    """团队成员"""

    id: str
    name: str
    email: str
    role: str  # e.g., "translator", "editor", "narrator", "proofreader", "manager"
    is_active: bool = True
    avatar_url: Optional[str] = None
    # 技能和偏好
    skills: List[str] = field(default_factory=list)
    languages: List[str] = field(default_factory=list)


@dataclass
class Comment:
    """评论"""

    id: str
    content: str
    author_id: str
    comment_type: CommentType
    created_at: datetime
    updated_at: datetime
    # 关联对象（可选）
    task_id: Optional[str] = None
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    # 回复关系
    parent_id: Optional[str] = None  # 如果是回复另一条评论
    resolved: bool = False
    resolved_by: Optional[str] = None
    resolved_at: Optional[datetime] = None


@dataclass
class Task:
    """任务"""

    id: str
    title: str
    description: str
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
    assignee_id: Optional[str] = None
    reporter_id: Optional[str] = None
    due_date: Optional[datetime] = None
    # 标签和优先级
    tags: List[str] = field(default_factory=list)
    priority: int = 1  # 1-5, 5为最高优先级
    # 估算工时
    estimated_hours: Optional[float] = None
    actual_hours: Optional[float] = None
    # 关联
    project_id: Optional[str] = None
    parent_task_id: Optional[str] = None  # 子任务
    depends_on: List[str] = field(default_factory=list)  # 前置任务


@dataclass
class ApprovalRequest:
    """审批请求"""

    id: str
    title: str
    description: str
    requester_id: str
    approver_ids: List[str]  # 需要审批的人员IDs
    status: ApprovalStatus
    created_at: datetime
    updated_at: datetime
    # 审批详情
    approvals: Dict[str, ApprovalResponse] = field(default_factory=dict)
    # 关联对象
    task_id: Optional[str] = None
    artifact_path: Optional[str] = None  # 待审批的 artifact（如文件、分支等）
    # 审批要求
    required_approvals: int = 1  # 需要多少人批准才能通过
    auto_approve_if_unstoppable: bool = False  # 如果没有人拒绝，是否自动批准


@dataclass
class ApprovalResponse:
    """审批响应"""

    approver_id: str
    status: ApprovalStatus
    commented_at: datetime
    comment: Optional[str] = None


@dataclass
class ChangeRecord:
    """变更记录"""

    id: str
    change_type: ChangeType
    entity_type: str  # 如 "task", "comment", "file", "approval"
    entity_id: str
    changed_by: str
    changed_at: datetime
    # 变更前后的状态（简化为JSON字符串）
    old_state: Optional[str] = None
    new_state: Optional[str] = None
    # 描述
    description: str = ""
    # 关联
    related_change_id: Optional[str] = None  # 用于撤销/重做链


class CollaborationManager:
    """团队协作管理器"""

    def __init__(self, storage_path: Path = Path("./collaboration_data")):
        self.storage_path = storage_path
        self.storage_path.mkdir(parents=True, exist_ok=True)

        # 内存存储（实际应用 zou 使用数据库）
        self.team_members: Dict[str, TeamMember] = {}
        self.comments: Dict[str, Comment] = {}
        self.tasks: Dict[str, Task] = {}
        self.approval_requests: Dict[str, ApprovalRequest] = {}
        self.change_history: List[ChangeRecord] = []

        # 加载已有数据
        self._load_data()

    def _load_data(self):
        """从磁盘加载数据"""
        # 加载团队成员
        members_file = self.storage_path / "team_members.json"
        if members_file.exists():
            try:
                with open(members_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for member_id, member_data in data.items():
                        # 转换datetime字段
                        if "created_at" in member_data:
                            member_data["created_at"] = datetime.fromisoformat(
                                member_data["created_at"]
                            )
                        if "updated_at" in member_data:
                            member_data["updated_at"] = datetime.fromisoformat(
                                member_data["updated_at"]
                            )
                        self.team_members[member_id] = TeamMember(**member_data)
            except Exception as e:
                logger.warning(f"⚠️ 加载团队成员数据失败: {e}")

        # 可以继续加载其他数据类型...
        # 为简化演示，这里只加载团队成员

    def _save_data(self):
        """保存数据到磁盘"""
        # 保存团队成员
        members_file = self.storage_path / "team_members.json"
        try:
            data = {}
            for member_id, member in self.team_members.items():
                member_dict = {
                    "id": member.id,
                    "name": member.name,
                    "email": member.email,
                    "role": member.role,
                    "is_active": member.is_active,
                    "avatar_url": member.avatar_url,
                    "skills": member.skills,
                    "languages": member.languages,
                }
                data[member_id] = member_dict
            with open(members_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"💾 保存了 {len(self.team_members)} 个团队成员数据")
        except Exception as e:
            logger.warning(f"⚠️ 保存团队成员数据失败: {e}")

        # 可以继续保存其他数据类型...
        # 为简化演示，这里只保存团队成员

    def add_team_member(self, member: TeamMember) -> str:
        """添加团队成员"""
        if not member.id:
            member.id = str(uuid.uuid4())

        # 设置时间戳
        now = datetime.now()
        if not hasattr(member, "created_at") or not member.created_at:
            member.created_at = now
        member.updated_at = now

        self.team_members[member.id] = member
        self._save_data()

        # 记录变更
        self._record_change(
            ChangeType.CREATE,
            "team_member",
            member.id,
            member.id,  # 在简单实现中，entity_id 就是成员ID
            None,  # 没有旧状态
            member,
        )

        return member.id

    def add_comment(self, comment: Comment) -> str:
        """添加评论"""
        if not comment.id:
            comment.id = str(uuid.uuid4())

        # 设置时间戳
        now = datetime.now()
        comment.created_at = now
        comment.updated_at = now

        self.comments[comment.id] = comment
        self._save_data()  # 简化：每次操作都保存

        # 记录变更
        self._record_change(
            ChangeType.CREATE, "comment", comment.id, comment.id, None, comment
        )

        return comment.id

    def add_task(self, task: Task) -> str:
        """添加任务"""
        if not task.id:
            task.id = str(uuid.uuid4())

        # 设置时间戳
        now = datetime.now()
        task.created_at = now
        task.updated_at = now

        self.tasks[task.id] = task
        self._save_data()

        # 记录变更
        self._record_change(ChangeType.CREATE, "task", task.id, task.id, None, task)

        return task.id

    def update_task_status(
        self, task_id: str, new_status: TaskStatus, updated_by: str
    ) -> bool:
        """更新任务状态"""
        if task_id not in self.tasks:
            return False

        task = self.tasks[task_id]
        old_status = task.status

        # 更新状态
        task.status = new_status
        task.updated_at = datetime.now()

        self._save_data()

        # 记录变更
        change_record = ChangeRecord(
            id=str(uuid.uuid4()),
            change_type=ChangeType.UPDATE,
            entity_type="task",
            entity_id=task_id,
            changed_by=updated_by,
            changed_at=datetime.now(),
            old_state=f'{{"status": "{old_status.value}"}}',
            new_state=f'{{"status": "{new_status.value}"}}',
            description=f"将任务 '{task.title}' 状态从 {old_status.value} 更改为 {new_status.value}",
        )
        self.change_history.append(change_record)
        self._save_data()

        return True

    def create_approval_request(
        self,
        title: str,
        description: str,
        requester_id: str,
        approver_ids: List[str],
        task_id: Optional[str] = None,
        artifact_path: Optional[str] = None,
    ) -> str:
        """创建审批请求"""
        approval_request = ApprovalRequest(
            id=str(uuid.uuid4()),
            title=title,
            description=description,
            requester_id=requester_id,
            approver_ids=approver_ids,
            status=ApprovalStatus.PENDING,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            task_id=task_id,
            artifact_path=artifact_path,
        )

        self.approval_requests[approval_request.id] = approval_request
        self._save_data()

        # 记录变更
        self._record_change(
            ChangeType.CREATE,
            "approval_request",
            approval_request.id,
            approval_request.id,
            None,
            approval_request,
        )

        return approval_request.id

    def respond_to_approval(
        self,
        approval_request_id: str,
        approver_id: str,
        status: ApprovalStatus,
        comment: Optional[str] = None,
    ) -> bool:
        """响应审批请求"""
        if approval_request_id not in self.approval_requests:
            return False

        approval_request = self.approval_requests[approval_request_id]

        # 检查是否是有效的审批者
        if approver_id not in approval_request.approver_ids:
            return False

        # 记录审批响应
        approval_request.approvals[approver_id] = ApprovalResponse(
            approver_id=approver_id,
            status=status,
            commented_at=datetime.now(),
            comment=comment,
        )

        approval_request.updated_at = datetime.now()

        # 检查是否满足审批条件
        self._check_approval_status(approval_request)

        self._save_data()

        # 记录变更
        change_record = ChangeRecord(
            id=str(uuid.uuid4()),
            change_type=ChangeType.UPDATE,
            entity_type="approval_request",
            entity_id=approval_request_id,
            changed_by=approver_id,
            changed_at=datetime.now(),
            old_state=f'{{"approvals_count": {len(approval_request.approvals) - 1}}}',
            new_state=f'{{"approvals_count": {len(approval_request.approvals)}}}',
            description=f"审批者 {approver_id} 对请求 '{approval_request.title}' 进行了 {status.value} 评价",
        )
        self.change_history.append(change_record)
        self._save_data()

        return True

    def _check_approval_status(self, approval_request: ApprovalRequest):
        """检查并更新审批请求的状态"""
        if not approval_request.approver_ids:
            approval_request.status = ApprovalStatus.APPROVED
            return

        approved_count = sum(
            1
            for resp in approval_request.approvals.values()
            if resp.status == ApprovalStatus.APPROVED
        )
        rejected_count = sum(
            1
            for resp in approval_request.approvals.values()
            if resp.status == ApprovalStatus.REJECTED
        )
        needs_changes_count = sum(
            1
            for resp in approval_request.approvals.values()
            if resp.status == ApprovalStatus.NEEDS_CHANGES
        )

        # 如果有人拒绝，则整体被拒绝
        if rejected_count > 0:
            approval_request.status = ApprovalStatus.REJECTED
        # 如果达到所需批准数且没有人拒绝，则批准
        elif (
            approved_count >= approval_request.required_approvals
            and rejected_count == 0
        ):
            approval_request.status = ApprovalStatus.APPROVED
        # 如果有人需要修改，则标记为需要修改
        elif needs_changes_count > 0:
            approval_request.status = ApprovalStatus.NEEDS_CHANGES
        # 否则保持待处理状态
        else:
            approval_request.status = ApprovalStatus.PENDING

    def get_task_comments(self, task_id: str) -> List[Comment]:
        """获取任务的所有评论"""
        return [
            comment for comment in self.comments.values() if comment.task_id == task_id
        ]

    def get_approval_requests_for_task(self, task_id: str) -> List[ApprovalRequest]:
        """获取任务的所有审批请求"""
        return [
            req for req in self.approval_requests.values() if req.task_id == task_id
        ]

    def get_member_tasks(self, member_id: str) -> List[Task]:
        """获取成员分配的所有任务"""
        return [task for task in self.tasks.values() if task.assignee_id == member_id]

    def _record_change(
        self,
        change_type: ChangeType,
        entity_type: str,
        entity_id: str,
        changed_by: str,
        old_state: Optional[object],
        new_state: Optional[object],
    ):
        """记录变更历史"""
        change_record = ChangeRecord(
            id=str(uuid.uuid4()),
            change_type=change_type,
            entity_type=entity_type,
            entity_id=entity_id,
            changed_by=changed_by,
            changed_at=datetime.now(),
            old_state=(
                json.dumps(old_state, default=str) if old_state is not None else None
            ),
            new_state=(
                json.dumps(new_state, default=str) if new_state is not None else None
            ),
            description=f"{change_type.value} {entity_type} {entity_id}",
        )
        self.change_history.append(change_record)

    def get_recent_changes(self, limit: int = 20) -> List[ChangeRecord]:
        """获取最近的变更记录"""
        # 按时间倒序排序
        sorted_changes = sorted(
            self.change_history, key=lambda c: c.changed_at, reverse=True
        )
        return sorted_changes[:limit]

    def get_collaboration_stats(self) -> Dict:
        """获取协作统计信息"""
        # 任务状态统计
        task_status_counts = {}
        for status in TaskStatus:
            task_status_counts[status.value] = sum(
                1 for task in self.tasks.values() if task.status == status
            )

        # 评论类型统计
        comment_type_counts = {}
        for comment_type in CommentType:
            comment_type_counts[comment_type.value] = sum(
                1
                for comment in self.comments.values()
                if comment.comment_type == comment_type
            )

        # 审批状态统计
        approval_status_counts = {}
        for status in ApprovalStatus:
            approval_status_counts[status.value] = sum(
                1 for req in self.approval_requests.values() if req.status == status
            )

        return {
            "team_members": len(self.team_members),
            "active_members": sum(1 for m in self.team_members.values() if m.is_active),
            "total_tasks": len(self.tasks),
            "tasks_by_status": task_status_counts,
            "total_comments": len(self.comments),
            "comments_by_type": comment_type_counts,
            "total_approval_requests": len(self.approval_requests),
            "approvals_by_status": approval_status_counts,
            "total_changes": len(self.change_history),
        }


def main():
    """主函数 - 演示团队协作系统"""
    logger.info("=== Audiobook Studio 团队协作系统演示 ===\n")

    # 创建协作管理器
    collab_manager = CollaborationManager(Path("./collaboration_demo"))

    logger.info("👥 初始化团队成员...\n")

    # 添加团队成员
    members = [
        TeamMember(
            id="",
            name="张译文",
            email="zhang.yifan@audiobookstudio.example.com",
            role="translator",
            skills=["translation", "proofreading"],
            languages=["zh-CN", "en-US", "ja-JP"],
        ),
        TeamMember(
            id="",
            name="李音工",
            email="li.yingong@audiobookstudio.example.com",
            role="narrator",
            skills=["voice_acting", "audio_editing"],
            languages=["zh-CN"],
        ),
        TeamMember(
            id="",
            name="王编辑",
            email="wang.bianji@audiobookstudio.example.com",
            role="editor",
            skills=["editing", "qa", "proofreading"],
            languages=["zh-CN", "en-US"],
        ),
        TeamMember(
            id="",
            name="赵经理",
            email="zhao.jingli@audiobookstudio.example.com",
            role="manager",
            skills=["project_management", "coordination"],
            languages=["zh-CN"],
        ),
    ]

    member_ids = []
    for member in members:
        member_id = collab_manager.add_team_member(member)
        member_ids.append(member_id)
        logger.info(f"   ✅ 添加成员: {member.name} ({member.role})")

    logger.info(f"\n📊 团队成员总数: {len(collab_manager.team_members)}")

    logger.info("\n" + "=" * 60)

    logger.info("\n📋 创建任务...\n")

    # 创建一些任务
    tasks_data = [
        {
            "title": "将第一章翻译为英文",
            "description": "将有声书的第一章从中文翻译为英文，保持原文风格和情感基调。",
            "assignee_id": member_ids[0],  # 张译文
            "reporter_id": member_ids[3],  # 赵经理
            "tags": ["translation", "chapter-1", "en-US"],
            "priority": 4,
            "estimated_hours": 5.0,
        },
        {
            "title": "录制第一章英文旁白",
            "description": "为第一章的英文翻译录制旁白音轨。",
            "assignee_id": member_ids[1],  # 李音工
            "reporter_id": member_ids[0],  # 张译文 (翻译完成后交给配音)
            "tags": ["narration", "chapter-1", "en-US"],
            "priority": 3,
            "estimated_hours": 3.0,
        },
        {
            "title": "审校第一章英文翻译",
            "description": "检查第一章英文翻译的准确性、流畅性和风格一致性。",
            "assignee_id": member_ids[2],  # 王编辑
            "reporter_id": member_ids[0],  # 张译文
            "tags": ["proofreading", "chapter-1", "en-US"],
            "priority": 4,
            "estimated_hours": 2.0,
        },
        {
            "title": "制作第一章试听样本",
            "description": "将翻译和配音后的第一章制作成试听样本供团队审阅。",
            "assignee_id": member_ids[1],  # 李音工
            "reporter_id": member_ids[2],  # 王编辑
            "tags": ["production", "sample", "chapter-1"],
            "priority": 3,
            "estimated_hours": 1.5,
        },
    ]

    task_ids = []
    for task_data in tasks_data:
        task = Task(
            id="",
            title=task_data["title"],
            description=task_data["description"],
            status=TaskStatus.TODO,
            assignee_id=task_data["assignee_id"],
            reporter_id=task_data["reporter_id"],
            tags=task_data["tags"],
            priority=task_data["priority"],
            estimated_hours=task_data["estimated_hours"],
        )
        task_id = collab_manager.add_task(task)
        task_ids.append(task_id)
        logger.info(f"   ✅ 创建任务: {task.title}")
        logger.info(
            f"      负责人: {collab_manager.team_members[task.assignee_id].name if task.assignee_id else '未分配'}"
        )
        logger.info(f"      优先级: {task.priority}/5")
        logger.info(f"      估算工时: {task.estimated_hours} 小时")

    logger.info(f"\n📊 任务总数: {len(collab_manager.tasks)}")

    logger.info("\n" + "=" * 60)

    logger.info("\n💬 添加评论和讨论...\n")

    # 为任务添加一些评论
    comments_data = [
        {
            "task_id": task_ids[0],  # 翻译任务
            "content": "我在翻译的时候发现《三体》中有些科幻概念很难直译，可能需要加注或者使用意译。例如『智子』这个概念，直接翻译为 'Sophon' 可能让西方读者不太理解其含义。",
            "comment_type": CommentType.SUGGESTION,
            "author_id": member_ids[0],  # 张译文
        },
        {
            "task_id": task_ids[0],  # 翻译任务
            "content": "建议我们保留原文『智子』，并在注释或制作特别的音频注释来解释其含义。这样既保持了原著的风格，又帮助了听众理解。",
            "comment_type": CommentType.COMMENT,
            "author_id": member_ids[2],  # 王编辑
        },
        {
            "task_id": task_ids[1],  # 配音任务
            "content": "我已经查看了翻译稿，准备开始录音。建议旁白的语速稍微快一点，因为英文表达通常比中文简洁。",
            "comment_type": CommentType.COMMENT,
            "author_id": member_ids[1],  # 李音工
        },
        {
            "task_id": task_ids[2],  # 审校任务
            "content": "我发现第3段有一处翻译错误：原文说『宇宙的黑暗森林假设』被翻译成了『宇宙的黑森林假设』，漏掉了『的』字。",
            "comment_type": CommentType.ISSUE,
            "author_id": member_ids[2],  # 王编辑
        },
    ]

    comment_ids = []
    for comment_data in comments_data:
        comment = Comment(
            id="",
            content=comment_data["content"],
            author_id=comment_data["author_id"],
            comment_type=comment_data["comment_type"],
            task_id=comment_data["task_id"],
        )
        comment_id = collab_manager.add_comment(comment)
        comment_ids.append(comment_id)
        logger.info(
            f"   ✅ 添加评论: [{comment_data['comment_type'].value}] {comment_data['content'][:30]}..."
        )

    logger.info(f"\n💬 评论总数: {len(collab_manager.comments)}")

    logger.info("\n" + "=" * 60)

    logger.info("\n📋 更新任务状态...\n")

    # 更新一些任务状态
    status_updates = [
        (task_ids[0], TaskStatus.IN_PROGRESS, member_ids[0]),  # 张译文开始翻译
        (task_ids[0], TaskStatus.REVIEW, member_ids[2]),  # 王评开始审校翻译
        (task_ids[0], TaskStatus.DONE, member_ids[2]),  # 翻译完成审校
        (task_ids[1], TaskStatus.IN_PROGRESS, member_ids[1]),  # 李音工开始录音
    ]

    for task_id, new_status, updater_id in status_updates:
        success = collab_manager.update_task_status(task_id, new_status, updater_id)
        if success:
            updater_name = collab_manager.team_members[updater_id].name
            task_title = collab_manager.tasks[task_id].title
            logger.info(
                f"   ✅ {updater_name} 将任务 '{task_title}' 状态更新为 {new_status.value}"
            )
        else:
            logger.error("   ❌ 更新任务状态失败")

    logger.info("\n" + "=" * 60)

    logger.info("\n📋 创建审批请求...\n")

    # 创建一个审批请求（例如，翻译完成后需要经理审批）
    approval_id = collab_manager.create_approval_request(
        title="批准第一章英文翻译发布",
        description="请审批第一章的英文翻译，确认可以进入配音阶段。",
        requester_id=member_ids[2],  # 王编辑 (翻译完成后请求审批)
        approver_ids=[member_ids[3]],  # 赵经理 (需要经理批准)
        task_id=task_ids[0],  # 关联到翻译任务
        artifact_path="./translations/chapter_01_en.txt",
    )
    logger.info("   ✅ 创建审批请求: '批准第一章英文翻译发布'")
    logger.info(f"      请求人: {collab_manager.team_members[member_ids[2]].name}")
    logger.info(f"      审批人: {collab_manager.team_members[member_ids[3]].name}")

    logger.info("\n" + "=" * 60)

    logger.info("\n📋 处理审批响应...\n")

    # 模拟审批响应
    approval_request = collab_manager.approval_requests[approval_id]
    approver_id = approval_request.approver_ids[0]  # 赵经理

    # 经理批准了请求
    success = collab_manager.respond_to_approval(
        approval_id,
        approver_id,
        ApprovalStatus.APPROVED,
        "翻译质量很好，可以进入配音阶段。建议在配音时注意语速和停顿。",
    )
    if success:
        approver_name = collab_manager.team_members[approver_id].name
        logger.info(f"   ✅ {approver_name} 批准了审批请求")
        logger.info(
            f"      批注: '翻译质量很好，可以进入配音阶段。建议在配音时注意语速和停顿。'"
        )
    else:
        logger.error("   ❌ 处理审批响应失败")

    logger.info("\n" + "=" * 60)

    logger.info("\n📊 查看协作统计信息...\n")

    stats = collab_manager.get_collaboration_stats()
    logger.info(
        f"👥 团队成员: {stats['team_members']} 人 (活跃: {stats['active_members']})"
    )
    logger.info(f"📋 任务总数: {stats['total_tasks']}")
    for status, count in stats["tasks_by_status"].items():
        if count > 0:
            logger.info(f"   - {status}: {count}")
    logger.info(f"💬 评论总数: {stats['total_comments']}")
    for ctype, count in stats["comments_by_type"].items():
        if count > 0:
            logger.info(f"   - {ctype}: {count}")
    logger.info(f"📋 审批请求总数: {stats['total_approval_requests']}")
    for status, count in stats["approvals_by_status"].items():
        if count > 0:
            logger.info(f"   - {status}: {count}")

    logger.info("\n" + "=" * 60)

    logger.info("\n📜 查看最近的变更历史...\n")

    recent_changes = collab_manager.get_recent_changes(10)
    logger.info(f"最近 {len(recent_changes)} 条变更记录:")
    for change in recent_changes:
        changer_name = "未知"
        if change.changed_by in collab_manager.team_members:
            changer_name = collab_manager.team_members[change.changed_by].name
        logger.info(
            f"   [{change.changed_at.strftime('%H:%M:%S')}] {changer_name} {change.description}"
        )

    logger.info("\n" + "=" * 60)

    logger.info("\n🎯 查看特定任务的详细信息...\n")

    # 查看第一章翻译任务的详情
    translation_task = collab_manager.tasks[task_ids[0]]
    logger.info(f"任务: {translation_task.title}")
    logger.info(f"   状态: {translation_task.status.value}")
    logger.info(
        f"   负责人: {collab_manager.team_members[translation_task.assignee_id].name if translation_task.assignee_id else '未分配'}"
    )
    logger.info(
        f"   创建时间: {translation_task.created_at.strftime('%Y-%m-%d %H:%M')}"
    )
    logger.info(
        f"   更新时间: {translation_task.updated_at.strftime('%Y-%m-%d %H:%M')}"
    )
    logger.info(f"   标签: {', '.join(translation_task.tags)}")
    logger.info(f"   优先级: {translation_task.priority}/5")
    if translation_task.estimated_hours:
        logger.info(f"   估算工时: {translation_task.estimated_hours} 小时")

    # 查看该任务的评论
    task_comments = collab_manager.get_task_comments(task_ids[0])
    logger.info(f"\n   评论 ({len(task_comments)} 条):")
    for comment in task_comments:
        author_name = (
            collab_manager.team_members[comment.author_id].name
            if comment.author_id in collab_manager.team_members
            else "未知"
        )
        logger.info(
            f"      [{comment.comment_type.value}] {author_name}: {comment.content[:50]}..."
        )

    # 查看该任务的审批请求
    task_approvals = collab_manager.get_approval_requests_for_task(task_ids[0])
    logger.info(f"\n   审批请求 ({len(task_approvals)} 项):")
    for approval in task_approvals:
        requester_name = (
            collab_manager.team_members[approval.requester_id].name
            if approval.requester_id in collab_manager.team_members
            else "未知"
        )
        logger.info(
            f"      '{approval.title}' (请求人: {requester_name}, 状态: {approval.status.value})"
        )
        if approval.approvals:
            for approver_id, response in approval.approvals.items():
                approver_name = (
                    collab_manager.team_members[approver_id].name
                    if approver_id in collab_manager.team_members
                    else "未知"
                )
                logger.info(f"         - {approver_name}: {response.status.value}")

    logger.info("\n" + "=" * 60)
    logger.info("🎉 团队协作系统演示完成")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
