"""
v0.5 RAG Consistency Integration Tests

These tests verify that the RAG system maintains consistency across 100 chapters
by using the golden dataset as ground truth.
"""

import json
import os
import sys
from pathlib import Path

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from audiobook_studio.rag import (
    CharacterProfile,
    DocumentType,
    PlotSummary,
    ProperNouns,
    StyleGuide,
    WorldBuildingDoc,
    init_retriever_from_settings,
    init_vector_store_from_settings,
)


class TestRAGGoldenDataset:
    """Test RAG consistency using golden dataset."""

    @classmethod
    def setup_class(cls):
        """Load golden dataset and initialize RAG system."""
        # Load golden dataset
        golden_path = Path(__file__).parent.parent / "golden" / "v05_rag" / "golden_dataset.json"
        with open(golden_path, "r", encoding="utf-8") as f:
            cls.golden = json.load(f)

        # Load test cases
        test_cases_path = Path(__file__).parent.parent / "golden" / "v05_rag" / "test_cases.json"
        with open(test_cases_path, "r", encoding="utf-8") as f:
            cls.test_cases = json.load(f)

        # Initialize vector store with in-memory ChromaDB for testing
        # Use a unique collection prefix for test isolation
        os.environ["CHROMADB_HOST"] = "localhost"
        os.environ["CHROMADB_PORT"] = "8000"
        os.environ["CHROMADB_COLLECTION_PREFIX"] = "audiobook_test"
        os.environ["CHROMADB_EMBEDDING_MODEL"] = "sentence-transformers/all-MiniLM-L6-v2"
        os.environ["CHROMADB_PERSIST_DIRECTORY"] = "./data/test_chromadb"
        os.environ["ENABLE_RAG"] = "true"
        os.environ["RAG_TOP_K"] = "5"
        os.environ["RAG_HYBRID_SEARCH_ALPHA"] = "0.5"

        # Import settings to get the configured values
        from audiobook_studio.config.settings import Settings

        cls.settings = Settings()

        # These are ChromaDB integration tests requiring a live server on
        # localhost:8000 and CHROMADB_* settings that the hermetic unit
        # environment does not provide. Skip deterministically rather than
        # erroring at setup when the config or server is unavailable.
        if not hasattr(cls.settings, "CHROMADB_HOST"):
            pytest.skip("Settings does not provide CHROMADB_* config")
        try:
            import socket

            sock = socket.create_connection((cls.settings.CHROMADB_HOST, int(cls.settings.CHROMADB_PORT)), timeout=1.0)
            sock.close()
        except Exception:
            pytest.skip("ChromaDB server not reachable")

        # Initialize vector store and retriever
        cls.vector_store = init_vector_store_from_settings(cls.settings)
        cls.retriever = init_retriever_from_settings(cls.settings)

        # Populate with golden data
        cls._populate_golden_data()

    @classmethod
    def _populate_golden_data(cls):
        """Populate vector store with golden dataset."""
        project_id = 999  # Test project ID

        # Add world building documents
        for _key, wb_data in cls.golden["world_building"].items():
            doc = WorldBuildingDoc(
                project_id=project_id,
                title=wb_data["title"],
                doc_type=wb_data["doc_type"],
                content=wb_data["content"],
                summary=wb_data.get("summary"),
                key_entities=wb_data.get("key_entities", []),
                chapter_range=wb_data.get("chapter_range", "1-100"),
                priority=wb_data.get("priority", 5),
                source_chapters=list(range(1, 101)),
            )
            cls.vector_store.add_world_building_doc(doc)

        # Add character profiles
        for char_data in cls.golden["characters"]:
            profile = CharacterProfile(
                project_id=project_id,
                canonical_name=char_data["canonical_name"],
                aliases=char_data.get("aliases", []),
                pronouns=char_data.get("pronouns", {"subject": "他", "object": "他", "possessive": "他的"}),
                gender=char_data.get("gender"),
                age=char_data.get("age"),
                voice_description=char_data.get("voice_description"),
                suggested_voice_id=char_data.get("suggested_voice_id"),
                personality_traits=char_data.get("personality_traits", []),
                speech_patterns=char_data.get("speech_patterns", []),
                emotional_baseline=char_data.get("emotional_baseline", "neutral"),
                relationships=char_data.get("relationships", {}),
                backstory=char_data.get("backstory"),
                role=char_data.get("role"),
                first_appearance_chapter=char_data.get("first_appearance_chapter"),
                confidence=char_data.get("confidence", 1.0),
                source_chapters=list(range(char_data.get("first_appearance_chapter", 1), 101)),
            )
            cls.vector_store.add_character_profile(profile)

        # Add style guide
        sg = cls.golden["style_guide"]
        style_guide = StyleGuide(
            project_id=project_id,
            name=sg["name"],
            narrative_voice=sg["narrative_voice"],
            tone=sg["tone"],
            pacing=sg["pacing"],
            perspective_rules=sg.get("perspective_rules", []),
            dialogue_rules=sg.get("dialogue_rules", []),
            description_rules=sg.get("description_rules", []),
            forbidden_patterns=sg.get("forbidden_patterns", []),
            required_patterns=sg.get("required_patterns", []),
            prosody_guidance=sg.get("prosody_guidance", {}),
            emotion_mapping=sg.get("emotion_mapping", {}),
            genre=sg.get("genre"),
            source_chapters=sg.get("source_chapters", [1]),
        )
        cls.vector_store.add_style_guide(style_guide)

        # Add plot summaries
        for ch in cls.golden["chapters"]:
            plot = PlotSummary(
                project_id=project_id,
                chapter_index=ch["chapter_index"],
                summary=ch["summary"],
                key_events=ch.get("key_events", []),
                characters_involved=ch.get("characters_involved", []),
            )
            cls.vector_store.add_plot_summary(plot)

        # Add proper nouns
        for noun_data in cls.golden["proper_nouns"]:
            noun = ProperNouns(
                project_id=project_id,
                category=noun_data["category"],
                canonical_form=noun_data["canonical_form"],
                variants=noun_data.get("variants", []),
                definition=noun_data.get("definition"),
                first_appearance_chapter=noun_data.get("first_appearance_chapter"),
            )
            cls.vector_store.add_proper_nouns(noun)

        # Invalidate BM25 cache to rebuild with new data
        cls.retriever.invalidate_bm25_cache(project_id)

        print("Populated RAG with:")
        print(f"  - {len(cls.golden['world_building'])} world building docs")
        print(f"  - {len(cls.golden['characters'])} character profiles")
        print("  - 1 style guide")
        print(f"  - {len(cls.golden['chapters'])} plot summaries")
        print(f"  - {len(cls.golden['proper_nouns'])} proper nouns")

    def test_character_retrieval_by_name(self):
        """Test retrieving character by canonical name and aliases."""
        project_id = 999

        for tc in self.test_cases["character_retrieval_tests"]:
            query = tc["query"]
            results = self.retriever.retrieve(query, project_id, DocumentType.CHARACTER_PROFILE, n_results=5)

            assert len(results) > 0, f"No results for query: {query}"

            # Check expected character found
            if "expected_character" in tc:
                found = False
                for r in results:
                    if tc["expected_character"] in r.document.content:
                        found = True
                        break
                assert found, f"Expected character {tc['expected_character']} not found in results for '{query}'"

            # Check expected noun found
            if "expected_noun" in tc:
                found = False
                for r in results:
                    if tc["expected_noun"] in r.document.content:
                        found = True
                        break
                assert found, f"Expected noun {tc['expected_noun']} not found in results for '{query}'"

    def test_world_building_retrieval(self):
        """Test retrieving world building facts."""
        project_id = 999

        for tc in self.test_cases["world_building_tests"]:
            query = tc["query"]
            results = self.retriever.retrieve(query, project_id, DocumentType.WORLD_BUILDING, n_results=5)

            assert len(results) > 0, f"No results for query: {query}"

            if "expected_entities" in tc:
                for entity in tc["expected_entities"]:
                    found = False
                    for r in results:
                        if entity in r.document.content:
                            found = True
                            break
                    assert found, f"Expected entity {entity} not found in results for '{query}'"

            if "expected_event" in tc:
                found = False
                for r in results:
                    if tc["expected_event"] in r.document.content:
                        found = True
                        break
                assert found, f"Expected event {tc['expected_event']} not found in results for '{query}'"

    def test_style_guide_retrieval(self):
        """Test retrieving style guide rules."""
        project_id = 999

        query = "风格指南 叙述视角 对话规则"
        results = self.retriever.retrieve(query, project_id, DocumentType.STYLE_GUIDE, n_results=3)

        assert len(results) > 0, "No style guide results"

        # Check key style rules present
        content = results[0].document.content
        assert "第三人称" in content or "全知" in content
        assert "对话" in content
        assert "禁用" in content or "forbidden" in content.lower()

    def test_proper_noun_retrieval(self):
        """Test retrieving proper nouns and checking canonical forms."""
        project_id = 999

        for tc in self.test_cases["proper_noun_drift_tests"]:
            canonical = tc["canonical"]
            forbidden = tc["forbidden_variants"]

            # Search for canonical form
            results = self.retriever.retrieve(canonical, project_id, DocumentType.PROPER_NOUNS, n_results=5)

            assert len(results) > 0, f"No results for canonical: {canonical}"

            # Verify canonical form is in results
            found_canonical = False
            for r in results:
                if canonical in r.document.content:
                    found_canonical = True
                    break
            assert found_canonical, f"Canonical form {canonical} not found in results"

            # Verify forbidden variants are NOT the primary match
            for r in results[:3]:  # Top 3 results
                for forbidden_variant in forbidden:
                    assert (
                        forbidden_variant not in r.document.content
                    ), f"Forbidden variant '{forbidden_variant}' found in top results for '{canonical}'"

    def test_rag_context_comprehensive(self):
        """Test comprehensive RAG context retrieval for a paragraph."""
        project_id = 999
        chapter_index = 10
        paragraph_index = 5
        paragraph_text = "艾琳抬头望向星空，低声念道：《星辰指引吾路》，星尘在指尖汇聚成光。"

        context = self.retriever.retrieve_for_paragraph(
            paragraph_text=paragraph_text,
            project_id=project_id,
            chapter_index=chapter_index,
            paragraph_index=paragraph_index,
        )

        # Verify all context types populated
        assert len(context.character_profiles) > 0, "No character profiles retrieved"
        assert len(context.world_building) > 0, "No world building retrieved"
        assert len(context.style_guides) > 0, "No style guides retrieved"
        assert len(context.plot_summaries) > 0, "No plot summaries retrieved"
        assert len(context.proper_nouns) > 0, "No proper nouns retrieved"

        # Verify key character (艾琳) is in context
        char_names = [c.canonical_name for c in context.character_profiles]
        assert "艾琳·星织" in char_names, "Protagonist not in retrieved context"

        # Verify context can be formatted for prompt
        prompt_context = context.to_prompt_context()
        assert len(prompt_context) > 100, "Prompt context too short"
        assert "角色档案" in prompt_context
        assert "世界设定" in prompt_context
        assert "风格指南" in prompt_context
        assert "情节摘要" in prompt_context
        assert "专有名词" in prompt_context

    def test_chapter_level_retrieval(self):
        """Test chapter-level RAG context retrieval."""
        project_id = 999
        chapter_index = 50  # Mid-story climax

        # Use chapter summary as query
        chapter_summary = self.golden["chapters"][chapter_index - 1]["summary"]

        context = self.retriever.retrieve_for_chapter(
            chapter_summary=chapter_summary,
            project_id=project_id,
            chapter_index=chapter_index,
        )

        assert context.total_documents > 0
        assert len(context.plot_summaries) > 0

        # Should retrieve current and adjacent chapter summaries
        plot_chapters = [p.chapter_index for p in context.plot_summaries if p.chapter_index]
        assert chapter_index in plot_chapters or (chapter_index - 1) in plot_chapters

    def test_hybrid_search_strategy(self):
        """Test that hybrid search combines semantic and BM25."""
        project_id = 999
        query = "霜誓护腕 凯尔"

        # Test each strategy
        semantic_results = self.retriever.retrieve(
            query, project_id, DocumentType.PROPER_NOUNS, n_results=5, strategy="semantic"
        )
        bm25_results = self.retriever.retrieve(
            query, project_id, DocumentType.PROPER_NOUNS, n_results=5, strategy="bm25"
        )
        hybrid_results = self.retriever.retrieve(
            query, project_id, DocumentType.PROPER_NOUNS, n_results=5, strategy="hybrid"
        )

        # All should return results
        assert len(semantic_results) > 0
        assert len(bm25_results) > 0
        assert len(hybrid_results) > 0

        # Hybrid should find the item (either semantic or BM25)
        found_in_hybrid = any("霜誓护腕" in r.document.content for r in hybrid_results)
        assert found_in_hybrid, "Hybrid search failed to find item"

    def test_cross_chapter_consistency(self):
        """Test that character info is consistent across chapters."""
        project_id = 999

        # Retrieve character at different chapter points
        for ch_idx in [1, 25, 50, 75, 100]:
            context = self.retriever.retrieve_for_chapter(
                chapter_summary=f"第{ch_idx}章剧情",
                project_id=project_id,
                chapter_index=ch_idx,
            )

            # Find 艾琳 in character profiles
            elin = None
            for c in context.character_profiles:
                if c.canonical_name == "艾琳·星织":
                    elin = c
                    break

            assert elin is not None, f"艾琳 not found in chapter {ch_idx} context"

            # Verify core attributes consistent
            assert elin.pronouns["subject"] == "她", f"Pronoun mismatch at chapter {ch_idx}"
            assert "冷静理智" in elin.personality_traits, f"Personality trait missing at chapter {ch_idx}"
            assert elin.suggested_voice_id == "zh-CN-XiaoxiaoNeural", f"Voice ID mismatch at chapter {ch_idx}"

    def test_no_character_name_drift(self):
        """Test that character names don't drift to variants."""
        project_id = 999

        # Search for each character by canonical name
        canonical_names = ["艾琳·星织", "凯尔·霜誓", "赛琳娜·炎心", "索恩·深岩", "莉拉·青藤"]

        for canonical in canonical_names:
            results = self.retriever.retrieve(canonical, project_id, DocumentType.CHARACTER_PROFILE, n_results=3)

            assert len(results) > 0, f"No results for {canonical}"

            # Top result should match canonical name
            top_result = results[0].document.content
            assert canonical in top_result, f"Canonical name {canonical} not in top result"

    def test_magic_system_consistency(self):
        """Test magic system rules don't contradict."""
        project_id = 999

        queries = [
            "冰系 克制 火系",
            "火系 克制 风系",
            "魔力反噬 跨系 修习",
            "禁忌魔法 死灵 血祭",
        ]

        for query in queries:
            results = self.retriever.retrieve(
                query, project_id, DocumentType.WORLD_BUILDING, n_results=3, where={"doc_type": "magic_system"}
            )

            assert len(results) > 0, f"No results for magic system query: {query}"

            # Verify content contains expected magic system info
            content = results[0].document.content
            assert "魔法" in content or "系" in content

    def test_retriever_stats(self):
        """Test retriever statistics reporting."""
        project_id = 999

        stats = self.retriever.get_stats(project_id)

        assert stats["project_id"] == project_id
        assert "bm25_cache_size" in stats
        assert "collections" in stats

        # Check each collection has documents (skip chapter_summary - not used in current impl)
        for doc_type, coll_stats in stats["collections"].items():
            if "document_count" in coll_stats and doc_type != "chapter_summary":
                assert coll_stats["document_count"] > 0, f"Collection {doc_type} is empty"


