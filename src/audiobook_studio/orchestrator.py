orchestrator = Orchestrator()

task_id = orchestrator.dispatch_task(
    AgentCapability.TEXT_EXTRACTION,
    {
        "book_id": "book-001",
        "file_path": "input/book.pdf"
    }
)
