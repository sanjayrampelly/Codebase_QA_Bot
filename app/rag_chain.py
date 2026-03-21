from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Dict, List

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate

from utils.logger import get_logger

logger = get_logger(__name__)
FILE_HINT_PATTERN = re.compile(r"(?:[\w.-]+[\\/])*[\w.-]*\.[A-Za-z0-9]+")
SPECIAL_FILE_HINTS = ("makefile", "dockerfile")

PROMPT_TEMPLATE = """
You are an expert code assistant. Answer questions about the codebase
using ONLY the provided context. Always mention the file name where
the relevant code was found.

If the answer is not in the context, say:
"I couldn't find relevant code for that in this repository."

Context:
{context}

Question: {question}

Answer (with file references):
""".strip()


def format_docs(docs) -> str:
    lines = []
    for doc in docs:
        path = doc.metadata.get("file_path", "unknown")
        snippet = doc.page_content
        lines.append(f"FILE: {path}\n{snippet}")
    return "\n\n".join(lines)


def extract_file_hints(question: str) -> List[str]:
    hints = set()
    for match in FILE_HINT_PATTERN.findall(question):
        cleaned = match.strip("`'\".,:;()[]{}<>")
        if not cleaned:
            continue
        normalized = cleaned.replace("\\", "/").lstrip("./").lower()
        if normalized:
            hints.add(normalized)
            hints.add(normalized.split("/")[-1])
    lower_question = question.lower()
    for special_name in SPECIAL_FILE_HINTS:
        if re.search(rf"\b{re.escape(special_name)}\b", lower_question):
            hints.add(special_name)
    return sorted(hint for hint in hints if hint)


def _doc_key(doc) -> tuple[str, int, str]:
    metadata = doc.metadata
    return (
        metadata.get("file_path", ""),
        metadata.get("chunk_index", -1),
        doc.page_content[:80],
    )


def _search_with_filter(vectorstore, question: str, metadata_filter: dict, k: int) -> List:
    try:
        return vectorstore.similarity_search(question, k=k, filter=metadata_filter)
    except Exception as exc:
        logger.debug("Filtered similarity search failed for %s: %s", metadata_filter, exc)
        return []


def resolve_documents(question: str, retriever) -> List:
    docs = list(retriever.invoke(question))
    vectorstore = getattr(retriever, "vectorstore", None)
    file_hints = extract_file_hints(question)
    if not vectorstore or not file_hints:
        return docs

    search_k = max(int(getattr(retriever, "search_kwargs", {}).get("k", 5)), 4)
    boosted_docs = []
    for hint in file_hints:
        boosted_docs.extend(
            _search_with_filter(
                vectorstore,
                question,
                {"file_name_lower": {"$eq": hint}},
                search_k,
            )
        )
        boosted_docs.extend(
            _search_with_filter(
                vectorstore,
                question,
                {"file_path_lower": {"$eq": hint}},
                search_k,
            )
        )

    if boosted_docs:
        logger.info("Boosted retrieval using file hints: %s", ", ".join(file_hints))

    merged_docs = []
    seen = set()
    for doc in boosted_docs + docs:
        key = _doc_key(doc)
        if key in seen:
            continue
        seen.add(key)
        merged_docs.append(doc)
    return merged_docs


@dataclass
class CodeQAChain:
    prompt: PromptTemplate = field(
        default_factory=lambda: PromptTemplate(
            input_variables=["context", "question"],
            template=PROMPT_TEMPLATE,
        )
    )

    def build_chain(self, llm):
        return self.prompt | llm | StrOutputParser()

    def ask(self, question: str, retriever, llm) -> Dict[str, List[str]]:
        docs = resolve_documents(question, retriever)
        context = format_docs(docs)
        chain = self.build_chain(llm)
        answer = chain.invoke({"context": context, "question": question})
        sources = []
        for doc in docs:
            path = doc.metadata.get("file_path")
            if path and path not in sources:
                sources.append(path)
        logger.info("Answered question with %s sources", len(sources))
        return {"answer": answer, "sources": sources, "context": context}
