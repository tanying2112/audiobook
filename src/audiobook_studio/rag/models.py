"""RAG Data Models - Character profiles, World-building docs, Style guides."""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ConfigDict


class DocumentType(str, Enum):
    """Types of documents stored in the RAG system."""
    CHARACTER_PROFILE = "character_profile"
    WORLD_BUILDING = "world_building"
    STYLE_GUIDE = "style_guide"
    PLOT_SUMMARY = "plot_summary"
    CHAPTER_SUMMARY = "chapter_summary"
    PROPER_NOUNS = "proper_nouns"  # names, places, terms


class RetrievalStrategy(str, Enum):
    """Retrieval strategy for RAG."""
    SEMANTIC = "semantic"
    BM25 = "bm25"
    HYBRID = "hybrid"


def _json_dumps(obj: Any) -> str:
    """Serialize to JSON string for ChromaDB metadata compatibility."""
    return json.dumps(obj, ensure_ascii=False)


def _json_loads(s: str) -> Any:
    """Deserialize from JSON string."""
    try:
        return json.loads(s)
    except Exception:
        return s


class CharacterProfile(BaseModel):
    """Character profile for consistency across chapters."""
    
    model_config = ConfigDict(extra="allow")
    
    # Core identity
    canonical_name: str = Field(..., description="Canonical name used in narration")
    aliases: List[str] = Field(default_factory=list, description="Alternative names/nicknames")
    pronouns: Dict[str, str] = Field(
        default_factory=lambda: {"subject": "他", "object": "他", "possessive": "他的"},
        description="Pronouns for the character (subject, object, possessive)"
    )
    
    # Physical/Voice attributes
    gender: Optional[str] = Field(None, description="Gender for voice selection")
    age: Optional[str] = Field(None, description="Age range or specific age")
    voice_description: Optional[str] = Field(None, description="Voice characteristics")
    suggested_voice_id: Optional[str] = Field(None, description="TTS voice ID suggestion")
    
    # Personality & Behavior
    personality_traits: List[str] = Field(default_factory=list, description="Key personality traits")
    speech_patterns: List[str] = Field(default_factory=list, description="Speech patterns, catchphrases")
    emotional_baseline: str = Field(default="neutral", description="Default emotional state")
    
    # Relationships
    relationships: Dict[str, str] = Field(
        default_factory=dict, 
        description="Relationship to other characters (name -> relationship)"
    )
    
    # Narrative
    backstory: Optional[str] = Field(None, description="Character backstory")
    role: Optional[str] = Field(None, description="Role in story (protagonist, antagonist, etc.)")
    first_appearance_chapter: Optional[int] = Field(None, description="Chapter where character first appears")
    
    # Metadata
    project_id: int = Field(..., description="Project ID this character belongs to")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    version: int = Field(default=1, description="Profile version for tracking changes")
    
    # Source tracking
    source_chapters: List[int] = Field(default_factory=list, description="Chapters where info was extracted from")
    confidence: float = Field(default=1.0, description="Confidence in this profile (0-1)")


class WorldBuildingDoc(BaseModel):
    """World-building document for setting consistency."""
    
    model_config = ConfigDict(extra="allow")
    
    title: str = Field(..., description="Document title")
    doc_type: str = Field(..., description="Sub-type: geography, magic_system, technology, culture, history, organization, etc.")
    content: str = Field(..., description="Full document content")
    summary: Optional[str] = Field(None, description="Brief summary for quick retrieval")
    
    # Key entities mentioned
    key_entities: List[str] = Field(default_factory=list, description="Important names, places, terms mentioned")
    
    # Metadata
    project_id: int = Field(..., description="Project ID")
    chapter_range: Optional[str] = Field(None, description="Chapters this applies to (e.g., '1-10', 'all')")
    priority: int = Field(default=0, description="Priority for retrieval (higher = more important)")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    version: int = Field(default=1)
    source_chapters: List[int] = Field(default_factory=list)


