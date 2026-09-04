"""
Standalone v0.5 RAG test - avoids full package import issues.
"""

import json
import sys
from pathlib import Path

# Add src to path - but need to make rag a package
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

# Create a minimal __init__.py for rag if needed
rag_init = Path(__file__).parent.parent.parent / "src" / "audiobook_studio" / "rag" / "__init__.py"
if not rag_init.exists():
    rag_init.write_text("")

# Now import with the package structure
# First load models (no dependencies)
import importlib.util


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(f"audiobook_studio.rag.{name}", path)
    module = importlib.util.module_from_spec(spec)
    # Set up the module's __package__ for relative imports
    module.__package__ = "audiobook_studio.rag"
    sys.modules[f"audiobook_studio.rag.{name}"] = module
    spec.loader.exec_module(module)
    return module


# Load in dependency order
models = load_module("models", "src/audiobook_studio/rag/models.py")
vector_store = load_module("vector_store", "src/audiobook_studio/rag/vector_store.py")
retriever = load_module("retriever", "src/audiobook_studio/rag/retriever.py")

CharacterProfile = models.CharacterProfile
WorldBuildingDoc = models.WorldBuildingDoc
StyleGuide = models.StyleGuide
PlotSummary = models.PlotSummary
ProperNouns = models.ProperNouns
DocumentType = models.DocumentType
ChromaVectorStore = vector_store.ChromaVectorStore
HybridRetriever = retriever.HybridRetriever

print("✓ All RAG modules loaded successfully")


class Settings:
    """Mock settings for testing."""

    CHROMADB_HOST = "localhost"
    CHROMADB_PORT = 8000
    CHROMADB_COLLECTION_PREFIX = "audiobook_test"
    CHROMADB_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
    CHROMADB_PERSIST_DIRECTORY = "./data/test_chromadb"
    ENABLE_RAG = True
    RAG_TOP_K = 5
    RAG_HYBRID_SEARCH_ALPHA = 0.5


