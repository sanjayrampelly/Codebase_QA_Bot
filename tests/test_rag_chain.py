import os
import time

import pytest
from langchain_core.documents import Document

from app.embedder import CodeEmbedder
from app.llm import get_llm
from app.rag_chain import CodeQAChain, resolve_documents
from app.vectorstore import PineconeStore


class FakeVectorStore:
    def similarity_search(self, query, k=4, filter=None):
        if filter == {"file_name_lower": {"$eq": "requirements.txt"}}:
            return [
                Document(
                    page_content="langchain\nstreamlit\npytest",
                    metadata={
                        "file_path": "requirements.txt",
                        "file_name": "requirements.txt",
                        "file_name_lower": "requirements.txt",
                        "chunk_index": 0,
                    },
                )
            ]
        return []


class FakeRetriever:
    def __init__(self):
        self.vectorstore = FakeVectorStore()
        self.search_kwargs = {"k": 2}

    def invoke(self, question):
        return [
            Document(
                page_content="ROOT_URLCONF = 'core.urls'",
                metadata={"file_path": "core/settings.py", "chunk_index": 0},
            )
        ]


def test_rag_chain_answer():
    if not os.getenv("PINECONE_API_KEY") or not os.getenv("GROQ_API_KEY"):
        pytest.skip("Pinecone or Groq API key not set")

    index_name = os.getenv("PINECONE_INDEX_NAME", "codebase-qna")
    namespace = f"test-rag-{int(time.time())}"

    store = PineconeStore(index_name=index_name)
    embedder = CodeEmbedder()

    docs = [
        Document(
            page_content="def login(user):\n    return True",
            metadata={"file_path": "src/auth.py"},
        )
    ]
    store.delete_namespace(namespace)
    store.upsert_documents(docs, embedder, namespace=namespace)

    retriever = store.get_retriever(embedder, namespace=namespace, k=1)
    llm = get_llm()
    chain = CodeQAChain()

    result = chain.ask("Where is the login logic?", retriever, llm)

    assert isinstance(result["answer"], str)
    assert len(result["answer"]) > 0
    assert len(result["sources"]) > 0


def test_resolve_documents_boosts_explicit_file_queries():
    docs = resolve_documents("What dependencies are in requirements.txt?", FakeRetriever())

    assert len(docs) >= 2
    assert docs[0].metadata["file_path"] == "requirements.txt"
