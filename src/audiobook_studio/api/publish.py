"""
Publish API endpoints for Audiobookshelf and Podcast RSS integration.

Extends export functionality with publishing capabilities:
- Push to Audiobookshelf server
- Generate Podcast RSS feed
- Schedule automatic releases
"""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.book import Project

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects/{project_id}/publish", tags=["publish"])


# ─────────────────────────────────────────────────────────────────────────────
# Request/Response Schemas
# ─────────────────────────────────────────────────────────────────────────────


class AudiobookshelfConfig(BaseModel):
    """Audiobookshelf server configuration."""

    server_url: str = Field(..., description="Audiobookshelf server URL")
    api_key: str = Field(..., description="API key for authentication")
    library_id: Optional[str] = Field(None, description="Target library ID")


class PodcastRSSConfig(BaseModel):
    """Podcast RSS feed configuration."""

    feed_title: str = Field(..., description="Podcast feed title")
    feed_description: str = Field(..., description="Podcast description")
    feed_link: str = Field(..., description="Feed website link")
    feed_language: str = Field("zh-CN", description="Feed language")
    author: str = Field(..., description="Author name")
    owner_email: str = Field(..., description="Owner email for RSS")
    categories: Optional[List[str]] = Field(None, description="Podcast categories")
    explicit: bool = Field(False, description="Whether content is explicit")
    chapter_as_episode: bool = Field(True, description="Use chapters as episodes")


class PublishRequest(BaseModel):
    """Publish request payload."""

    destinations: List[str] = Field(
        ["audiobookshelf"],
        description="Where to publish: audiobookshelf, podcast_rss, both",
    )
    audiobookshelf_config: Optional[AudiobookshelfConfig] = None
    podcast_config: Optional[PodcastRSSConfig] = None


class PublishJobOut(BaseModel):
    """Publish job output."""

    job_id: str
    project_id: int
    status: str = "pending"  # pending, publishing, completed, failed
    destinations: List[str]
    results: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None


class PublishHistoryOut(BaseModel):
    """Publish history item."""

    job_id: str
    status: str
    destinations: List[str]
    created_at: str
    completed_at: Optional[str] = None


class RSSFeedOut(BaseModel):
    """Generated RSS feed."""

    xml: str = Field(..., description="RSS XML content")
    feed_url: str = Field(..., description="Feed URL")
    episode_count: int = Field(..., description="Number of episodes")


# ─────────────────────────────────────────────────────────────────────────────
# In-memory job store (for MVP)
# ─────────────────────────────────────────────────────────────────────────────

_publish_jobs: Dict[str, Dict[str, Any]] = {}


