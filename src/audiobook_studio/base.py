import logging
import threading
import traceback
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, TypeVar

T = TypeVar("T")


# --- 1. 新增错误等级枚举 ---
class ErrorSeverity(Enum):
    TRANSIENT = "transient"  # 瞬时错误，建议重试
    FATAL = "fatal"  # 致命错误，停止该任务


class AgentCapability(Enum):
    TEXT_EXTRACTION = "extract"
    STRUCTURE_ANALYSIS = "analyze"
    TTS_SYNTHESIS = "synthesize"
    QUALITY_CONTROL = "quality_check"
    FEEDBACK_LEARNING = "learn"


@dataclass
class AgentContext:
    task_id: str
    book_id: str
    current_stage: str
    shared_knowledge: Dict[str, Any]
    retry_count: int = 0


@dataclass
class AgentMessage:
    sender: str
    content: Dict[str, Any]
    requires_response: bool = False


class AbstractAgent:
    def __init__(self, capabilities: List[AgentCapability]):
        self.agent_id = f"{self.__class__.__name__}-{str(uuid.uuid4())[:8]}"
        self.capabilities = capabilities
        self.context: Optional[AgentContext] = None
        self.message_queue: List[AgentMessage] = []
        self.lock = threading.Lock()
        self.logger = logging.getLogger(self.agent_id)

    # --- 2. 优化：防爆的消息处理循环 ---
    def receive_message(self, message: AgentMessage) -> None:
        with self.lock:
            self.message_queue.append(message)

    def process_messages(self) -> None:
        while True:
            msg = None
            with self.lock:
                if not self.message_queue:
                    break
                msg = self.message_queue.pop(0)

            try:
                self._handle_message(msg)
            except Exception as e:
                # 捕获处理逻辑中的所有异常
                self._handle_failure(e, severity=ErrorSeverity.FATAL)

    def _handle_message(self, message: AgentMessage) -> None:
        raise NotImplementedError

    # --- 3. 增强：更智能的错误处理 ---
    def _handle_failure(
        self, error: Exception, severity: ErrorSeverity = ErrorSeverity.FATAL
    ) -> None:
        """增强的错误处理：记录堆栈、分类级别，并上报"""
        error_msg = f"Agent {self.agent_id} failed: {str(error)}"
        self.logger.error(error_msg)
        self.logger.error(traceback.format_exc())  # 记录完整堆栈

        # 这里可以调用 Orchestrator 的状态更新接口
        # 为了解耦，我们保持现有逻辑，但增加了 severity 参数供后续扩展
        if severity == ErrorSeverity.FATAL:
            self.logger.warning("Fatal error encountered, cleaning up resources...")
            # 可以在此执行 Agent 级别的清理工作

    def acquire_context(self, context: Optional[AgentContext] = None) -> None:
        self.context = context

    def can_handle(self, capability: AgentCapability) -> bool:
        return capability in self.capabilities

    def send_message(self, message: AgentMessage) -> None:
        """Send a message to another agent."""
        with self.lock:
            self.message_queue.append(message)

    def get_agent_id(self) -> str:
        """Return the agent ID."""
        return self.agent_id
