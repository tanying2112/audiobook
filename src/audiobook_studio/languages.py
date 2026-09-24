"""Language support registry — S2.3 (expand language support: JA / FR).

Centralises the set of languages the pipeline can handle end-to-end
(extraction → analysis → annotation → TTS) and the per-language metadata
used to pick TTS voices and build language-aware LLM prompts.

Previously only ``zh``/``en`` were first-class. This module makes Japanese
(``ja``/``ja-JP``) and French (``fr``/``fr-FR``) first-class citizens so the
frontend, API and LLM providers can surface and honour them consistently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

# ── Core registry ────────────────────────────────────────────────────────────

# Mapping from ISO 639-1 (used by schemas/pipeline) to BCP-47 (used by TTS/Edge).
_ISO_TO_BCP47: Dict[str, str] = {
    "zh": "zh-CN",
    "en": "en-US",
    "ja": "ja-JP",
    "fr": "fr-FR",
    "es": "es-ES",
    "de": "de-DE",
    "ko": "ko-KR",
    "pt": "pt-BR",
    "it": "it-IT",
    "ru": "ru-RU",
    "zh-TW": "zh-TW",
}


@dataclass(frozen=True)
class LanguageInfo:
    """Per-language metadata for the audiobook pipeline."""

    iso639_1: str
    bcp47: str
    display_name: str
    # Default Edge-TTS neural voice for this language.
    default_edge_voice: str
    # Script family used by the language (for detection heuristics).
    script: str = "latin"
    # Short guidance injected into LLM prompts so the model responds in-language.
    prompt_guidance: str = ""
    # Free, self-hostable TTS engine family for this language (e.g. "edge").
    tts_engine: str = "edge"
    # Recommended free-resource LLM provider family for this language.
    # Ollama (local) and Qwen (strong multilingual / CJK) are both free.
    free_api: str = "ollama"
    # Whether the translate pipeline can auto-translate into this language.
    translation_supported: bool = True


# Per-language overrides for the recommended free LLM family (S3.4).
# Qwen has strong CJK/multilingual coverage; Llama is strongest for English.
_LANGUAGE_FREE_API: Dict[str, str] = {
    "zh": "qwen",
    "ja": "qwen",
    "ko": "qwen",
    "en": "llama",
}


# Canonical, supported languages (S2.3 adds ja / fr as first-class).
SUPPORTED_LANGUAGES: Dict[str, LanguageInfo] = {
    "zh": LanguageInfo(
        iso639_1="zh",
        bcp47="zh-CN",
        display_name="中文（简体）",
        default_edge_voice="zh-CN-XiaoyiNeural",
        script="han",
        prompt_guidance="请使用简体中文输出。",
    ),
    "en": LanguageInfo(
        iso639_1="en",
        bcp47="en-US",
        display_name="English",
        default_edge_voice="en-US-JennyNeural",
        script="latin",
        prompt_guidance="Please respond in English.",
    ),
    "ja": LanguageInfo(
        iso639_1="ja",
        bcp47="ja-JP",
        display_name="日本語",
        default_edge_voice="ja-JP-NanamiNeural",
        script="japanese",
        prompt_guidance="日本語で出力してください。",
    ),
    "fr": LanguageInfo(
        iso639_1="fr",
        bcp47="fr-FR",
        display_name="Français",
        default_edge_voice="fr-FR-DeniseNeural",
        script="latin",
        prompt_guidance="Veuillez répondre en français.",
    ),
    "es": LanguageInfo(
        iso639_1="es",
        bcp47="es-ES",
        display_name="Español",
        default_edge_voice="es-ES-ElviraNeural",
        script="latin",
        prompt_guidance="Por favor responda en español.",
    ),
    "de": LanguageInfo(
        iso639_1="de",
        bcp47="de-DE",
        display_name="Deutsch",
        default_edge_voice="de-DE-KatjaNeural",
        script="latin",
        prompt_guidance="Bitte antworten Sie auf Deutsch.",
    ),
    "ko": LanguageInfo(
        iso639_1="ko",
        bcp47="ko-KR",
        display_name="한국어",
        default_edge_voice="ko-KR-SunHiNeural",
        script="hangul",
        prompt_guidance="한국어로 출력해 주세요.",
        free_api="qwen",
    ),
}


# Convenience lists used by API validation and frontend dropdowns.
SUPPORTED_BCP47_CODES: List[str] = sorted({info.bcp47 for info in SUPPORTED_LANGUAGES.values()})
SUPPORTED_ISO_CODES: List[str] = sorted(SUPPORTED_LANGUAGES.keys())


def normalize_language(code: str) -> str:
    """Normalize any language code (ISO-639-1 or BCP-47) to ISO-639-1.

    Examples: ``"ja-JP"`` -> ``"ja"``, ``"zh-CN"`` -> ``"zh"``.
    Unknown codes fall back to ``"en"``.
    """
    code = (code or "").strip()
    if not code:
        return "en"
    if code in SUPPORTED_LANGUAGES:
        return code
    # Try BCP-47 -> ISO (e.g. "ja-JP")
    if code in _ISO_TO_BCP47:
        return _ISO_TO_BCP47[code]
    base = code.split("-")[0].lower()
    if base in SUPPORTED_LANGUAGES:
        return base
    return "en"


def to_bcp47(code: str) -> str:
    """Return the BCP-47 TTS code for an ISO or BCP-47 language code."""
    iso = normalize_language(code)
    return SUPPORTED_LANGUAGES[iso].bcp47


def get_language_info(code: str) -> Optional[LanguageInfo]:
    """Return :class:`LanguageInfo` for ``code`` (any form), or ``None``."""
    iso = normalize_language(code)
    return SUPPORTED_LANGUAGES.get(iso)


def is_supported(code: str) -> bool:
    """Whether ``code`` (ISO or BCP-47) is a supported language."""
    return normalize_language(code) in SUPPORTED_LANGUAGES


def default_voice_for(code: str) -> str:
    """Return the default Edge-TTS voice id for ``code``."""
    info = get_language_info(code)
    return info.default_edge_voice if info else "en-US-JennyNeural"


def prompt_guidance_for(code: str) -> str:
    """Return the language-specific LLM prompt guidance (empty if unknown)."""
    info = get_language_info(code)
    return info.prompt_guidance if info else ""


def tts_engine_for(code: str) -> str:
    """Return the recommended free TTS engine family for ``code`` (S3.4)."""
    info = get_language_info(code)
    if info and info.tts_engine:
        return info.tts_engine
    return "edge"


def free_api_for(code: str) -> str:
    """Return the recommended free-resource LLM provider family for ``code`` (S3.4)."""
    iso = normalize_language(code)
    if iso in _LANGUAGE_FREE_API:
        return _LANGUAGE_FREE_API[iso]
    info = SUPPORTED_LANGUAGES.get(iso)
    if info and info.free_api:
        return info.free_api
    return "ollama"


def requires_translation(source: str, target: str) -> bool:
    """Whether the auto-translate stage must translate source -> target (S3.4).

    Returns ``False`` when both sides normalise to the same language (no-op
    translation is skipped to avoid degrading already-correct text).
    """
    return normalize_language(source) != normalize_language(target)


def migrate_sop_rules(source_lang: str, target_lang: str, rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Migrate SOP genre/rules from ``source_lang`` to ``target_lang`` (S3.4).

    Cross-language SOP migration keeps the *structure* of each rule but adapts
    language-specific metadata: the rule is tagged with the target language and
    its ``prompt_guidance`` is swapped for the target language's guidance so the
    pipeline emits prompts in the right language. Rule *content* (e.g. genre
    descriptions) is left to the translate pipeline; this function only handles
    the metadata-level adaptation and is fully deterministic/testable.
    """
    src = normalize_language(source_lang)
    tgt = normalize_language(target_lang)
    tgt_guidance = prompt_guidance_for(tgt)
    migrated: list[dict[str, Any]] = []
    for rule in rules or []:
        new_rule = dict(rule)
        new_rule["language"] = tgt
        new_rule["source_language"] = src
        new_rule["target_language"] = tgt
        if "prompt_guidance" in new_rule:
            new_rule["prompt_guidance"] = tgt_guidance
        migrated.append(new_rule)
    return migrated