class StyleGuide(BaseModel):
    """Style guide for narrative voice and writing style."""
    
    model_config = ConfigDict(extra="allow")
    
    name: str = Field(..., description="Style guide name")
    narrative_voice: str = Field(..., description="Description of narrative voice (e.g., 'third-person omniscient, literary')")
    tone: str = Field(..., description="Overall tone (e.g., 'serious, melancholic, humorous')")
    pacing: str = Field(..., description="Pacing style (e.g., 'slow and atmospheric, fast-paced action')")
    
    # Specific rules
    perspective_rules: List[str] = Field(default_factory=list, description="POV rules (e.g., 'never break from protagonist POV')")
    dialogue_rules: List[str] = Field(default_factory=list, description="Dialogue formatting rules")
    description_rules: List[str] = Field(default_factory=list, description="Description style rules")
    forbidden_patterns: List[str] = Field(default_factory=list, description="Patterns to avoid")
    required_patterns: List[str] = Field(default_factory=list, description="Patterns to maintain")
    
    # TTS-specific
    prosody_guidance: Dict[str, Any] = Field(default_factory=dict, description="Prosody guidance for TTS")
    emotion_mapping: Dict[str, str] = Field(default_factory=dict, description="Emotion to prosody mapping")
    
    # Metadata
    project_id: int = Field(..., description="Project ID")
    genre: Optional[str] = Field(None, description="Genre this style guide applies to")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    version: int = Field(default=1)
    source_chapters: List[int] = Field(default_factory=list)


class PlotSummary(BaseModel):
    """Chapter or book-level plot summary."""
    
    model_config = ConfigDict(extra="allow")
    
    project_id: int
    chapter_index: Optional[int] = Field(None, description="Chapter number (None for book-level)")
    summary: str = Field(..., description="Plot summary")
    key_events: List[str] = Field(default_factory=list, description="Key events in this chapter/section")
    characters_involved: List[str] = Field(default_factory=list, description="Characters appearing")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ProperNouns(BaseModel):
    """Proper nouns (names, places, terms) for consistency."""
    
    model_config = ConfigDict(extra="allow")
    
    project_id: int
    category: str = Field(..., description="Category: character, place, organization, item, term, etc.")
    canonical_form: str = Field(..., description="Canonical spelling/form")
    variants: List[str] = Field(default_factory=list, description="Known variants/aliases")
    definition: Optional[str] = Field(None, description="Definition or description")
    first_appearance_chapter: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RAGDocument(BaseModel):
    """Unified document model for ChromaDB storage."""
    
    model_config = ConfigDict(extra="allow")
    
    id: str = Field(..., description="Unique document ID")
    project_id: int = Field(..., description="Project ID")
    doc_type: DocumentType = Field(..., description="Document type")
    content: str = Field(..., description="Document content for embedding")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    embedding: Optional[List[float]] = Field(None, description="Pre-computed embedding")


class RetrievalResult(BaseModel):
    """Result from RAG retrieval."""
    
    model_config = ConfigDict(extra="allow")
    
    document: RAGDocument
    score: float = Field(..., description="Relevance score (0-1)")
    strategy: RetrievalStrategy = Field(..., description="Strategy used for retrieval")