def main():
    # Load golden dataset
    golden_path = Path(__file__).parent.parent / "golden" / "v05_rag" / "golden_dataset.json"
    with open(golden_path, "r", encoding="utf-8") as f:
        golden = json.load(f)

    test_cases_path = Path(__file__).parent.parent / "golden" / "v05_rag" / "test_cases.json"
    with open(test_cases_path, "r", encoding="utf-8") as f:
        test_cases = json.load(f)

    # Initialize
    settings = Settings()
    vector_store_instance = ChromaVectorStore(
        host=settings.CHROMADB_HOST,
        port=settings.CHROMADB_PORT,
        collection_prefix=settings.CHROMADB_COLLECTION_PREFIX,
        embedding_model=settings.CHROMADB_EMBEDDING_MODEL,
        persist_directory=settings.CHROMADB_PERSIST_DIRECTORY,
    )
    retriever_instance = HybridRetriever(
        vector_store=vector_store_instance,
        top_k=settings.RAG_TOP_K,
        hybrid_alpha=settings.RAG_HYBRID_SEARCH_ALPHA,
    )

    project_id = 999

    # Populate
    print("Populating vector store...")

    # World building
    for _key, wb_data in golden["world_building"].items():
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
        vector_store_instance.add_world_building_doc(doc)

    # Characters
    for char_data in golden["characters"]:
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
        vector_store_instance.add_character_profile(profile)

    # Style guide
    sg = golden["style_guide"]
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
    vector_store_instance.add_style_guide(style_guide)

    # Plot summaries
    for ch in golden["chapters"]:
        plot = PlotSummary(
            project_id=project_id,
            chapter_index=ch["chapter_index"],
            summary=ch["summary"],
            key_events=ch.get("key_events", []),
            characters_involved=ch.get("characters_involved", []),
        )
        vector_store_instance.add_plot_summary(plot)

    # Proper nouns
    for noun_data in golden["proper_nouns"]:
        noun = ProperNouns(
            project_id=project_id,
            category=noun_data["category"],
            canonical_form=noun_data["canonical_form"],
            variants=noun_data.get("variants", []),
            definition=noun_data.get("definition"),
            first_appearance_chapter=noun_data.get("first_appearance_chapter"),
        )
        vector_store_instance.add_proper_nouns(noun)

    # Rebuild BM25
    retriever_instance.invalidate_bm25_cache(project_id)
    print("✓ Vector store populated")

    # Run tests
    print("\n=== Running Tests ===\n")

    passed = 0
    failed = 0

    def test(name, condition, msg=""):
        nonlocal passed, failed
        if condition:
            print(f"✅ {name}")
            passed += 1
        else:
            print(f"❌ {name}: {msg}")
            failed += 1

    # Test 1: Character retrieval by name
    print("Test 1: Character retrieval")
    for tc in test_cases["character_retrieval_tests"]:
        query = tc["query"]
        results = retriever_instance.retrieve(query, project_id, DocumentType.CHARACTER_PROFILE, n_results=5)

        if "expected_character" in tc:
            found = any(tc["expected_character"] in r.document.content for r in results)
            test(f"  Character: {tc['expected_character']}", found, f"Not found in results for '{query}'")

        if "expected_noun" in tc:
            found = any(tc["expected_noun"] in r.document.content for r in results)
            test(f"  Noun: {tc['expected_noun']}", found, f"Not found in results for '{query}'")

    # Test 2: World building
    print("\nTest 2: World building retrieval")
    for tc in test_cases["world_building_tests"]:
        query = tc["query"]
        results = retriever_instance.retrieve(query, project_id, DocumentType.WORLD_BUILDING, n_results=5)

        if "expected_entities" in tc:
            for entity in tc["expected_entities"]:
                found = any(entity in r.document.content for r in results)
                test(f"  Entity: {entity}", found, f"Not found in results for '{query}'")

        if "expected_event" in tc:
            found = any(tc["expected_event"] in r.document.content for r in results)
            test(f"  Event: {tc['expected_event']}", found, f"Not found in results for '{query}'")

    # Test 3: Style guide
    print("\nTest 3: Style guide retrieval")
    results = retriever_instance.retrieve("风格指南 叙述视角", project_id, DocumentType.STYLE_GUIDE, n_results=3)
    test("  Style guide found", len(results) > 0)
    if results:
        content = results[0].document.content
        test("  Has narrative voice", "第三人称" in content or "全知" in content)
        test("  Has dialogue rules", "对话" in content)

    # Test 4: Proper nouns - canonical forms
    print("\nTest 4: Proper noun canonical forms")
    for tc in test_cases["proper_noun_drift_tests"]:
        canonical = tc["canonical"]
        forbidden = tc["forbidden_variants"]

        results = retriever_instance.retrieve(canonical, project_id, DocumentType.PROPER_NOUNS, n_results=5)
        found_canonical = any(canonical in r.document.content for r in results)
        test(f"  Canonical: {canonical}", found_canonical, "Canonical not in results")

        # Check forbidden variants not in top results
        for r in results[:3]:
            for fv in forbidden:
                if fv in r.document.content:
                    test(f"  No forbidden variant: {fv}", False, "Found forbidden variant in top result")
                else:
                    test(f"  No forbidden variant: {fv}", True)

    # Test 5: Comprehensive RAG context
    print("\nTest 5: Comprehensive RAG context")
    context = retriever_instance.retrieve_for_paragraph(
        paragraph_text="艾琳抬头望向星空，低声念道：《星辰指引吾路》，星尘在指尖汇聚成光。",
        project_id=project_id,
        chapter_index=10,
        paragraph_index=5,
    )

    test("  Has character profiles", len(context.character_profiles) > 0)
    test("  Has world building", len(context.world_building) > 0)
    test("  Has style guides", len(context.style_guides) > 0)
    test("  Has plot summaries", len(context.plot_summaries) > 0)
    test("  Has proper nouns", len(context.proper_nouns) > 0)

    char_names = [c.canonical_name for c in context.character_profiles]
    test("  Protagonist in context", "艾琳·星织" in char_names)

    prompt = context.to_prompt_context()
    test("  Prompt context formatted", len(prompt) > 100)
    test("  Has sections", all(s in prompt for s in ["角色档案", "世界设定", "风格指南", "情节摘要", "专有名词"]))

    # Test 6: Cross-chapter consistency
    print("\nTest 6: Cross-chapter character consistency")
    for ch_idx in [1, 25, 50, 75, 100]:
        context = retriever_instance.retrieve_for_chapter(
            chapter_summary=f"第{ch_idx}章剧情",
            project_id=project_id,
            chapter_index=ch_idx,
        )

        elin = next((c for c in context.character_profiles if c.canonical_name == "艾琳·星织"), None)
        test(f"  Ch{ch_idx}: 艾琳 found", elin is not None)
        if elin:
            test(f"  Ch{ch_idx}: Pronouns correct", elin.pronouns.get("subject") == "她")
            test(f"  Ch{ch_idx}: Personality correct", "冷静理智" in elin.personality_traits)
            test(f"  Ch{ch_idx}: Voice ID correct", elin.suggested_voice_id == "zh-CN-XiaoxiaoNeural")

    # Test 7: Hybrid search strategies
    print("\nTest 7: Hybrid search strategies")
    query = "霜誓护腕 凯尔"
    sem = retriever_instance.retrieve(query, project_id, DocumentType.PROPER_NOUNS, n_results=5, strategy="semantic")
    bm25 = retriever_instance.retrieve(query, project_id, DocumentType.PROPER_NOUNS, n_results=5, strategy="bm25")
    hybrid = retriever_instance.retrieve(query, project_id, DocumentType.PROPER_NOUNS, n_results=5, strategy="hybrid")

    test("  Semantic returns results", len(sem) > 0)
    test("  BM25 returns results", len(bm25) > 0)
    test("  Hybrid returns results", len(hybrid) > 0)
    test("  Hybrid finds item", any("霜誓护腕" in r.document.content for r in hybrid))

    # Test 8: Stats
    print("\nTest 8: Retriever stats")
    stats = retriever_instance.get_stats(project_id)
    test("  Stats has project_id", stats["project_id"] == project_id)
    test("  Stats has collections", "collections" in stats)
    for doc_type, coll_stats in stats["collections"].items():
        if "document_count" in coll_stats:
            test(f"  {doc_type} has docs", coll_stats["document_count"] > 0)

    # Summary
    print(f"\n=== Summary: {passed} passed, {failed} failed ===")
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
