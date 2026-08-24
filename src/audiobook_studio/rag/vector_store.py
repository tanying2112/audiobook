"""ChromaDB Vector Store Wrapper for RAG."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings
from chromadb.utils import embedding_functions
from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2

from .models import (
    RAGDocument,
    DocumentType,
    CharacterProfile,
    WorldBuildingDoc,
    StyleGuide,
    PlotSummary,
    ProperNouns,
    create_character_profile_doc,
    create_world_building_doc,
    create_style_guide_doc,
    create_plot_summary_doc,
    create_proper_nouns_doc,
)

logger = logging.getLogger(__name__)


class ChromaVectorStore:
    """Wrapper around ChromaDB for RAG document storage and retrieval."""
    
    def __init__(
        self,
        host: str = "localhost",
        port: int = 8000,
        collection_prefix: str = "audiobook",
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
        persist_directory: Optional[str] = None,
    ):
        self.host = host
        self.port = port
        self.collection_prefix = collection_prefix
        self.embedding_model = embedding_model
        self.persist_directory = persist_directory
        
        self._client: Optional[chromadb.Client] = None
        self._collections: Dict[DocumentType, chromadb.Collection] = {}
        self._embedding_fn = None
        
    def _get_client(self) -> chromadb.Client:
        """Get or create ChromaDB client."""
        if self._client is None:
            if self.persist_directory:
                # Persistent client for local development
                self._client = chromadb.PersistentClient(
                    path=self.persist_directory,
                    settings=ChromaSettings(
                        anonymized_telemetry=False,
                        allow_reset=True,
                    )
                )
            else:
                # HTTP client for remote/server deployment
                self._client = chromadb.HttpClient(
                    host=self.host,
                    port=self.port,
                    settings=ChromaSettings(anonymized_telemetry=False),
                )
        return self._client
    
    def _get_embedding_function(self):
        """Get or create embedding function."""
        if self._embedding_fn is None:
            # Use ONNX MiniLM-L6-v2 for CPU-only inference (no PyTorch required)
            # Falls back to default if ONNX model not available
            try:
                self._embedding_fn = ONNXMiniLM_L6_V2()
            except Exception:
                # Fallback to default embedding function
                self._embedding_fn = embedding_functions.DefaultEmbeddingFunction()
        return self._embedding_fn
    
    def _get_collection_name(self, doc_type: DocumentType, project_id: int) -> str:
        """Generate collection name for a document type and project."""
        return f"{self.collection_prefix}_{doc_type.value}_{project_id}"
    
    def _get_or_create_collection(self, doc_type: DocumentType, project_id: int) -> chromadb.Collection:
        """Get or create a collection for a document type."""
        key = (doc_type, project_id)
        if key not in self._collections:
            client = self._get_client()
            collection_name = self._get_collection_name(doc_type, project_id)
            try:
                collection = client.get_collection(
                    name=collection_name,
                    embedding_function=self._get_embedding_function(),
                )
            except Exception:
                collection = client.create_collection(
                    name=collection_name,
                    embedding_function=self._get_embedding_function(),
                    metadata={"project_id": project_id, "doc_type": doc_type.value},
                )
            self._collections[key] = collection
        return self._collections[key]
    
    def add_document(self, doc: RAGDocument) -> str:
        """Add a single document to the vector store."""
        collection = self._get_or_create_collection(doc.doc_type, doc.project_id)
        
        # Generate ID if not provided
        doc_id = doc.id or str(uuid.uuid4())
        
        collection.add(
            ids=[doc_id],
            documents=[doc.content],
            metadatas=[doc.metadata],
            embeddings=[doc.embedding] if doc.embedding else None,
        )
        logger.debug(f"Added document {doc_id} to {doc.doc_type.value} collection")
        return doc_id
    
    def add_documents(self, docs: List[RAGDocument]) -> List[str]:
        """Add multiple documents to the vector store."""
        if not docs:
            return []
        
        # Group by collection
        by_collection: Dict[tuple, List[RAGDocument]] = {}
        for doc in docs:
            key = (doc.doc_type, doc.project_id)
            by_collection.setdefault(key, []).append(doc)
        
        all_ids = []
        for (doc_type, project_id), doc_list in by_collection.items():
            collection = self._get_or_create_collection(doc_type, project_id)
            
            ids = []
            documents = []
            metadatas = []
            embeddings = []
            
            for doc in doc_list:
                doc_id = doc.id or str(uuid.uuid4())
                ids.append(doc_id)
                documents.append(doc.content)
                metadatas.append(doc.metadata)
                if doc.embedding:
                    embeddings.append(doc.embedding)
            
            collection.add(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
                embeddings=embeddings if embeddings else None,
            )
            all_ids.extend(ids)
            logger.debug(f"Added {len(doc_list)} documents to {doc_type.value} collection")
        
        return all_ids
    
    def query(
        self,
        query_text: str,
        doc_type: DocumentType,
        project_id: int,
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None,
        where_document: Optional[Dict[str, Any]] = None,
    ) -> List[RAGDocument]:
        """Query documents by semantic similarity."""
        collection = self._get_or_create_collection(doc_type, project_id)
        
        results = collection.query(
            query_texts=[query_text],
            n_results=n_results,
            where=where,
            where_document=where_document,
            include=["documents", "metadatas", "distances"],
        )
        
        documents = []
        if results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                doc = RAGDocument(
                    id=doc_id,
                    project_id=project_id,
                    doc_type=doc_type,
                    content=results["documents"][0][i],
                    metadata=results["metadatas"][0][i] or {},
                )
                documents.append(doc)
        
        return documents
    
    def query_by_ids(
        self,
        ids: List[str],
        doc_type: DocumentType,
        project_id: int,
    ) -> List[RAGDocument]:
        """Retrieve documents by their IDs."""
        collection = self._get_or_create_collection(doc_type, project_id)
        
        results = collection.get(
            ids=ids,
            include=["documents", "metadatas"],
        )
        
        documents = []
        if results["ids"]:
            for i, doc_id in enumerate(results["ids"]):
                doc = RAGDocument(
                    id=doc_id,
                    project_id=project_id,
                    doc_type=doc_type,
                    content=results["documents"][i],
                    metadata=results["metadatas"][i] or {},
                )
                documents.append(doc)
        
        return documents
    
    def update_document(self, doc: RAGDocument) -> None:
        """Update an existing document."""
        collection = self._get_or_create_collection(doc.doc_type, doc.project_id)
        collection.update(
            ids=[doc.id],
            documents=[doc.content],
            metadatas=[doc.metadata],
            embeddings=[doc.embedding] if doc.embedding else None,
        )
    
    def delete_document(self, doc_id: str, doc_type: DocumentType, project_id: int) -> None:
        """Delete a document by ID."""
        collection = self._get_or_create_collection(doc_type, project_id)
        collection.delete(ids=[doc_id])
    
    def delete_project(self, project_id: int) -> None:
        """Delete all collections for a project."""
        client = self._get_client()
        for doc_type in DocumentType:
            collection_name = self._get_collection_name(doc_type, project_id)
            try:
                client.delete_collection(collection_name)
                self._collections.pop((doc_type, project_id), None)
            except Exception:
                pass  # Collection might not exist
    
    def get_collection_stats(self, doc_type: DocumentType, project_id: int) -> Dict[str, Any]:
        """Get collection statistics."""
        collection = self._get_or_create_collection(doc_type, project_id)
        count = collection.count()
        return {
            "collection_name": self._get_collection_name(doc_type, project_id),
            "document_count": count,
            "doc_type": doc_type.value,
            "project_id": project_id,
        }
    
    # --- High-level methods for domain models ---
    
    def add_character_profile(self, profile: CharacterProfile) -> str:
        """Add a character profile to the vector store."""
        doc = create_character_profile_doc(profile)
        return self.add_document(doc)
    
    def add_world_building_doc(self, doc: WorldBuildingDoc) -> str:
        """Add a world-building document to the vector store."""
        rag_doc = create_world_building_doc(doc)
        return self.add_document(rag_doc)
    
    def add_style_guide(self, guide: StyleGuide) -> str:
        """Add a style guide to the vector store."""
        rag_doc = create_style_guide_doc(guide)
        return self.add_document(rag_doc)
    
    def add_plot_summary(self, summary: PlotSummary) -> str:
        """Add a plot summary to the vector store."""
        rag_doc = create_plot_summary_doc(summary)
        return self.add_document(rag_doc)
    
    def add_proper_nouns(self, noun: ProperNouns) -> str:
        """Add proper nouns to the vector store."""
        rag_doc = create_proper_nouns_doc(noun)
        return self.add_document(rag_doc)
    
    def search_characters(
        self,
        query: str,
        project_id: int,
        n_results: int = 5,
    ) -> List[RAGDocument]:
        """Search character profiles."""
        return self.query(query, DocumentType.CHARACTER_PROFILE, project_id, n_results)
    
    def search_world_building(
        self,
        query: str,
        project_id: int,
        n_results: int = 5,
        doc_type_filter: Optional[str] = None,
    ) -> List[RAGDocument]:
        """Search world-building documents."""
        where = {"doc_type": doc_type_filter} if doc_type_filter else None
        return self.query(query, DocumentType.WORLD_BUILDING, project_id, n_results, where=where)
    
    def search_style_guides(
        self,
        query: str,
        project_id: int,
        n_results: int = 3,
    ) -> List[RAGDocument]:
        """Search style guides."""
        return self.query(query, DocumentType.STYLE_GUIDE, project_id, n_results)
    
    def search_plot_summaries(
        self,
        query: str,
        project_id: int,
        n_results: int = 5,
    ) -> List[RAGDocument]:
        """Search plot summaries."""
        return self.query(query, DocumentType.PLOT_SUMMARY, project_id, n_results)
    
    def search_proper_nouns(
        self,
        query: str,
        project_id: int,
        n_results: int = 10,
        category: Optional[str] = None,
    ) -> List[RAGDocument]:
        """Search proper nouns."""
        where = {"category": category} if category else None
        return self.query(query, DocumentType.PROPER_NOUNS, project_id, n_results, where=where)
    
    def get_all_characters(self, project_id: int) -> List[RAGDocument]:
        """Get all character profiles for a project."""
        collection = self._get_or_create_collection(DocumentType.CHARACTER_PROFILE, project_id)
        results = collection.get(include=["documents", "metadatas"])
        return [
            RAGDocument(
                id=results["ids"][i],
                project_id=project_id,
                doc_type=DocumentType.CHARACTER_PROFILE,
                content=results["documents"][i],
                metadata=results["metadatas"][i] or {},
            )
            for i in range(len(results["ids"]))
        ]


# Global instance (initialized lazily)
_vector_store: Optional[ChromaVectorStore] = None


def get_vector_store(
    host: str = "localhost",
    port: int = 8000,
    collection_prefix: str = "audiobook",
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
    persist_directory: Optional[str] = None,
) -> ChromaVectorStore:
    """Get or create the global vector store instance."""
    global _vector_store
    if _vector_store is None:
        _vector_store = ChromaVectorStore(
            host=host,
            port=port,
            collection_prefix=collection_prefix,
            embedding_model=embedding_model,
            persist_directory=persist_directory,
        )
    return _vector_store


def init_vector_store_from_settings(settings) -> ChromaVectorStore:
    """Initialize vector store from application settings."""
    global _vector_store
    _vector_store = ChromaVectorStore(
        host=settings.CHROMADB_HOST,
        port=settings.CHROMADB_PORT,
        collection_prefix=settings.CHROMADB_COLLECTION_PREFIX,
        embedding_model=settings.CHROMADB_EMBEDDING_MODEL,
        persist_directory=settings.CHROMADB_PERSIST_DIRECTORY,
    )
    return _vector_store
