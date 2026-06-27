"""
Mock Router for Frontend Offline Development

Provides mock endpoints returning static JSON files for frontend development
without requiring backend business logic to be implemented.

Usage:
  Frontend configures baseUrl: '/api/mock' during development.
  All requests are served from static/mock/*.json files.

SSE streaming endpoints (chat-edit / chat-annotate) are defined inline and
generate fake token-by-token output to validate the frontend typewriter effect.
"""

import asyncio
import json
import logging
import random
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mock", tags=["mock"])

# Mock data directory
MOCK_DIR = Path(__file__).parent.parent / "static" / "mock"


def _load_mock_data(filename: str) -> Dict[str, Any]:
    """Load mock JSON data from file."""
    filepath = MOCK_DIR / filename
    if not filepath.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Mock data file not found: {filename}. Please create it in {MOCK_DIR}"
        )

    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────────────────────────────────────────────────────────────
# Mock Endpoints (mirroring real API structure)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/projects")
async def mock_list_projects():
    """Mock: List all projects."""
    data = _load_mock_data("projects.json")
    return JSONResponse(content=data)


@router.get("/projects/{project_id}")
async def mock_get_project(project_id: int):
    """Mock: Get single project details."""
    data = _load_mock_data(f"project-{project_id}.json")
    return JSONResponse(content=data)


@router.get("/projects/{project_id}/chapters")
async def mock_list_chapters(project_id: int):
    """Mock: List chapters for a project."""
    data = _load_mock_data(f"project-{project_id}-chapters.json")
    return JSONResponse(content=data)


@router.get("/projects/{project_id}/paragraphs")
async def mock_list_paragraphs(project_id: int, chapter_id: int = None, skip: int = 0, limit: int = 100):
    """Mock: List paragraphs with pagination."""
    if chapter_id:
        data = _load_mock_data(f"project-{project_id}-chapter-{chapter_id}-paragraphs.json")
    else:
        data = _load_mock_data(f"project-{project_id}-paragraphs.json")

    # Apply pagination
    items = data.get("items", [])
    paginated = items[skip:skip+limit]

    return JSONResponse(content={
        "items": paginated,
        "total": len(items),
        "skip": skip,
        "limit": limit,
    })


@router.get("/paragraphs/{paragraph_id}/detail")
async def mock_get_paragraph_detail(paragraph_id: int):
    """Mock: Get paragraph with full embedded data (P0-5 endpoint)."""
    data = _load_mock_data(f"paragraph-{paragraph_id}-detail.json")
    return JSONResponse(content=data)


@router.get("/projects/{project_id}/templates")
async def mock_list_templates(project_id: int, pending_only: bool = False):
    """Mock: List templates for project."""
    if pending_only:
        data = _load_mock_data(f"project-{project_id}-templates-pending.json")
    else:
        data = _load_mock_data(f"project-{project_id}-templates.json")
    return JSONResponse(content=data)


@router.get("/projects/{project_id}/auto-run/status")
async def mock_auto_run_status(project_id: int, run_id: str = None):
    """Mock: Get auto-run pipeline status."""
    data = _load_mock_data(f"project-{project_id}-autorun-status.json")
    if run_id:
        data["run_id"] = run_id
    return JSONResponse(content=data)


@router.get("/harness/status")
async def mock_harness_status():
    """Mock: HARNESS self-iteration status."""
    data = _load_mock_data("harness-status.json")
    return JSONResponse(content=data)


@router.get("/harness/dashboard")
async def mock_harness_dashboard():
    """Mock: Complete HARNESS dashboard."""
    data = _load_mock_data("harness-dashboard.json")
    return JSONResponse(content=data)


@router.get("/golden/samples")
async def mock_golden_samples(stage: str = None):
    """Mock: Browse golden samples."""
    if stage:
        data = _load_mock_data(f"golden-samples-{stage}.json")
    else:
        data = _load_mock_data("golden-samples.json")
    return JSONResponse(content=data)


@router.get("/llm/voices")
async def mock_tts_voices():
    """Mock: TTS voice enumeration."""
    data = _load_mock_data("tts-voices.json")
    return JSONResponse(content=data)


