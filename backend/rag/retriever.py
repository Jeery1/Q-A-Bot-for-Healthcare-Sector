"""
RAG retriever for healthcare QA — ChromaDB + sentence-transformers.
"""

import logging
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions

logger = logging.getLogger(__name__)


class MedicalRAG:
    def __init__(
        self,
        persist_dir: str,
        model_name: str = "shibing624/text2vec-base-chinese",
        collection_name: str = "huatuo_medical_qa",
    ):
        self.persist_dir = persist_dir
        Path(persist_dir).mkdir(parents=True, exist_ok=True)

        model_path = model_name
        local = Path(model_name)
        if local.exists() and local.is_dir():
            model_path = str(local.resolve())
            logger.info(f"Using local embedding model: {model_path}")

        self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=model_path
        )
        self.client = chromadb.PersistentClient(path=persist_dir)
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            embedding_function=self.embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )
        count = self.collection.count()
        logger.info(f"MedicalRAG initialized, {count} documents in collection '{collection_name}'")

    def is_ready(self) -> bool:
        return self.collection.count() > 0

    def retrieve(self, query: str, top_k: int = 3) -> list[dict]:
        if not self.is_ready():
            logger.warning("RAG index is empty, returning empty results")
            return []

        results = self.collection.query(query_texts=[query], n_results=top_k)
        docs = []
        ids_list = results.get("ids", [[]])[0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        for i, doc_id in enumerate(ids_list):
            meta = metadatas[i] if i < len(metadatas) else {}
            docs.append({
                "id": doc_id,
                "question": meta.get("question", ""),
                "answer": meta.get("answer", ""),
                "score": 1 - distances[i] if distances and i < len(distances) else 0,
            })

        return docs

    def add_documents(self, documents: list[dict]):
        ids = [doc["id"] for doc in documents]
        texts = [doc["text"] for doc in documents]
        metadatas = [
            {"question": doc.get("question", ""), "answer": doc.get("answer", "")}
            for doc in documents
        ]
        self.collection.add(ids=ids, documents=texts, metadatas=metadatas)
        logger.info(f"Added {len(documents)} documents to collection")

    def get_count(self) -> int:
        return self.collection.count()
