"""Language registry API — S3.4 (cross-language end-to-end support).

Exposes the supported-language registry (zh / en / ja / ko / fr / es / de / ...)
with per-language TTS engine + free-resource LLM API recommendations, plus the
helpers used by the auto-translate pipeline and cross-language SOP migration.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from ..languages import (
    SUPPORTED_BCP47_CODES,
    SUPPORTED_ISO_CODES,
    SUPPORTED_LANGUAGES,
    free_api_for,
    get_language_info,
    is_supported,
    migrate_sop_rules,
    normalize_language,
    requires_translation,
    tts_engine_for,
)

router = APIRouter(prefix="/languages", tags=["languages"])


@router.get("")
def list_languages() -> Dict[str, Any]:
    """Return all first-class supported languages with their TTS / free-API config.

    S3.4 acceptance: zh / en / ja / ko are first-class and each carries a TTS
    voice + a recommended free-resource LLM API family.
    """
    languages: List[Dict[str, Any]] = []
    for iso, info in SUPPORTED_LANGUAGES.items():
        languages.append(
            {
                "iso639_1": info.iso639_1,
                "bcp47": info.bcp47,
                "display_name": info.display_name,
                "default_edge_voice": info.default_edge_voice,
                "tts_engine": tts_engine_for(iso),
                "free_api": free_api_for(iso),
                "prompt_guidance": info.prompt_guidance,
                "translation_supported": info.translation_supported,
            }
        )
    return {
        "supported_iso": SUPPORTED_ISO_CODES,
        "supported_bcp47": SUPPORTED_BCP47_CODES,
        "languages": languages,
    }


@router.get("/{code}")
def get_language(code: str) -> Dict[str, Any]:
    """Return per-language TTS / free-API config, or 404 if unsupported."""
    if not is_supported(code):
        raise HTTPException(status_code=404, detail=f"Unsupported language: {code}")
    iso = normalize_language(code)
    info = get_language_info(iso)
    return {
        "iso639_1": info.iso639_1,
        "bcp47": info.bcp47,
        "display_name": info.display_name,
        "default_edge_voice": info.default_edge_voice,
        "tts_engine": tts_engine_for(iso),
        "free_api": free_api_for(iso),
        "prompt_guidance": info.prompt_guidance,
        "translation_supported": info.translation_supported,
    }


@router.get("/translate/required")
def translate_required(source: str = Query(...), target: str = Query(...)) -> Dict[str, Any]:
    """Whether the auto-translate stage must run for source -> target (S3.4)."""
    return {
        "source": normalize_language(source),
        "target": normalize_language(target),
        "requires_translation": requires_translation(source, target),
    }


@router.post("/sop/migrate")
def migrate_sop(source_lang: str = Query(...), target_lang: str = Query(...), rules: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Cross-language SOP rule migration (S3.4).

    Adapts the provided SOP rules (genre/rules) from ``source_lang`` to
    ``target_lang``: keeps rule structure, tags the target language and swaps
    language-specific ``prompt_guidance``.
    """
    migrated = migrate_sop_rules(source_lang, target_lang, rules or [])
    return {
        "source_language": normalize_language(source_lang),
        "target_language": normalize_language(target_lang),
        "migrated_count": len(migrated),
        "rules": migrated,
    }