# ─────────────────────────────────────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/", response_model=PublishJobOut)
async def publish_project(
    project_id: int,
    request: PublishRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Publish completed audiobook to destinations.

    Supported destinations:
    - audiobookshelf: Push to Audiobookshelf server
    - podcast_rss: Generate Podcast RSS feed

    Returns job_id for tracking progress.
    """
    # Verify project exists and is completed
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.status != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Project not ready for publishing. Current status: {project.status}",
        )

    # Validate destinations
    valid_destinations = {"audiobookshelf", "podcast_rss"}
    requested = set(request.destinations)
    if not requested.issubset(valid_destinations):
        invalid = requested - valid_destinations
        raise HTTPException(
            status_code=400,
            detail=f"Invalid destinations: {invalid}. Valid: {valid_destinations}",
        )

    # Generate job ID
    job_id = f"publish_{project_id}_{int(datetime.now().timestamp())}"

    # Create job record
    _publish_jobs[job_id] = {
        "job_id": job_id,
        "project_id": project_id,
        "status": "pending",
        "destinations": request.destinations,
        "results": {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    # Schedule background task
    background_tasks.add_task(
        _publish_background,
        job_id=job_id,
        project_id=project_id,
        destinations=request.destinations,
        audiobookshelf_config=(
            request.audiobookshelf_config.model_dump()
            if request.audiobookshelf_config
            else None
        ),
        podcast_config=(
            request.podcast_config.model_dump() if request.podcast_config else None
        ),
    )

    return PublishJobOut(
        job_id=job_id,
        project_id=project_id,
        status="pending",
        destinations=request.destinations,
        created_at=_publish_jobs[job_id]["created_at"],
    )


async def _publish_background(
    job_id: str,
    project_id: int,
    destinations: List[str],
    audiobookshelf_config: Optional[dict] = None,
    podcast_config: Optional[dict] = None,
):
    """
    Background task: Execute publishing.

    For each destination:
    1. Prepare export files
    2. Upload/publish
    3. Record result
    """
    job = _publish_jobs.get(job_id)
    if not job:
        logger.error(f"Publish job {job_id} not found")
        return

    job["status"] = "publishing"

    results = {}

    # Publish to Audiobookshelf
    if "audiobookshelf" in destinations:
        try:
            result = await _publish_to_audiobookshelf(
                project_id=project_id,
                config=audiobookshelf_config or {},
            )
            results["audiobookshelf"] = {
                "success": True,
                "book_url": result.get("book_url"),
            }
        except Exception as e:
            logger.error(f"Audiobookshelf publish failed: {e}")
            results["audiobookshelf"] = {
                "success": False,
                "error": str(e),
            }

    # Generate Podcast RSS
    if "podcast_rss" in destinations:
        try:
            result = await _generate_podcast_rss(
                project_id=project_id,
                config=podcast_config or {},
            )
            results["podcast_rss"] = {
                "success": True,
                "rss_url": result.get("rss_url"),
                "episode_count": result.get("episode_count"),
            }
        except Exception as e:
            logger.error(f"Podcast RSS generation failed: {e}")
            results["podcast_rss"] = {
                "success": False,
                "error": str(e),
            }

    # Update job status
    job["results"] = results
    job["completed_at"] = datetime.now(timezone.utc).isoformat()

    # Check if all succeeded
    all_success = all(r.get("success", False) for r in results.values())
    job["status"] = "completed" if all_success else "failed"

    if not all_success:
        errors = [r.get("error") for r in results.values() if r.get("error")]
        job["error"] = "; ".join(errors)


async def _publish_to_audiobookshelf(
    project_id: int,
    config: dict,
) -> dict:
    """
    Publish to Audiobookshelf server.

    Implements the official Audiobookshelf API flow:
    1. GET  /api/libraries/{id}        — resolve library & folder ID
    2. POST /api/upload                 — upload audio files (multipart)
    3. POST /api/libraries/{id}/scan    — trigger scan to create item
    4. GET  /api/libraries/{id}/search  — find the newly-created item
    5. PATCH /api/items/{id}/media      — update book metadata
    6. POST /api/items/{id}/cover       — upload cover image

    Reference: https://api.audiobookshelf.org/

    Args:
        project_id: Project to publish
        config: Server configuration {
            server_url: str,
            api_key: str,
            library_id: str (optional — first library used if omitted),
            base_path: str (optional, local library path for direct copy)
        }

    Returns:
        Result dict with book_url, item_id, success status, and upload details
    """
    import asyncio
    import shutil

    server_url = config.get("server_url", "").rstrip("/")
    api_key = config.get("api_key")
    library_id = config.get("library_id")
    base_path = config.get("base_path")  # For local file libraries

    if not server_url or not api_key:
        raise ValueError("Audiobookshelf server_url and api_key are required")

    # Prepare API headers (remove Content-Type so aiohttp sets it for multipart)
    headers = {"Authorization": f"Bearer {api_key}"}

    # Helper: resolve MIME type from extension
    def _mime_type(path: Path) -> str:
        return {
            ".m4b": "audio/mp4",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".flac": "audio/flac",
            ".ogg": "audio/ogg",
            ".aac": "audio/aac",
        }.get(path.suffix.lower(), "application/octet-stream")

    async with aiohttp.ClientSession(headers=headers) as session:
        # ─────────────────────────────────────────────────────────────
        # Step 1: Resolve library & folder
        # ─────────────────────────────────────────────────────────────
        if not library_id:
            async with session.get(f"{server_url}/api/libraries") as list_resp:
                if list_resp.status != 200:
                    error_text = await list_resp.text()
                    raise ValueError(
                        f"Failed to list libraries ({list_resp.status}): {error_text}"
                    )
                libraries = await list_resp.json()
                if not libraries:
                    raise ValueError("No libraries found on Audiobookshelf server")
                library_id = libraries[0]["id"]
                logger.info(f"Using first available library: {library_id}")

        # Get library details — we need a folder ID for the upload endpoint
        folder_id: Optional[str] = None
        async with session.get(f"{server_url}/api/libraries/{library_id}") as lib_resp:
            if lib_resp.status == 404:
                async with session.get(f"{server_url}/api/libraries") as list_resp:
                    available = await list_resp.json()
                available_ids = [lib.get("id") for lib in available]
                raise ValueError(
                    f"Library {library_id} not found. Available: {available_ids}"
                )
            elif lib_resp.status != 200:
                error_text = await lib_resp.text()
                raise ValueError(
                    f"Failed to access library ({lib_resp.status}): {error_text}"
                )

            library_info = await lib_resp.json()
            folders = library_info.get("folders", [])
            if folders:
                folder_id = folders[0].get("id")
                logger.info(f"Using folder: {folder_id} in library {library_id}")

        # ─────────────────────────────────────────────────────────────
        # Step 2: Load project metadata & audio segments from DB
        # ─────────────────────────────────────────────────────────────
        from ..database import SessionLocal
        from ..models.audio_segment import AudioSegment

        db = SessionLocal()
        try:
            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                raise ValueError(f"Project {project_id} not found")

            segments = (
                db.query(AudioSegment)
                .filter(
                    AudioSegment.project_id == project_id,
                    AudioSegment.is_current.is_(True),
                )
                .order_by(AudioSegment.id)
                .all()
            )
        finally:
            db.close()

        # Collect existing audio files
        audio_files: List[Path] = []
        total_size = 0
        for seg in segments:
            if seg.file_path:
                p = Path(seg.file_path)
                if p.exists() and p.is_file():
                    audio_files.append(p)
                    total_size += p.stat().st_size

        if not audio_files:
            raise ValueError(f"No audio files found for project {project_id}")

        book_title = project.title or f"Project {project_id}"
        author = project.author or "Unknown"

        # ─────────────────────────────────────────────────────────────
        # Step 3: Upload files
        # ─────────────────────────────────────────────────────────────
        upload_results: List[Dict[str, Any]] = []

        if base_path:
            # ── Local library: copy files directly to the library folder ──
            library_audio_path = Path(base_path) / author / book_title
            library_audio_path.mkdir(parents=True, exist_ok=True)

            for audio_file in audio_files:
                dest_path = library_audio_path / audio_file.name
                try:
                    shutil.copy2(audio_file, dest_path)
                    upload_results.append(
                        {
                            "file": audio_file.name,
                            "success": True,
                            "server_path": str(dest_path),
                        }
                    )
                except Exception as e:
                    upload_results.append(
                        {
                            "file": audio_file.name,
                            "success": False,
                            "error": str(e),
                        }
                    )
        else:
            # ── Remote server: use POST /api/upload (multipart) ──
            if not folder_id:
                raise ValueError(
                    "Library has no folders configured; cannot upload remotely. "
                    "Provide base_path for local copy instead."
                )

            for audio_file in audio_files:
                with open(audio_file, "rb") as f:
                    data = aiohttp.FormData()
                    data.add_field("library", str(library_id))
                    data.add_field("folder", str(folder_id))
                    data.add_field("title", book_title)
                    data.add_field("author", author)
                    data.add_field(
                        "file",
                        f,
                        filename=audio_file.name,
                        content_type=_mime_type(audio_file),
                    )

                    async with session.post(
                        f"{server_url}/api/upload", data=data
                    ) as upload_resp:
                        if upload_resp.status in (200, 201):
                            upload_results.append(
                                {
                                    "file": audio_file.name,
                                    "success": True,
                                }
                            )
                        else:
                            error = await upload_resp.text()
                            upload_results.append(
                                {
                                    "file": audio_file.name,
                                    "success": False,
                                    "error": f"HTTP {upload_resp.status}: {error}",
                                }
                            )

        successful_uploads = sum(1 for r in upload_results if r.get("success"))
        if successful_uploads == 0:
            raise ValueError(
                "All file uploads failed: "
                + "; ".join(
                    r.get("error", "unknown")
                    for r in upload_results
                    if not r.get("success")
                )
            )

        # ─────────────────────────────────────────────────────────────
        # Step 4: Trigger library scan
        # ─────────────────────────────────────────────────────────────
        async with session.post(
            f"{server_url}/api/libraries/{library_id}/scan"
        ) as scan_resp:
            scan_ok = scan_resp.status in (200, 201)
            if not scan_ok:
                logger.warning(f"Scan trigger returned {scan_resp.status}")

        # ─────────────────────────────────────────────────────────────
        # Step 5: Wait for scan & find the new item
        # ─────────────────────────────────────────────────────────────
        item_id: Optional[str] = None
        max_retries = 10
        poll_interval = 3  # seconds

        for attempt in range(max_retries):
            await asyncio.sleep(poll_interval)
            async with session.get(
                f"{server_url}/api/libraries/{library_id}/search",
                params={"q": book_title},
            ) as search_resp:
                if search_resp.status != 200:
                    continue
                results = await search_resp.json()
                for item in results:
                    # Navigate the Audiobookshelf search result structure
                    media = item.get("media") or {}
                    metadata = media.get("metadata") or {}
                    item_title = metadata.get("title", "")
                    if item_title.lower() == book_title.lower():
                        item_id = item.get("id")
                        break
            if item_id:
                break

        if not item_id:
            logger.warning(
                f"Could not locate uploaded item '{book_title}' after "
                f"{max_retries * poll_interval}s. Files were uploaded successfully."
            )

        # ─────────────────────────────────────────────────────────────
        # Step 6: Update book metadata (PATCH /api/items/{id}/media)
        # ─────────────────────────────────────────────────────────────
        if item_id:
            metadata_payload: Dict[str, Any] = {
                "metadata": {
                    "title": book_title,
                    "authorName": author,
                }
            }
            # Conditionally add optional fields (None values not accepted)
            if project.story_line_summary:
                metadata_payload["metadata"]["description"] = project.story_line_summary
            if project.genre:
                metadata_payload["metadata"]["genres"] = [project.genre]
            if project.language:
                # Audiobookshelf uses BCP-47 e.g. "zh-CN"; Project.language is "zh"
                lang = project.language
                if len(lang) == 2:
                    lang_map = {
                        "zh": "zh-CN",
                        "en": "en-US",
                        "ja": "ja-JP",
                        "ko": "ko-KR",
                    }
                    lang = lang_map.get(lang, lang)
                metadata_payload["metadata"]["language"] = lang

            async with session.patch(
                f"{server_url}/api/items/{item_id}/media",
                json=metadata_payload,
            ) as meta_resp:
                if meta_resp.status not in (200,):
                    logger.warning(f"Metadata update returned {meta_resp.status}")

            # ─────────────────────────────────────────────────────────
            # Step 7: Upload cover image (if available)
            # ─────────────────────────────────────────────────────────
            from .. import storage as storage_module

            cover_candidates = [
                storage_module.project_dir(project_id) / "cover.jpg",
                storage_module.project_dir(project_id) / "cover.png",
            ]
            for cover_path in cover_candidates:
                if cover_path.exists():
                    with open(cover_path, "rb") as cover_f:
                        cover_data = aiohttp.FormData()
                        cover_data.add_field(
                            "cover",
                            cover_f,
                            filename=cover_path.name,
                            content_type=(
                                "image/jpeg"
                                if cover_path.suffix == ".jpg"
                                else "image/png"
                            ),
                        )
                        async with session.post(
                            f"{server_url}/api/items/{item_id}/cover",
                            data=cover_data,
                        ) as cover_resp:
                            if cover_resp.status in (200, 201):
                                logger.info(f"Cover uploaded for item {item_id}")
                            else:
                                logger.warning(
                                    f"Cover upload returned {cover_resp.status}"
                                )
                    break  # Only upload the first found cover

        # ─────────────────────────────────────────────────────────────
        # Build result
        # ─────────────────────────────────────────────────────────────
        return {
            "book_url": f"{server_url}/item/{item_id}" if item_id else None,
            "book_id": item_id,
            "item_id": item_id,
            "success": successful_uploads > 0,
            "uploaded_files": successful_uploads,
            "total_files": len(audio_files),
            "total_size_bytes": total_size,
            "upload_results": upload_results,
            "library_id": library_id,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Podcast RSS Generation
# ─────────────────────────────────────────────────────────────────────────────


async def _generate_podcast_rss(
    project_id: int,
    config: dict,
) -> dict:
    """
    Generate Podcast RSS feed.

    Args:
        project_id: Project to publish
        config: Feed configuration (title, description, author, etc.)

    Returns:
        Result dict with rss_url and episode_count
    """
    from ..database import SessionLocal
    from ..models.audio_segment import AudioSegment
    from ..models.book import Project

    db = SessionLocal()
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise ValueError(f"Project {project_id} not found")

        # Get current audio segments (episodes)
        segments = (
            db.query(AudioSegment)
            .filter(
                AudioSegment.project_id == project_id,
                AudioSegment.is_current.is_(True),
            )
            .order_by(AudioSegment.index)
            .all()
        )
        episode_count = len(segments)
    finally:
        db.close()

    # Build public URL for media files
    public_url = os.getenv("APP_PUBLIC_URL", "http://localhost:8000").rstrip("/")
    # Media files are served under /media/{project_id}/ (to be implemented by frontend/web server)
    media_url = f"{public_url}/media/{project_id}"

    # Construct the RSS feed URL (endpoint that serves the generated XML)
    rss_url = f"{public_url}/projects/{project_id}/publish/feed.xml"

    return {
        "rss_url": rss_url,
        "episode_count": episode_count,
        "success": True,
    }


@router.get("/jobs/{job_id}", response_model=PublishJobOut)
async def get_publish_job(project_id: int, job_id: str):
    """Get publish job status by ID."""
    job = _publish_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Publish job not found")

    if job["project_id"] != project_id:
        raise HTTPException(
            status_code=400, detail="Job does not belong to this project"
        )

    return PublishJobOut(**job)


@router.get("/history", response_model=List[PublishHistoryOut])
async def get_publish_history(project_id: int):
    """Get publish history for a project."""
    history = [job for job in _publish_jobs.values() if job["project_id"] == project_id]

    # Sort by created_at descending
    history.sort(key=lambda x: x["created_at"], reverse=True)

    return [
        PublishHistoryOut(
            job_id=job["job_id"],
            status=job["status"],
            destinations=job["destinations"],
            created_at=job["created_at"],
            completed_at=job.get("completed_at"),
        )
        for job in history
    ]


@router.get("/feed.xml", response_model=RSSFeedOut)
async def get_podcast_rss_feed(
    project_id: int,
    feed_title: Optional[str] = None,
    feed_description: Optional[str] = None,
    feed_link: Optional[str] = None,
    feed_language: Optional[str] = None,
    author: Optional[str] = None,
    owner_email: Optional[str] = None,
    categories: Optional[str] = None,  # comma-separated
    explicit: Optional[bool] = False,
):
    """
    Get Podcast RSS feed XML for a project.

    Returns generated RSS feed that can be submitted to podcast platforms.
    """
    from ..database import SessionLocal
    from ..models.audio_segment import AudioSegment
    from ..models.book import Project

    db = SessionLocal()
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # Get current audio segments (episodes)
        segments = (
            db.query(AudioSegment)
            .filter(
                AudioSegment.project_id == project_id,
                AudioSegment.is_current.is_(True),
            )
            .order_by(AudioSegment.index)
            .all()
        )
        episode_count = len(segments)
    finally:
        db.close()

    # Build public URL for media files
    public_url = os.getenv("APP_PUBLIC_URL", "http://localhost:8000").rstrip("/")
    media_url = f"{public_url}/media/{project_id}"

    # Build config from query params with project defaults
    config = {
        "feed_title": feed_title
        or f"Podcast {project.title or f'Project {project_id}'}",
        "feed_description": feed_description or project.story_line_summary or "",
        "feed_link": feed_link or public_url,
        "feed_language": feed_language or project.language or "zh-CN",
        "author": author or project.author or "Unknown",
        "owner_email": owner_email or "admin@example.com",
        "categories": categories.split(",") if categories else [],
        "explicit": explicit or False,
    }

    # Extract config values for RSS generation
    rss_version = "2.0"
    itunes_namespace = "http://www.itunes.com/dtds/podcast-1.0.dtd"
    feed_title = config["feed_title"]
    feed_desc = config["feed_description"]
    feed_link = config["feed_link"]
    feed_lang = config["feed_language"]
    feed_author = config["author"]
    feed_owner_email = config["owner_email"]
    feed_categories = config["categories"]
    feed_explicit = config["explicit"]

    # Generate RSS XML
    xml_lines = [
        f'<?xml version="1.0" encoding="UTF-8"?>',
        f'<rss version="{rss_version}" xmlns:itunes="{itunes_namespace}">',
        f"  <channel>",
        f"    <title>{feed_title}</title>",
        f"    <description>{feed_desc}</description>",
        f"    <link>{feed_link}</link>",
        f"    <language>{feed_lang}</language>",
        f"    <itunes:author>{feed_author}</itunes:author>",
        f"    <itunes:owner><itunes:email>{feed_owner_email}</itunes:email></itunes:owner>",
    ]

    # Add categories
    for category in feed_categories:
        xml_lines.append(f'    <itunes:category text="{category}"/>')

    # Explicit tag
    xml_lines.append(f"    <itunes:explicit>{feed_explicit}</itunes:explicit>")

    # Add episodes
    for i, seg in enumerate(segments, start=1):
        # Get filename from file_path
        filename = Path(seg.file_path).name if seg.file_path else f"episode_{i}.m4b"
        enclosure_url = f"{media_url}/{filename}"
        # Determine MIME type from extension
        ext = Path(filename).suffix.lower()
        mime_type = {
            ".m4b": "audio/mp4",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".flac": "audio/flac",
            ".ogg": "audio/ogg",
            ".aac": "audio/aac",
        }.get(ext, "application/octet-stream")

        # Use segment index or a title from the segment if available
        # We don't have a title in the segment model, so use index or a placeholder
        episode_title = f"Episode {i}"
        # Optionally, use a snippet of the text as description? We don't have text in segment.
        episode_description = f"Chapter {seg.chapter_index if hasattr(seg, 'chapter_index') else '?'} Segment {seg.index if hasattr(seg, 'index') else i}"

        xml_lines.extend(
            [
                f"    <item>",
                f"      <title>{episode_title}</title>",
                f"      <description>{episode_description}</description>",
                f'      <enclosure url="{enclosure_url}" length="{seg.file_size_bytes or 0}" type="{mime_type}"/>',
                f"      <guid>{enclosure_url}</guid>",
                f"      <pubDate>{datetime.now(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S %Z')}</pubDate>",
                f"      <itunes:duration>{seg.duration_ms // 1000 if seg.duration_ms else 0}</itunes:duration>",
                f"    </item>",
            ]
        )

    xml_lines.extend(
        [
            f"  </channel>",
            f"</rss>",
        ]
    )

    xml_content = "\n".join(xml_lines)

    return RSSFeedOut(
        xml=xml_content,
        feed_url=f"{public_url}/projects/{project_id}/publish/feed.xml",
        episode_count=episode_count,
    )
