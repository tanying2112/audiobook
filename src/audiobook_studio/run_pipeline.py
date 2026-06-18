import logging
import time
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

from .database import engine, Base, SessionLocal
from .models import TaskRecord
from .orchestrator import Orchestrator, AgentCapability

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("pipeline")

def create_mock_files():
    """Create mock text files if they don't exist"""
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    
    # Create Chinese mock file
    ch_file = data_dir / "hongloumeng.txt"
    if not ch_file.exists():
        ch_file.write_text("""红楼梦第一回：甄士隐梦幻识通灵 贾雨村风尘怀闺秀

此开卷第一回也。作者自云：因曾历过一番梦幻之后，故将真事隐去，而借"通灵"之说，撰此《石头记》一书也。故曰"甄士隐"云云。""", encoding="utf-8")
    
    # Create English mock file
    en_file = data_dir / "sanguoyanyi.txt"
    if not en_file.exists():
        en_file.write_text("""Romance of the Three Kingdoms - Chapter 1

The empire, long divided, must unite; long united, must divide. Thus it has ever been. 
In the closing years of the Zhou Dynasty, seven kingdoms warred among themselves...""", encoding="utf-8")

def initialize_database():
    """Initialize database tables"""
    logger.info("Initializing database tables...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialized successfully")

def create_tasks(orchestrator: Orchestrator) -> Dict[str, Dict[str, Any]]:
    """Create and dispatch initial tasks for both books"""
    tasks = {}
    
    # Task 1: 红楼梦 (Chinese)
    hongloumeng_task = orchestrator.dispatch_task(
        AgentCapability.TEXT_EXTRACTION,
        {
            "file_path": "data/hongloumeng.txt",
            "mime_type": "text/plain",
            "lang": "zh",
            "book_id": "hongloumeng"
        }
    )
    tasks[hongloumeng_task] = {"name": "红楼梦", "lang": "zh"}
    
    # Task 2: 三国演义 (English)
    sanguoyanyi_task = orchestrator.dispatch_task(
        AgentCapability.TEXT_EXTRACTION,
        {
            "file_path": "data/sanguoyanyi.txt",
            "mime_type": "text/plain",
            "lang": "en",
            "voice_params": {"lang": "en"},
            "book_id": "sanguoyanyi"
        }
    )
    tasks[sanguoyanyi_task] = {"name": "三国演义", "lang": "en"}
    
    return tasks

def run_pipeline():
    """Main pipeline execution"""
    initialize_database()
    
    orchestrator = Orchestrator()
    tasks = create_tasks(orchestrator)
    
    logger.info("Starting pipeline execution...")
    start_time = datetime.now()
    
    # Create mock files if they don't exist
    create_mock_files()
    
    while True:
        # Process messages for all agents
        for agent in orchestrator.agents.values():
            if agent.message_queue:
                logger.info(f"Processing messages for {agent.agent_id}")
                agent.process_messages()
        
        # Check task status from database
        db = SessionLocal()
        try:
            completed_tasks = 0
            failed_tasks = []
            
            for task_id in tasks.keys():
                task_record = db.query(TaskRecord).filter_by(id=task_id).first()
                if task_record and task_record.status in ("COMPLETED", "FAILED"):
                    completed_tasks += 1
                    if task_record.status == "FAILED":
                        failed_tasks.append(task_id)
            
            if completed_tasks == len(tasks):
                break
        finally:
            db.close()
            
        # Sleep to prevent busy waiting
        time.sleep(1)
    
    # Print final results
    duration = (datetime.now() - start_time).total_seconds()
    logger.info(f"Pipeline completed in {duration:.2f} seconds")
    
    db = next(get_db())
    for task_id, task_info in tasks.items():
        task_record = db.query(TaskRecord).filter_by(id=task_id).first()
        if task_record:
            status = task_record.status
            logger.info(f"Task {task_id[:8]}... ({task_info['name']}) - Status: {status}")
            if status == "FAILED" and task_record.output_data:
                logger.info(f"  Error: {task_record.output_data.get('error')}")
                logger.info(f"  Error type: {task_record.output_data.get('error_type')}")

if __name__ == "__main__":
    run_pipeline()
