from __future__ import annotations

from dataclasses import dataclass

from app.embedder import CodeEmbedder
from app.vectorstore import PineconeStore


@dataclass
class CodeRetriever:
    store: PineconeStore
    embedder: CodeEmbedder

    def get_retriever(self, namespace: str, k: int = 5):
        return self.store.get_retriever(self.embedder, namespace, k=k)
