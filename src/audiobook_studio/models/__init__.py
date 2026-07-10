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
# TECH-DEBT: 协作模块导入暂时移除 (feature/sprint-l-infrastructure 分支)
# ---------------------------------------------------------------------------
# 原始代码于此处执行:
#     from .collaboration import (
#         ApprovalRequest, ApprovalResponse, ChangeRecord, Comment, Task, TeamMember,
#     )
# 并在 __all__ 中导出上述 6 个符号。
#
# 移除原因: 干净主干 HEAD(ff4ee0b) 并未提交 src/audiobook_studio/models/collaboration.py
# ——该文件当前仅为未跟踪的工作区文件,属于 feat/collab-module 分支的工作产物。
# 此悬空导入会使 `import audiobook_studio.models` 抛出 ModuleNotFoundError,
# 进而阻断 tests/unit/utils/ 下所有测试的收集(env_checker / secure_subprocess 等)。
# 这是 Agent B 为完成"加固后方基建"任务所做的最小解锁修复,刻意不触碰 tts/ 与 pipeline/。
#
# 恢复条件(交由协作模块负责人执行):
#   当 collaboration.py 通过 feat/collab-module 正式合并进主干后,
#   请在此处恢复上述 from .collaboration import (...) 语句,
#   并在下方 __all__ 中补回对应符号:
#     "TeamMember", "Comment", "Task",
#     "ApprovalRequest", "ApprovalResponse", "ChangeRecord"
#
# 追踪: 见项目记忆 collab-feature-completion。
# ---------------------------------------------------------------------------
from .emotion_snapshot import EmotionSnapshot
from .feedback_record import FeedbackRecord
from .paragraph import Paragraph
from .processing_run import ProcessingRun
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
]