class RAGContext(BaseModel):
    """Aggregated RAG context for LLM injection."""
    
    model_config = ConfigDict(extra="allow")
    
    project_id: int
    chapter_index: Optional[int] = None
    paragraph_index: Optional[int] = None
    
    # Retrieved contexts by type
    character_profiles: List[CharacterProfile] = Field(default_factory=list)
    world_building: List[WorldBuildingDoc] = Field(default_factory=list)
    style_guides: List[StyleGuide] = Field(default_factory=list)
    plot_summaries: List[PlotSummary] = Field(default_factory=list)
    proper_nouns: List[ProperNouns] = Field(default_factory=list)
    
    # Metadata
    retrieval_strategy: RetrievalStrategy = RetrievalStrategy.HYBRID
    total_documents: int = 0
    retrieval_time_ms: float = 0.0
    
    def to_prompt_context(self) -> str:
        """Format retrieved context for LLM prompt injection."""
        parts = []
        
        if self.character_profiles:
            parts.append("=== 角色档案 ===")
            for char in self.character_profiles:
                parts.append(f"【{char.canonical_name}】")
                if char.aliases:
                    parts.append(f"  别名: {', '.join(char.aliases)}")
                parts.append(f"  代词: {char.pronouns}")
                if char.voice_description:
                    parts.append(f"  声音: {char.voice_description}")
                if char.personality_traits:
                    parts.append(f"  性格: {', '.join(char.personality_traits)}")
                if char.speech_patterns:
                    parts.append(f"  语言习惯: {', '.join(char.speech_patterns)}")
                if char.relationships:
                    rel_str = ", ".join(f"{k}: {v}" for k, v in char.relationships.items())
                    parts.append(f"  关系: {rel_str}")
                parts.append("")
        
        if self.world_building:
            parts.append("=== 世界设定 ===")
            for doc in self.world_building:
                parts.append(f"【{doc.title}】({doc.doc_type})")
                if doc.summary:
                    parts.append(f"  摘要: {doc.summary}")
                else:
                    parts.append(f"  内容: {doc.content[:500]}...")
                if doc.key_entities:
                    parts.append(f"  关键实体: {', '.join(doc.key_entities)}")
                parts.append("")
        
        if self.style_guides:
            parts.append("=== 风格指南 ===")
            for guide in self.style_guides:
                parts.append(f"【{guide.name}】")
                parts.append(f"  叙述视角: {guide.narrative_voice}")
                parts.append(f"  基调: {guide.tone}")
                parts.append(f"  节奏: {guide.pacing}")
                if guide.perspective_rules:
                    parts.append(f"  视角规则: {'; '.join(guide.perspective_rules)}")
                if guide.dialogue_rules:
                    parts.append(f"  对话规则: {'; '.join(guide.dialogue_rules)}")
                if guide.forbidden_patterns:
                    parts.append(f"  禁用模式: {'; '.join(guide.forbidden_patterns)}")
                parts.append("")
        
        if self.plot_summaries:
            parts.append("=== 情节摘要 ===")
            for summary in self.plot_summaries:
                if summary.chapter_index:
                    parts.append(f"第 {summary.chapter_index} 章: {summary.summary}")
                else:
                    parts.append(f"全书大纲: {summary.summary}")
                if summary.key_events:
                    parts.append(f"  关键事件: {'; '.join(summary.key_events)}")
                parts.append("")
        
        if self.proper_nouns:
            parts.append("=== 专有名词表 ===")
            for noun in self.proper_nouns:
                variant_str = f" (别名: {', '.join(noun.variants)})" if noun.variants else ""
                parts.append(f"  {noun.canonical_form}{variant_str}: {noun.definition or 'N/A'}")
            parts.append("")
        
        return "\n".join(parts)


# Helper functions for creating RAG documents from pipeline outputs

def create_character_profile_doc(profile: CharacterProfile) -> RAGDocument:
    """Convert CharacterProfile to RAGDocument for storage."""
    content_parts = [
        f"角色: {profile.canonical_name}",
        f"别名: {', '.join(profile.aliases)}" if profile.aliases else "",
        f"代词: {profile.pronouns}",
        f"性别: {profile.gender}" if profile.gender else "",
        f"年龄: {profile.age}" if profile.age else "",
        f"声音描述: {profile.voice_description}" if profile.voice_description else "",
        f"性格特征: {', '.join(profile.personality_traits)}" if profile.personality_traits else "",
        f"语言习惯: {', '.join(profile.speech_patterns)}" if profile.speech_patterns else "",
        f"情感基线: {profile.emotional_baseline}",
        f"背景故事: {profile.backstory}" if profile.backstory else "",
        f"角色定位: {profile.role}" if profile.role else "",
        f"关系: {', '.join(f'{k}是{v}' for k, v in profile.relationships.items())}" if profile.relationships else "",
    ]
    content = "\n".join(filter(None, content_parts))
    
    return RAGDocument(
        id=f"character_{profile.project_id}_{profile.canonical_name}",
        project_id=profile.project_id,
        doc_type=DocumentType.CHARACTER_PROFILE,
        content=content,
        metadata={
            "canonical_name": profile.canonical_name,
            "aliases": _json_dumps(profile.aliases),
            "pronouns": _json_dumps(profile.pronouns),
            "gender": profile.gender,
            "age": profile.age,
            "suggested_voice_id": profile.suggested_voice_id,
            "role": profile.role,
            "first_appearance_chapter": profile.first_appearance_chapter,
            "confidence": profile.confidence,
            "version": profile.version,
            "project_id": profile.project_id,
            "personality_traits": _json_dumps(profile.personality_traits),
            "speech_patterns": _json_dumps(profile.speech_patterns),
            "emotional_baseline": profile.emotional_baseline,
            "backstory": profile.backstory,
            "relationships": _json_dumps(profile.relationships),
        }
    )


