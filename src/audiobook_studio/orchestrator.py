from typing import Dict, List, Optional, TypeVar
from dataclasses import dataclass
from enum import Enum
import threading
import uuid
import logging
from datetime import datetime
from .database import get_db
from .models import TaskRecord

T = TypeVar('T')

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
    shared_knowledge: dict
    
@dataclass
class AgentMessage:
    sender: str
    content: dict
    requires_response: bool = False

class AbstractAgent:
    def __init__(self, capabilities: List[AgentCapability]):
        self.agent_id = f"{self.__class__.__name__}-{str(uuid.uuid4())[:8]}"
        self.capabilities = capabilities
        self.context: Optional[AgentContext] = None
        self.message_queue = []
        self.lock = threading.Lock()
        self.logger = logging.getLogger(self.agent_id)
        
    def receive_message(self, message: AgentMessage):
        with self.lock:
            self.message_queue.append(message)
        
    def process_messages(self):
        while self.message_queue:
            msg = self.message_queue.pop(0)
            self._handle_message(msg)
            
    def _handle_message(self, message: AgentMessage):
        raise NotImplementedError
            
    def acquire_context(self, context: AgentContext):
        self.context = context
        
    def can_handle(self, capability: AgentCapability) -> bool:
        return capability in self.capabilities
        
    def _handle_failure(self, error: Exception):
        """Common error handling for all agents"""
        db = next(get_db())
        task_record = db.query(TaskRecord).filter_by(id=self.context.task_id).first()
        if task_record:
            task_record.status = "FAILED"
            task_record.output_data = {
                'error': str(error),
                'error_type': type(error).__name__
            }
            task_record.completed_at = datetime.utcnow()
            db.commit()
        self.logger.error(f"Task failed: {error}", exc_info=True)

class Orchestrator:
    def __init__(self):
        self.agents: Dict[str, AbstractAgent] = {}
        self.task_registry = {}
        self._register_core_agents()
        
    def _register_core_agents(self):
        """Register essential agents for audiobook production"""
        from .pipeline.agents import (
            ExtractAgent, AnalyzeAgent,
            SynthesizeAgent, QualityAgent
        )
        self.register_agent(ExtractAgent())
        self.register_agent(AnalyzeAgent())
        self.register_agent(SynthesizeAgent())
        self.register_agent(QualityAgent())
        
    def register_agent(self, agent: AbstractAgent):
        self.agents[agent.agent_id] = agent
                        
    def dispatch_task(self, task_type: AgentCapability, payload: dict) -> str:
        """Route tasks to capable agents with load balancing"""
        task_id = str(uuid.uuid4())
        
        capable_agents = [
            a for a in self.agents.values() 
            if a.can_handle(task_type)
        ]
        
        if not capable_agents:
            raise ValueError(f"No agents available for {task_type}")
            
        # TODO: Add sophisticated routing logic
        selected_agent = capable_agents[0]
        
        context = AgentContext(
            task_id=task_id,
            book_id=payload.get('book_id', ''),
            current_stage=task_type.value,
            shared_knowledge={}
        )
        
        selected_agent.acquire_context(context)
        selected_agent.receive_message(AgentMessage(
            sender="orchestrator",
            content=payload
        ))
        
        self.task_registry[task_id] = {
            'status': 'pending',
            'assigned_agent': selected_agent.agent_id
        }
        
        return task_id
    
    def monitor_tasks(self):
        """Background task monitoring and recovery"""
        # TODO: Implement health checks and retry logic
        pass