@router.get("/export/jobs")
async def mock_export_jobs():
    """Mock: List export jobs."""
    data = _load_mock_data("export-jobs.json")
    return JSONResponse(content=data)


# ─────────────────────────────────────────────────────────────────────────────
# SSE Streaming Endpoints (对话式编辑 / 标注)
# 用于验证前端 sse.ts 打字机效果。事件格式: data: {...}\n\n
# ⚠️ 必须定义在 catch-all 路由之前，否则会被 /{path:path} 拦截。
# ─────────────────────────────────────────────────────────────────────────────


class ChatEditRequest(BaseModel):
    """对话式编辑请求（与前端 sse.ts 的 ChatEditRequest 对齐）."""

    project_id: int = Field(..., description="项目 ID")
    chapter_index: int = Field(..., ge=1, description="章节索引")
    paragraph_index: int = Field(..., ge=0, description="段落索引")
    target_stage: str = Field(default="edit", description="目标阶段: edit/annotate")
    intent: str = Field(..., min_length=1, description="用户编辑意图")
    conversation_history: List[dict] = Field(
        default_factory=list, description="历史对话"
    )
    annotation_context: Optional[dict] = Field(
        default=None, description="段落标注上下文"
    )
    shortcut: Optional[str] = Field(default=None, description="快捷指令")


class ChatAnnotateRequest(BaseModel):
    """对话式标注请求."""

    project_id: int = Field(..., description="项目 ID")
    chapter_index: int = Field(..., ge=1, description="章节索引")
    paragraph_index: int = Field(..., ge=0, description="段落索引")
    intent: str = Field(..., min_length=1, description="用户标注意图")
    conversation_history: List[dict] = Field(default_factory=list)
    current_annotation: Optional[dict] = Field(default=None)


# 预设编辑范本库：覆盖口语化/书面化/敏感词/长句拆分/数字归一化
_MOCK_EDIT_LIBRARY: List[dict] = [
    {
        "keywords": ["口语", "colloquial", "自然"],
        "before": "他对此表示非常愤怒，并表示绝对不会接受这样的安排。",
        "after": "他气坏了，说这事儿他绝对不答应。",
        "changes_made": ["书面转口语", "简化长句", "去除书面连接词"],
        "rationale": "将书面化表达转为口语，更符合 TTS 朗读的自然节奏。",
        "confidence": 0.92,
        "pattern": "text_formal",
    },
    {
        "keywords": ["书面", "formal", "正式"],
        "before": "这事儿太离谱了，我真的不想再说了。",
        "after": "此事颇为荒谬，我无意再多作陈述。",
        "changes_made": ["口语转书面", "用词正式化"],
        "rationale": "将口语化表达转为书面语，匹配严肃叙事的文风。",
        "confidence": 0.88,
        "pattern": "text_colloquial",
    },
    {
        "keywords": ["敏感", "sensitive", "删除", "remove"],
        "before": "他喝了三瓶茅台后开始胡言乱语。",
        "after": "他饮酒过量后开始语无伦次。",
        "changes_made": ["敏感品牌词替换", "酒精相关表达泛化"],
        "rationale": "移除具体酒类品牌，避免广告嫌疑与敏感内容。",
        "confidence": 0.95,
        "pattern": "sensitive_content",
    },
    {
        "keywords": ["拆分", "split", "长句", "断句"],
        "before": "当他走进那个堆满了旧书和积满灰尘的木架子之间的小房间的时候，他忽然想起了小时候在爷爷书房里度过的那些漫长而宁静的下午。",
        "after": "他走进那个堆满旧书的小房间。木架子上积满了灰尘。他忽然想起，小时候在爷爷书房里度过的那些漫长而宁静的下午。",
        "changes_made": ["长句拆分（>50字）", "每句≤30字", "标点优化"],
        "rationale": "原句 68 字过长，TTS 朗读易产生韵律断裂，拆分为短句提升自然度。",
        "confidence": 0.90,
        "pattern": "pacing_issue",
    },
    {
        "keywords": ["数字", "number", "归一化", "normalize"],
        "before": "他在1985年花了贰佰叁拾元买了3本书。",
        "after": "他在 1985 年花了 230 元买了 3 本书。",
        "changes_made": ["中文数字转阿拉伯数字", "数字两侧加空格"],
        "rationale": "统一数字格式为阿拉伯数字，便于 TTS 引擎正确朗读。",
        "confidence": 0.94,
        "pattern": "formatting_error",
    },
]