def create_world_building_doc(doc: WorldBuildingDoc) -> RAGDocument:
    """Convert WorldBuildingDoc to RAGDocument for storage."""
    content = f"标题: {doc.title}\n类型: {doc.doc_type}\n内容: {doc.content}"
    if doc.summary:
        content = f"摘要: {doc.summary}\n{content}"
    
    return RAGDocument(
        id=f"world_{doc.project_id}_{doc.title}",
        project_id=doc.project_id,
        doc_type=DocumentType.WORLD_BUILDING,
        content=content,
        metadata={
            "title": doc.title,
            "doc_type": doc.doc_type,
            "content": doc.content,
            "summary": doc.summary,
            "key_entities": _json_dumps(doc.key_entities),
            "chapter_range": doc.chapter_range,
            "priority": doc.priority,
            "version": doc.version,
            "project_id": doc.project_id,
        }
    )


def create_style_guide_doc(guide: StyleGuide) -> RAGDocument:
    """Convert StyleGuide to RAGDocument for storage."""
    content_parts = [
        f"风格指南: {guide.name}",
        f"叙述视角: {guide.narrative_voice}",
        f"基调: {guide.tone}",
        f"节奏: {guide.pacing}",
    ]
    if guide.perspective_rules:
        content_parts.append(f"视角规则: {'; '.join(guide.perspective_rules)}")
    if guide.dialogue_rules:
        content_parts.append(f"对话规则: {'; '.join(guide.dialogue_rules)}")
    if guide.description_rules:
        content_parts.append(f"描写规则: {'; '.join(guide.description_rules)}")
    if guide.forbidden_patterns:
        content_parts.append(f"禁用模式: {'; '.join(guide.forbidden_patterns)}")
    if guide.required_patterns:
        content_parts.append(f"必需模式: {'; '.join(guide.required_patterns)}")
    
    content = "\n".join(content_parts)
    
    return RAGDocument(
        id=f"style_{guide.project_id}_{guide.name}",
        project_id=guide.project_id,
        doc_type=DocumentType.STYLE_GUIDE,
        content=content,
        metadata={
            "name": guide.name,
            "narrative_voice": guide.narrative_voice,
            "tone": guide.tone,
            "pacing": guide.pacing,
            "genre": guide.genre,
            "version": guide.version,
            "project_id": guide.project_id,
            "perspective_rules": _json_dumps(guide.perspective_rules),
            "dialogue_rules": _json_dumps(guide.dialogue_rules),
            "description_rules": _json_dumps(guide.description_rules),
            "forbidden_patterns": _json_dumps(guide.forbidden_patterns),
            "required_patterns": _json_dumps(guide.required_patterns),
            "prosody_guidance": _json_dumps(guide.prosody_guidance),
            "emotion_mapping": _json_dumps(guide.emotion_mapping),
        }
    )


def create_plot_summary_doc(summary: PlotSummary) -> RAGDocument:
    """Convert PlotSummary to RAGDocument for storage."""
    content = f"章节: {summary.chapter_index or '全书'}\n摘要: {summary.summary}"
    if summary.key_events:
        content += f"\n关键事件: {'; '.join(summary.key_events)}"
    if summary.characters_involved:
        content += f"\n涉及角色: {', '.join(summary.characters_involved)}"
    
    return RAGDocument(
        id=f"plot_{summary.project_id}_ch{summary.chapter_index or 'all'}",
        project_id=summary.project_id,
        doc_type=DocumentType.PLOT_SUMMARY,
        content=content,
        metadata={
            "chapter_index": summary.chapter_index,
            "key_events": _json_dumps(summary.key_events),
            "characters_involved": _json_dumps(summary.characters_involved),
            "project_id": summary.project_id,
            "summary": summary.summary,
        }
    )


def create_proper_nouns_doc(noun: ProperNouns) -> RAGDocument:
    """Convert ProperNouns to RAGDocument for storage."""
    content = f"词条: {noun.canonical_form}\n类别: {noun.category}"
    if noun.variants:
        content += f"\n别名: {', '.join(noun.variants)}"
    if noun.definition:
        content += f"\n定义: {noun.definition}"
    
    return RAGDocument(
        id=f"noun_{noun.project_id}_{noun.canonical_form}",
        project_id=noun.project_id,
        doc_type=DocumentType.PROPER_NOUNS,
        content=content,
        metadata={
            "canonical_form": noun.canonical_form,
            "category": noun.category,
            "variants": _json_dumps(noun.variants),
            "first_appearance_chapter": noun.first_appearance_chapter,
            "project_id": noun.project_id,
            "definition": noun.definition,
        }
    )


