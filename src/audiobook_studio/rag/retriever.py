"""Hybrid Retriever for RAG - Combines semantic search with BM25."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Set, Union

from rank_bm25 import BM25Okapi

from .models import (
    DocumentType,
    RAGContext,
    RAGDocument,
    RetrievalResult,
    RetrievalStrategy,
    deserialize_character_profile,
    deserialize_plot_summary,
    deserialize_proper_nouns,
    deserialize_style_guide,
    deserialize_world_building_doc,
)
from .vector_store import ChromaVectorStore, get_vector_store, init_vector_store_from_settings

logger = logging.getLogger(__name__)


class HybridRetriever:
    """Hybrid retriever combining semantic search (ChromaDB) with BM25 keyword search."""

    def __init__(
        self,
        vector_store: Optional[ChromaVectorStore] = None,
        top_k: int = 5,
        hybrid_alpha: float = 0.5,  # 0 = BM25 only, 1 = Semantic only
    ):
        self.vector_store = vector_store or get_vector_store()
        self.top_k = top_k
        self.hybrid_alpha = hybrid_alpha

        # BM25 index cache: (project_id, doc_type) -> BM25Okapi
        self._bm25_index: Dict[tuple[int, DocumentType], Optional[BM25Okapi]] = {}
        self._bm25_doc_ids: Dict[tuple[int, DocumentType], List[str]] = {}
        self._bm25_documents: Dict[tuple[int, DocumentType], List[str]] = {}
        self._bm25_tokenized: Dict[tuple[int, DocumentType], List[List[str]]] = {}

    def _tokenize(self, text: str) -> List[str]:
        """Simple tokenization for BM25 (Chinese + English)."""
        import re

        # Split on whitespace and punctuation, keep Chinese characters
        tokens = re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z0-9]+", text.lower())
        return tokens

    def _build_bm25_index(
        self,
        project_id: int,
        doc_type: DocumentType,
        force_rebuild: bool = False,
    ) -> None:
        """Build or rebuild BM25 index for a collection."""
        key = (project_id, doc_type)

        if key in self._bm25_index and not force_rebuild:
            return

        # Get all documents from vector store
        collection = self.vector_store._get_or_create_collection(doc_type, project_id)
        results = collection.get(include=["documents", "metadatas"])

        if not results["ids"]:
            self._bm25_index[key] = None
            self._bm25_doc_ids[key] = []
            self._bm25_documents[key] = []
            self._bm25_tokenized[key] = []
            return

        doc_ids = results["ids"]
        documents = results["documents"] or []

        tokenized_docs = [self._tokenize(doc) for doc in documents]

        # Build BM25 index
        bm25 = BM25Okapi(tokenized_docs)

        self._bm25_index[key] = bm25
        self._bm25_doc_ids[key] = doc_ids
        self._bm25_documents[key] = documents
        self._bm25_tokenized[key] = tokenized_docs

        logger.debug(f"Built BM25 index for {doc_type.value} (project {project_id}): {len(doc_ids)} docs")

    def _bm25_search(
        self,
        query: str,
        project_id: int,
        doc_type: DocumentType,
        n_results: int = 10,
    ) -> List[RetrievalResult]:
        """Search using BM25."""
        self._build_bm25_index(project_id, doc_type)

        key = (project_id, doc_type)
        bm25 = self._bm25_index.get(key)

        if bm25 is None:
            return []

        query_tokens = self._tokenize(query)
        scores = bm25.get_scores(query_tokens)

        # Get top-k indices
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:n_results]

        results = []
        for idx in top_indices:
            if scores[idx] <= 0:
                continue
            doc_id = self._bm25_doc_ids[key][idx]
            doc = RAGDocument(
                id=doc_id,
                project_id=project_id,
                doc_type=doc_type,
                content=self._bm25_documents[key][idx],
                metadata={},  # Metadata not stored in BM25 cache
                embedding=None,
            )
            # Normalize BM25 score to 0-1 range (approximate)
            normalized_score = min(scores[idx] / 10.0, 1.0)
            results.append(
                RetrievalResult(
                    document=doc,
                    score=normalized_score,
                    strategy=RetrievalStrategy.BM25,
                )
            )

        return results

    def _semantic_search(
        self,
        query: str,
        project_id: int,
        doc_type: DocumentType,
        n_results: int = 10,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[RetrievalResult]:
        """Search using semantic similarity (ChromaDB)."""
        docs = self.vector_store.query(
            query_text=query,
            doc_type=doc_type,
            project_id=project_id,
            n_results=n_results,
            where=where,
        )

        results = []
        for doc in docs:
            # ChromaDB returns distances (lower = more similar), convert to similarity score
            # We don't have direct distance here, so use position-based scoring
            results.append(
                RetrievalResult(
                    document=doc,
                    score=1.0,  # Will be re-ranked in hybrid
                    strategy=RetrievalStrategy.SEMANTIC,
                )
            )

        return results

    def _boost_exact_match(self, query: str, results: List[RetrievalResult]) -> List[RetrievalResult]:
        """Boost results that contain the exact query as a canonical form."""
        boosted = []
        for r in results:
            score = r.score
            # Check if query matches canonical_form in metadata exactly
            if r.document.metadata:
                canonical = r.document.metadata.get("canonical_form", "")
                if canonical == query:
                    score *= 1.5  # Boost exact canonical match
                # Also check title for world_building
                title = r.document.metadata.get("title", "")
                if title == query:
                    score *= 1.5
                # Check name for style_guide
                name = r.document.metadata.get("name", "")
                if name == query:
                    score *= 1.5
            boosted.append(
                RetrievalResult(
                    document=r.document,
                    score=score,
                    strategy=r.strategy,
                )
            )
        boosted.sort(key=lambda x: x.score, reverse=True)
        return boosted

    def _hybrid_search(
        self,
        query: str,
        project_id: int,
        doc_type: DocumentType,
        n_results: int = 10,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[RetrievalResult]:
        """Combine semantic and BM25 search results."""
        # Get more results from each for better fusion
        fetch_k = min(n_results * 3, 30)

        semantic_results = self._semantic_search(query, project_id, doc_type, fetch_k, where)
        bm25_results = self._bm25_search(query, project_id, doc_type, fetch_k)

        # Fuse results using reciprocal rank fusion (RRF)
        # RRF score = sum(1 / (k + rank)) for each result
        k = 60  # RRF parameter

        # Create score maps
        semantic_scores: Dict[str, float] = {}
        for rank, result in enumerate(semantic_results):
            semantic_scores[result.document.id] = 1.0 / (k + rank + 1)

        bm25_scores: Dict[str, float] = {}
        for rank, result in enumerate(bm25_results):
            bm25_scores[result.document.id] = 1.0 / (k + rank + 1)

        # Combine all unique document IDs
        all_ids: Set[str] = set(semantic_scores.keys()) | set(bm25_scores.keys())

        # Compute hybrid scores
        fused_results: List[RetrievalResult] = []
        for doc_id in all_ids:
            sem_score = semantic_scores.get(doc_id, 0.0)
            bm25_score = bm25_scores.get(doc_id, 0.0)

            # Weighted combination
            hybrid_score = self.hybrid_alpha * sem_score + (1 - self.hybrid_alpha) * bm25_score

            # Find the document object
            doc = None
            for r in semantic_results:
                if r.document.id == doc_id:
                    doc = r.document
                    break
            if doc is None:
                for r in bm25_results:
                    if r.document.id == doc_id:
                        doc = r.document
                        break

            if doc:
                fused_results.append(
                    RetrievalResult(
                        document=doc,
                        score=hybrid_score,
                        strategy=RetrievalStrategy.HYBRID,
                    )
                )

        # Boost exact canonical form matches
        fused_results = self._boost_exact_match(query, fused_results)

        # Sort by hybrid score and return top-k
        fused_results.sort(key=lambda x: x.score, reverse=True)
        return fused_results[:n_results]

    def _normalize_strategy(self, strategy: Union[RetrievalStrategy, str]) -> RetrievalStrategy:
        """Normalize strategy input to RetrievalStrategy enum."""
        if isinstance(strategy, RetrievalStrategy):
            return strategy
        if isinstance(strategy, str):
            try:
                return RetrievalStrategy(strategy.lower())
            except ValueError:
                return RetrievalStrategy.HYBRID
        return RetrievalStrategy.HYBRID

    def retrieve(
        self,
        query: str,
        project_id: int,
        doc_type: DocumentType,
        n_results: int = 5,
        strategy: Union[RetrievalStrategy, str] = RetrievalStrategy.HYBRID,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[RetrievalResult]:
        """Main retrieval method."""
        start_time = time.time()

        strategy = self._normalize_strategy(strategy)

        if strategy == RetrievalStrategy.SEMANTIC:
            results = self._semantic_search(query, project_id, doc_type, n_results, where)
        elif strategy == RetrievalStrategy.BM25:
            results = self._bm25_search(query, project_id, doc_type, n_results)
        else:  # HYBRID
            results = self._hybrid_search(query, project_id, doc_type, n_results, where)

        elapsed = (time.time() - start_time) * 1000
        logger.debug(f"Retrieval ({strategy.value}) for {doc_type.value}: {len(results)} results in {elapsed:.1f}ms")

        return results

    def retrieve_context(
        self,
        query: str,
        project_id: int,
        chapter_index: Optional[int] = None,
        paragraph_index: Optional[int] = None,
        top_k: Optional[int] = None,
        strategy: Union[RetrievalStrategy, str] = RetrievalStrategy.HYBRID,
    ) -> RAGContext:
        """Retrieve comprehensive context for a query across all document types."""
        start_time = time.time()
        k = top_k or self.top_k

        strategy = self._normalize_strategy(strategy)

        context = RAGContext(
            project_id=project_id,
            chapter_index=chapter_index,
            paragraph_index=paragraph_index,
            retrieval_strategy=strategy,
        )

        # Build filters for chapter-specific retrieval
        chapter_filter = None
        if chapter_index is not None:
            chapter_filter = {"chapter_index": chapter_index}

        # Retrieve from each document type
        # 1. Character profiles (always relevant)
        char_results = self.retrieve(query, project_id, DocumentType.CHARACTER_PROFILE, k, strategy)
        context.character_profiles = [deserialize_character_profile(r.document.metadata) for r in char_results]

        # 2. World building (no chapter filter - uses chapter_range in metadata)
        world_results = self.retrieve(query, project_id, DocumentType.WORLD_BUILDING, k, strategy)
        context.world_building = [deserialize_world_building_doc(r.document.metadata) for r in world_results]

        # 3. Style guides
        style_results = self.retrieve(query, project_id, DocumentType.STYLE_GUIDE, min(k, 3), strategy)
        context.style_guides = [deserialize_style_guide(r.document.metadata) for r in style_results]

        # 4. Plot summaries (use chapter filter)
        plot_results = self.retrieve(query, project_id, DocumentType.PLOT_SUMMARY, k, strategy, where=chapter_filter)
        context.plot_summaries = [deserialize_plot_summary(r.document.metadata) for r in plot_results]

        # 5. Proper nouns
        noun_results = self.retrieve(query, project_id, DocumentType.PROPER_NOUNS, k * 2, strategy)
        context.proper_nouns = [deserialize_proper_nouns(r.document.metadata) for r in noun_results]

        context.total_documents = (
            len(context.character_profiles)
            + len(context.world_building)
            + len(context.style_guides)
            + len(context.plot_summaries)
            + len(context.proper_nouns)
        )
        context.retrieval_time_ms = (time.time() - start_time) * 1000

        logger.info(
            f"RAG context retrieved for project {project_id}, ch{chapter_index}: "
            f"{context.total_documents} docs in {context.retrieval_time_ms:.1f}ms"
        )

        return context

    def retrieve_for_paragraph(
        self,
        paragraph_text: str,
        project_id: int,
        chapter_index: int,
        paragraph_index: int,
        top_k: Optional[int] = None,
    ) -> RAGContext:
        """Retrieve context specifically for paragraph annotation/synthesis."""
        # Build query from paragraph text + context
        query = paragraph_text[:500]  # First 500 chars as query

        return self.retrieve_context(
            query=query,
            project_id=project_id,
            chapter_index=chapter_index,
            paragraph_index=paragraph_index,
            top_k=top_k,
        )

    def retrieve_for_chapter(
        self,
        chapter_summary: str,
        project_id: int,
        chapter_index: int,
        top_k: Optional[int] = None,
    ) -> RAGContext:
        """Retrieve context for chapter-level processing."""
        return self.retrieve_context(
            query=chapter_summary,
            project_id=project_id,
            chapter_index=chapter_index,
            top_k=top_k,
        )

    def invalidate_bm25_cache(self, project_id: int, doc_type: Optional[DocumentType] = None) -> None:
        """Invalidate BM25 cache for a project or specific doc type."""
        if doc_type:
            key = (project_id, doc_type)
            self._bm25_index.pop(key, None)
            self._bm25_doc_ids.pop(key, None)
            self._bm25_documents.pop(key, None)
            self._bm25_tokenized.pop(key, None)
        else:
            # Invalidate all for project
            keys_to_remove = [k for k in self._bm25_index.keys() if k[0] == project_id]
            for key in keys_to_remove:
                self._bm25_index.pop(key, None)
                self._bm25_doc_ids.pop(key, None)
                self._bm25_documents.pop(key, None)
                self._bm25_tokenized.pop(key, None)

    def get_stats(self, project_id: int) -> Dict[str, Any]:
        """Get retriever statistics."""
        stats: Dict[str, Any] = {
            "project_id": project_id,
            "bm25_cache_size": len([k for k in self._bm25_index.keys() if k[0] == project_id]),
            "collections": {},
        }

        for doc_type in DocumentType:
            try:
                coll_stats = self.vector_store.get_collection_stats(doc_type, project_id)
                stats["collections"][doc_type.value] = coll_stats
            except Exception as e:
                stats["collections"][doc_type.value] = {"error": str(e)}

        return stats


# Global instance
_retriever: Optional[HybridRetriever] = None


def get_retriever(
    vector_store: Optional[ChromaVectorStore] = None,
    top_k: int = 5,
    hybrid_alpha: float = 0.5,
) -> HybridRetriever:
    """Get or create the global retriever instance."""
    global _retriever
    if _retriever is None:
        _retriever = HybridRetriever(
            vector_store=vector_store,
            top_k=top_k,
            hybrid_alpha=hybrid_alpha,
        )
    return _retriever


def init_retriever_from_settings(settings: Any) -> HybridRetriever:
    """Initialize retriever from application settings."""
    global _retriever
    vector_store = init_vector_store_from_settings(settings)
    _retriever = HybridRetriever(
        vector_store=vector_store,
        top_k=settings.RAG_TOP_K,
        hybrid_alpha=settings.RAG_HYBRID_SEARCH_ALPHA,
    )
    return _retriever