_DEFAULT_EDIT = _MOCK_EDIT_LIBRARY[0]


def _pick_edit_template(intent: str) -> dict:
    """根据 intent 关键词匹配编辑范本."""
    intent_lower = intent.lower()
    for template in _MOCK_EDIT_LIBRARY:
        if any(kw.lower() in intent_lower for kw in template["keywords"]):
            return template
    return _DEFAULT_EDIT


def _tokenize_for_streaming(text: str) -> List[str]:
    """把文本切成 token 片段用于打字机效果.

    中文按 1-3 字、英文按单词、标点单独成片，模拟真实 LLM token 输出节奏。
    """
    tokens: List[str] = []
    buffer = ""
    for char in text:
        buffer += char
        # 英文/数字连续字符累积成词
        if char.isalnum() or char in "'-":
            continue
        if buffer.strip():
            tokens.append(buffer)
            buffer = ""
        elif buffer:
            tokens.append(buffer)
            buffer = ""
    if buffer:
        tokens.append(buffer)
    return tokens


def _sse(payload: Any) -> str:
    """格式化 SSE 事件行."""
    data = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return f"data: {data}\n\n"


def _segment_id(project_id: int, chapter_index: int, paragraph_index: int) -> str:
    """构造 segment_id: {book}_ch{chapter}_p{paragraph}."""
    return f"{project_id}_ch{chapter_index}_p{paragraph_index}"


async def _chat_edit_generator(req: ChatEditRequest) -> AsyncGenerator[str, None]:
    """模拟 LLM 打字机流式输出.

    事件序列:
      1. thinking  → LLM 思考提示
      2. token *   → 逐 token 输出编辑理由（打字机）
      3. suggestion → 完整编辑建议
      4. [DONE]    → 结束
    """
    template = _pick_edit_template(req.intent)
    message_id = str(uuid.uuid4())

    yield _sse({"type": "thinking", "message_id": message_id})
    await asyncio.sleep(random.uniform(0.2, 0.5))

    for token in _tokenize_for_streaming(template["rationale"]):
        yield _sse({"type": "token", "content": token, "message_id": message_id})
        await asyncio.sleep(random.uniform(0.02, 0.08))

    await asyncio.sleep(0.1)

    suggestion = {
        "kind": "text_edit",
        "paragraph_id": _segment_id(req.project_id, req.chapter_index, req.paragraph_index),
        "before": {"text": template["before"]},
        "after": {"text": template["after"]},
        "changes_made": template["changes_made"],
        "confidence": template["confidence"],
        "rationale": template["rationale"],
        "pattern_tag": template["pattern"],
    }
    yield _sse({"type": "suggestion", "suggestion": suggestion, "message_id": message_id})
    await asyncio.sleep(0.1)

    yield _sse({"type": "done", "message_id": message_id})
    yield _sse("[DONE]")


_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲，保证流式实时性
}


