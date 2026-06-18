from typing import Optional
from datetime import datetime
from sqlalchemy import Column, String, JSON, DateTime
from .database import Base

class AgentKnowledge(Base):
    """Centralized knowledge base for agent collaboration"""
    __tablename__ = "agent_knowledge"
    
    id = Column(String, primary_key=True)
    topic = Column(String, index=True)
    knowledge = Column(JSON)  # Structured domain knowledge
    source_agent = Column(String)
    confidence_score = Column(JSON)  # {'score': 0.9, 'factors': [...]}
    created_at = Column(DateTime, default=datetime.utcnow)
    last_accessed = Column(DateTime)

class TaskRecord(Base):
    """Audit trail for all agent operations"""
    __tablename__ = "agent_tasks"
    
    id = Column(String, primary_key=True)
    task_type = Column(String)
    input_data = Column(JSON)
    output_data = Column(JSON, nullable=True)
    assigned_agent = Column(String)
    status = Column(String)  # pending/running/completed/failed
    retries = Column(JSON)  # List of retry attempts
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    @property
    def duration(self) -> Optional[float]:
        if self.completed_at:
            return (self.completed_at - self.created_at).total_seconds()
        return None
