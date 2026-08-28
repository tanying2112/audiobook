"""SQLAlchemy 2.0 ORM ORM models for Audiobook Studio (HARNESS 规范对齐版).

核心实体 (Project -> Chapter -> Paragraph -> AudioSegment):
- Project: 书籍项目 (上帝视角完整档案)
- Character: 角色声音绑定
- EmotionSnapshot: 章节情感快照
- Chapter: 章节元数据 + 处理状态
- Paragraph: 段落完整标注 + 编辑 + 路由 + 质检 (宽表设计)
- AudioSegment: 音频片段 (版本控制、增量合成)
- TTSEdit: 编辑历史版本
- Routing: TTS 路由决策历史
- Quality: 质检记录
- FeedbackRecord: 反馈记录 (自我迭代核心)
- ProcessingRun: 管线运行记录 (版本追踪与回滚)
- User: 用户认证模型
- Role: RBAC 角色模型
- Permission: RBAC 权限模型
- ProjectPermission: 项目级权限模型
- TeamMember: 团队成员模型
- Comment: 评论模型
- Task: 任务模型
- ApprovalRequest: 审批请求模型
- ApprovalResponse: 审批响应模型
- ChangeRecord: 变更记录模型
"""

from .agent import AgentKnowledge, TaskRecord
from .audio_segment import AudioSegment
from .book import Project
from .chapter import Chapter
from .character import Character

# ---------------------------------------------------------------------------
# 协作模块: collaboration.py 现已并入主干(已被 git 跟踪), 恢复导入以注册所有
# 协作表(含新增的 CollaborationRecord 聚合表)到 Base.metadata。
# 恢复条件已满足(见原 TECH-DEBT 注释: collaboration.py 合并进主干后恢复)。
# ---------------------------------------------------------------------------
from .collaboration import (
    ApprovalRequest,
    ApprovalResponse,
    ChangeRecord,
    CollaborationRecord,
    Comment,
    Task,
    TeamMember,
)
from .emotion_snapshot import EmotionSnapshot
from .feedback_record import FeedbackRecord
from .legacy import (
    LegacyBook,
    LegacyParagraph,
    LegacyTTSEdit,
    LegacyRouting,
    LegacyQuality,
)
from .paragraph import Paragraph
from .processing_run import ProcessingRun
from .project_segment import ProjectSegment
from .publish import PublishHistory, PublishJob
from .publish_job import PublishJobState
from .quality import Quality
from .routing import Routing
from .tts_edit import TTSEdit
from .user import Permission, ProjectPermission, Role, User

__all__ = [
    "Project",
    "Character",
    "EmotionSnapshot",
    "Chapter",
    "Paragraph",
    "AudioSegment",
    "TTSEdit",
    "Routing",
    "Quality",
    "FeedbackRecord",
    "ProcessingRun",
    "AgentKnowledge",
    "TaskRecord",
    "User",
    "Role",
    "Permission",
    "ProjectPermission",
    "ProjectSegment",
    "PublishHistory",
    "PublishJob",
    "PublishJobState",
    "LegacyBook",
    "LegacyParagraph",
    "LegacyTTSEdit",
    "LegacyRouting",
    "LegacyQuality",
    "TeamMember",
    "Comment",
    "Task",
    "ApprovalRequest",
    "ApprovalResponse",
    "ChangeRecord",
    "CollaborationRecord",
]