@router.post("/llm/chat-edit")
async def mock_chat_edit(req: ChatEditRequest):
    """模拟对话式文本编辑的 SSE 流式响应."""
    logger.info(
        "[mock] chat-edit: project=%s ch=%s p=%s intent=%r",
        req.project_id, req.chapter_index, req.paragraph_index, req.intent,
    )
    return StreamingResponse(
        _chat_edit_generator(req),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.post("/llm/chat-annotate")
async def mock_chat_annotate(req: ChatAnnotateRequest):
    """模拟对话式标注的 SSE 流式响应."""

    async def gen() -> AsyncGenerator[str, None]:
        message_id = str(uuid.uuid4())
        yield _sse({"type": "thinking", "message_id": message_id})
        await asyncio.sleep(0.3)

        rationale = "已根据上下文调整说话人与情感标注，提升角色一致性。"
        for token in _tokenize_for_streaming(rationale):
            yield _sse({"type": "token", "content": token, "message_id": message_id})
            await asyncio.sleep(random.uniform(0.03, 0.07))

        suggestion = {
            "kind": "annotation_adjust",
            "paragraph_id": _segment_id(req.project_id, req.chapter_index, req.paragraph_index),
            "before": {
                "speaker_canonical_name": "unknown",
                "emotion": "neutral",
                "emotion_intensity": 0.5,
            },
            "after": {
                "speaker_canonical_name": "张三",
                "emotion": "angry",
                "emotion_intensity": 0.8,
            },
            "changes_made": ["修正说话人", "情感调整为愤怒", "强度提升至 0.8"],
            "confidence": 0.87,
            "rationale": rationale,
        }
        yield _sse({"type": "suggestion", "suggestion": suggestion, "message_id": message_id})
        await asyncio.sleep(0.1)
        yield _sse({"type": "done", "message_id": message_id})
        yield _sse("[DONE]")

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers=_SSE_HEADERS,
    )


