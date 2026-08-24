"""RAG (Retrieval-Augmented Generation) Module for Audiobook Studio."""

from .models import (
    DocumentType,
    RetrievalStrategy,
    CharacterProfile,
    WorldBuildingDoc,
    StyleGuide,
    PlotSummary,
    ProperNouns,
    RAGDocument,
    RetrievalResult,
    RAGContext,
)
from .vector_store import ChromaVectorStore, get_vector_store, init_vector_store_from_settings
from .retriever import HybridRetriever, get_retriever, init_retriever_from_settings

__all__ = [
    # Models
    "DocumentType",
    "RetrievalStrategy",
    "CharacterProfile",
    "WorldBuildingDoc",
    "StyleGuide",
    "PlotSummary",
    "ProperNouns",
    "RAGDocument",
    "RetrievalResult",
    "RAGContext",
    # Vector Store
    "ChromaVectorStore",
    "get_vector_store",
    "init_vector_store_from_settings",
    # Retriever
    "HybridRetriever",
    "get_retriever",
    "init_retriever_from_settings",
]
