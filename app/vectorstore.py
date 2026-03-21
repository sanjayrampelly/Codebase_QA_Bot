from __future__ import annotations

from dataclasses import dataclass

from utils.config import get_env
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class PineconeStore:
    index_name: str
    dimension: int = 384
    metric: str = "cosine"
    cloud: str = "aws"
    region: str = "us-east-1"

    def __post_init__(self) -> None:
        value = (self.index_name or "").strip()
        if value.lower() in {"", "none", "null"}:
            self.index_name = get_env("PINECONE_INDEX_NAME", "codebase-qna") or "codebase-qna"

    def _list_index_names(self, pinecone_client) -> list[str]:
        indexes = pinecone_client.list_indexes()
        if hasattr(indexes, "names"):
            return list(indexes.names())
        if isinstance(indexes, list):
            return [idx["name"] if isinstance(idx, dict) else idx.name for idx in indexes]
        return []

    def init_index(self):
        api_key = get_env("PINECONE_API_KEY")
        if not api_key:
            raise ValueError("PINECONE_API_KEY is not set")

        from pinecone import Pinecone, ServerlessSpec

        pc = Pinecone(api_key=api_key)
        existing = self._list_index_names(pc)
        if self.index_name not in existing:
            logger.info("Creating Pinecone index: %s", self.index_name)
            pc.create_index(
                name=self.index_name,
                dimension=self.dimension,
                metric=self.metric,
                spec=ServerlessSpec(cloud=self.cloud, region=self.region),
            )
        return pc.Index(self.index_name)

    def upsert_documents(self, docs, embedder, namespace: str) -> None:
        self.init_index()
        embeddings = embedder.get_embeddings()
        try:
            from langchain_pinecone import PineconeVectorStore
        except ImportError as exc:
            raise ImportError(
                "langchain-pinecone is required. Run `pip install -r requirements.txt`."
            ) from exc
        vectorstore = PineconeVectorStore.from_existing_index(
            index_name=self.index_name,
            embedding=embeddings,
            text_key="text",
            namespace=namespace,
        )
        vectorstore.add_documents(documents=docs, namespace=namespace)
        logger.info("Upserted %s documents into namespace %s", len(docs), namespace)

    def get_retriever(self, embedder, namespace: str, k: int = 5):
        self.init_index()
        embeddings = embedder.get_embeddings()
        try:
            from langchain_pinecone import PineconeVectorStore
        except ImportError as exc:
            raise ImportError(
                "langchain-pinecone is required. Run `pip install -r requirements.txt`."
            ) from exc
        vectorstore = PineconeVectorStore.from_existing_index(
            index_name=self.index_name,
            embedding=embeddings,
            text_key="text",
            namespace=namespace,
        )
        return vectorstore.as_retriever(search_kwargs={"k": k, "namespace": namespace})

    def delete_namespace(self, namespace: str) -> None:
        index = self.init_index()
        try:
            index.delete(delete_all=True, namespace=namespace)
            logger.info("Deleted namespace %s", namespace)
        except Exception as exc:
            if "Namespace not found" in str(exc):
                logger.info("Namespace %s does not exist yet; skipping delete.", namespace)
            else:
                logger.warning("Failed to delete namespace %s: %s", namespace, exc)