@router.get("/health")
async def mock_health():
    """验证 mock router 是否挂载成功."""
    return {
        "status": "ok",
        "mock_mode": True,
        "timestamp": datetime.utcnow().isoformat(),
        "endpoints": [
            "POST /api/mock/llm/chat-edit",
            "POST /api/mock/llm/chat-annotate",
            "GET /api/mock/health",
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Catch-all for undefined mock endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def mock_catchall(request: Request, path: str):
    """
    Catch-all mock endpoint for any undefined API path.

    Returns a generic mock response with the requested path info.
    Useful for prototyping new endpoints before defining them explicitly.
    """
    method = request.method

    # Log the unhandled mock request for debugging
    logger.info(f"Mock catch-all: {method} /api/mock/{path}")

    # Return generic mock response
    return JSONResponse(
        content={
            "_mock": True,
            "requested_path": f"/api/mock/{path}",
            "method": method,
            "message": f"This is a mock response for {method} {path}. Define this endpoint in static/mock/ for custom data.",
        },
        status_code=200,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Helper to Initialize Mock Data Directory
# ─────────────────────────────────────────────────────────────────────────────

def ensure_mock_directory():
    """Create mock data directory and sample files if they don't exist."""
    MOCK_DIR.mkdir(parents=True, exist_ok=True)

    SAMPLE_FILES = {
        "projects.json": {
            "items": [
                {
                    "id": 1,
                    "title": "示例项目：红楼梦",
                    "author": "曹雪芹",
                    "genre": "古典小说",
                    "difficulty": "B",
                    "status": "processing",
                    "progress": 0.45,
                    "total_cost_usd": 3.50,
                    "created_at": "2026-06-20T10:00:00Z",
                    "updated_at": "2026-06-26T08:30:00Z"
                }
            ],
            "total": 1
        },
        "project-1.json": {
            "id": 1,
            "title": "示例项目：红楼梦",
            "author": "曹雪芹",
            "genre": "古典小说",
            "difficulty": "B",
            "status": "processing",
            "progress": 0.45,
            "total_chapters": 120,
            "completed_chapters": 54,
            "total_cost_usd": 3.50,
            "_embedded": {
                "analysis": {
                    "character_count": 731000,
                    "character_list": ["贾宝玉", "林黛玉", "薛宝钗", "王熙凤"]
                }
            }
        },
        "project-1-chapters.json": {
            "items": [
                {"id": 1, "title": "第一回 甄士隐梦幻识通灵", "status": "completed", "progress": 1.0},
                {"id": 2, "title": "第二回 贾夫人仙逝扬州城", "status": "completed", "progress": 1.0},
                {"id": 3, "title": "第三回 托内兄如海荐西宾", "status": "processing", "progress": 0.6}
            ],
            "total": 120
        },
        "paragraph-1-detail.json": {
            "id": 1,
            "chapter_id": 1,
            "paragraph_index": 0,
            "original_text": "话说大荒山无稽崖青埂峰下，有一块顽石，自经锻炼，灵性已通。",
            "edited_text": "话说大荒山无稽崖青埂峰下，有一块顽石，自经锻炼，灵性已通。",
            "status": "quality_checked",
            "embedded_data": {
                "annotation": {
                    "speaker_canonical_name": "旁白",
                    "is_dialogue": False,
                    "emotion": "neutral",
                    "emotion_intensity": 0.5,
                    "speech_rate": 1.0,
                    "difficulty": "B",
                    "forbid_edit": False
                },
                "tts_edit": {"changes_made": [], "edited_text": None},
                "routing": {"engine_choice": "kokoro", "voice_id": "kokoro_narrator"},
                "quality": {"overall_score": 0.85, "needs_regeneration": False, "issues": []}
            },
            "annotation": {"speaker_canonical_name": "旁白", "emotion": "neutral"},
            "tts_edit": None,
            "routing": {"engine_choice": "kokoro", "voice_id": "kokoro_narrator"},
            "quality": {"overall_score": 0.85, "needs_regeneration": False}
        },
        "tts-voices.json": {
            "engines": {
                "kokoro": {
                    "available": True,
                    "voices": [
                        {"id": "kokoro_narrator", "name": "旁白", "gender": "neutral", "language": "zh-CN"}
                    ]
                },
                "edge_tts": {
                    "available": True,
                    "voices": [
                        {"id": "zh-CN-XiaoxiaoNeural", "name": "晓晓", "gender": "female", "language": "zh-CN"},
                        {"id": "zh-CN-YunxiNeural", "name": "云希", "gender": "male", "language": "zh-CN"},
                        {"id": "zh-CN-YunjianNeural", "name": "云健", "gender": "male", "language": "zh-CN"}
                    ]
                },
                "azure": {
                    "available": True,
                    "voices": [
                        {"id": "zh-CN-XiaozhenNeural", "name": "晓珍", "gender": "female", "language": "zh-CN"}
                    ]
                }
            }
        },
        "harness-status.json": {
            "running": False,
            "iteration_count": 0,
            "unprocessed_feedback_count": 0,
            "min_feedback_threshold": 10
        },
        "harness-dashboard.json": {
            "iteration_status": {"running": False, "iteration_count": 0},
            "feedback_funnel": {"total_feedback": 0, "analyzed_count": 0},
            "pattern_heatmap": {"patterns": [], "top_patterns": []},
            "prompt_timeline": {"stages": {}},
            "promotion_gate": {"format_compliance_rate": 0.99, "overall_pass": True},
            "canary_dashboard": {"active_canaries": [], "total_active": 0},
            "ab_tests": {"tests": [], "total_tests": 0},
            "critics_latest": {"verdicts": [], "weighted_verdict": "accept"}
        },
        "golden-samples.json": {
            "samples": [
                {
                    "id": "case_1",
                    "stage": "annotate",
                    "input": {"text": "黛玉道：'我没这么凶 hang。'"},
                    "expected_output": {"speaker": "林黛玉", "emotion": "sad", "is_dialogue": True},
                    "human_verified": True,
                    "quality_score": 0.95
                }
            ],
            "total_count": 1,
            "by_stage": {"annotate": 1}
        },
        "export-jobs.json": {
            "items": [
                {
                    "job_id": "export_001",
                    "project_id": 1,
                    "format": "m4b",
                    "status": "completed",
                    "progress": 1.0,
                    "output_url": "/api/export/output_001.m4b",
                    "created_at": "2026-06-25T10:00:00Z",
                    "completed_at": "2026-06-25T10:30:00Z"
                }
            ],
            "total": 1
        },
        "project-1-autorun-status.json": {
            "project_id": 1,
            "run_id": "autorun_1_1719405600",
            "status": "running",
            "current_stage": "annotate",
            "completed_stages": ["extract", "analyze"],
            "progress": 0.28,
            "cost_usd": 1.50,
            "quality_score": None,
            "started_at": "2026-06-26T09:00:00Z"
        }
    }

    for filename, content in SAMPLE_FILES.items():
        filepath = MOCK_DIR / filename
        if not filepath.exists():
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(content, f, ensure_ascii=False, indent=2)
            logger.info(f"Created mock data file: {filepath}")