class TestRAGSchemaCompatibility:
    """Test that RAG schemas are compatible with existing pipeline schemas."""

    def test_paragraph_annotation_input_has_rag_context(self):
        """Verify ParagraphAnnotationInput has optional rag_context field."""
        from audiobook_studio.schemas.paragraph import ParagraphAnnotationInput

        # Check field exists
        fields = ParagraphAnnotationInput.model_fields
        assert "rag_context" in fields
        assert fields["rag_context"].is_required() is False
        assert fields["rag_context"].default is None

    def test_tts_routing_input_has_rag_context(self):
        """Verify TtsRoutingInput has optional rag_context field."""
        from audiobook_studio.schemas.tts_routing import TtsRoutingInput

        fields = TtsRoutingInput.model_fields
        assert "rag_context" in fields
        assert fields["rag_context"].is_required() is False
        assert fields["rag_context"].default is None

    def test_rag_context_model_structure(self):
        """Verify RAGContext model has all required fields."""
        from audiobook_studio.rag.models import CharacterProfile, RAGContext

        # Create minimal context
        context = RAGContext(
            project_id=1,
            character_profiles=[],
            world_building=[],
            style_guides=[],
            plot_summaries=[],
            proper_nouns=[],
        )

        # Verify it can be formatted for prompt
        prompt = context.to_prompt_context()
        assert isinstance(prompt, str)

        # Add a character and verify it appears
        char = CharacterProfile(
            project_id=1,
            canonical_name="测试角色",
            pronouns={"subject": "他", "object": "他", "possessive": "他的"},
        )
        context.character_profiles = [char]
        prompt = context.to_prompt_context()
        assert "测试角色" in prompt
        assert "角色档案" in prompt


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
