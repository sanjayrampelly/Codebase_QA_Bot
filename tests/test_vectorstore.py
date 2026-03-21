import os
import time

import pytest
from langchain_core.documents import Document

from app.embedder import CodeEmbedder
from app.vectorstore import PineconeStore


def test_vectorstore_roundtrip():
    if not os.getenv("PINECONE_API_KEY"):
        pytest.skip("PINECONE_API_KEY not set")

    index_name = os.getenv("PINECONE_INDEX_NAME", "codebase-qna")
    namespace = f"test-{int(time.time())}"

    store = PineconeStore(index_name=index_name)
    embedder = CodeEmbedder()

    docs = [
        Document(page_content="Auth logic lives in src/auth.py", metadata={"file_path": "src/auth.py"})
    ]

    store.delete_namespace(namespace)
    store.upsert_documents(docs, embedder, namespace=namespace)

    retriever = store.get_retriever(embedder, namespace=namespace, k=1)
    results = retriever.invoke("Where is auth?")

    assert len(results) > 0