# Deserialization helpers for reconstructing models from metadata
def deserialize_character_profile(metadata: Dict[str, Any]) -> CharacterProfile:
    """Reconstruct CharacterProfile from ChromaDB metadata."""
    return CharacterProfile(
        canonical_name=metadata.get("canonical_name", ""),
        aliases=_json_loads(metadata.get("aliases", "[]")),
        pronouns=_json_loads(metadata.get("pronouns", '{"subject": "他", "object": "他", "possessive": "他的"}')),
        gender=metadata.get("gender"),
        age=metadata.get("age"),
        suggested_voice_id=metadata.get("suggested_voice_id"),
        role=metadata.get("role"),
        first_appearance_chapter=metadata.get("first_appearance_chapter"),
        confidence=metadata.get("confidence", 1.0),
        version=metadata.get("version", 1),
        project_id=metadata.get("project_id", 0),
        personality_traits=_json_loads(metadata.get("personality_traits", "[]")),
        speech_patterns=_json_loads(metadata.get("speech_patterns", "[]")),
        emotional_baseline=metadata.get("emotional_baseline", "neutral"),
        backstory=metadata.get("backstory"),
        relationships=_json_loads(metadata.get("relationships", "{}")),
    )


def deserialize_world_building_doc(metadata: Dict[str, Any]) -> WorldBuildingDoc:
    """Reconstruct WorldBuildingDoc from ChromaDB metadata."""
    return WorldBuildingDoc(
        title=metadata.get("title", ""),
        doc_type=metadata.get("doc_type", ""),
        content=metadata.get("content", ""),
        summary=metadata.get("summary"),
        key_entities=_json_loads(metadata.get("key_entities", "[]")),
        chapter_range=metadata.get("chapter_range"),
        priority=metadata.get("priority", 0),
        version=metadata.get("version", 1),
        project_id=metadata.get("project_id", 0),
    )


def deserialize_style_guide(metadata: Dict[str, Any]) -> StyleGuide:
    """Reconstruct StyleGuide from ChromaDB metadata."""
    return StyleGuide(
        name=metadata.get("name", ""),
        narrative_voice=metadata.get("narrative_voice", ""),
        tone=metadata.get("tone", ""),
        pacing=metadata.get("pacing", ""),
        genre=metadata.get("genre"),
        version=metadata.get("version", 1),
        project_id=metadata.get("project_id", 0),
        perspective_rules=_json_loads(metadata.get("perspective_rules", "[]")),
        dialogue_rules=_json_loads(metadata.get("dialogue_rules", "[]")),
        description_rules=_json_loads(metadata.get("description_rules", "[]")),
        forbidden_patterns=_json_loads(metadata.get("forbidden_patterns", "[]")),
        required_patterns=_json_loads(metadata.get("required_patterns", "[]")),
        prosody_guidance=_json_loads(metadata.get("prosody_guidance", "{}")),
        emotion_mapping=_json_loads(metadata.get("emotion_mapping", "{}")),
    )


def deserialize_plot_summary(metadata: Dict[str, Any]) -> PlotSummary:
    """Reconstruct PlotSummary from ChromaDB metadata."""
    return PlotSummary(
        project_id=metadata.get("project_id", 0),
        chapter_index=metadata.get("chapter_index"),
        summary=metadata.get("summary", ""),
        key_events=_json_loads(metadata.get("key_events", "[]")),
        characters_involved=_json_loads(metadata.get("characters_involved", "[]")),
    )


def deserialize_proper_nouns(metadata: Dict[str, Any]) -> ProperNouns:
    """Reconstruct ProperNouns from ChromaDB metadata."""
    return ProperNouns(
        project_id=metadata.get("project_id", 0),
        category=metadata.get("category", ""),
        canonical_form=metadata.get("canonical_form", ""),
        variants=_json_loads(metadata.get("variants", "[]")),
        definition=metadata.get("definition"),
        first_appearance_chapter=metadata.get("first_appearance_chapter"),
    )
