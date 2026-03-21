from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from langchain_community.document_loaders import TextLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

try:
    from langchain_text_splitters import Language
except Exception:  # pragma: no cover
    Language = None

from utils.file_filters import iter_code_files
from utils.github_utils import clone_repo
from utils.logger import get_logger

logger = get_logger(__name__)

LANGUAGE_BY_EXT = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".java": "java",
    ".cpp": "cpp",
    ".go": "go",
    ".rs": "rust",
    ".md": "markdown",
    ".txt": "text",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
}


@dataclass
class CodeIngestor:
    chunk_size: int = 1000
    chunk_overlap: int = 150

    def clone_repo(self, github_url: str) -> str:
        return clone_repo(github_url)

    def load_files(self, local_path: str, repo_url: Optional[str] = None) -> List[Document]:
        docs: List[Document] = []
        root = Path(local_path)
        for file_path in iter_code_files(root):
            rel_path = file_path.relative_to(root).as_posix()
            language = LANGUAGE_BY_EXT.get(file_path.suffix.lower(), "text")
            try:
                loader = TextLoader(
                    str(file_path), encoding="utf-8", autodetect_encoding=True
                )
            except TypeError:
                loader = TextLoader(str(file_path), encoding="utf-8")
            file_docs = loader.load()
            for doc in file_docs:
                doc.metadata.update(
                    {
                        "file_path": rel_path,
                        "file_name": file_path.name,
                        "file_name_lower": file_path.name.lower(),
                        "file_path_lower": rel_path.lower(),
                        "language": language,
                        "repo_url": repo_url or "",
                    }
                )
                docs.append(doc)
        logger.info("Loaded %s files", len(docs))
        return docs

    def _get_splitter_for_ext(self, ext: str) -> RecursiveCharacterTextSplitter:
        if Language is not None:
            if ext == ".py":
                return RecursiveCharacterTextSplitter.from_language(
                    language=Language.PYTHON,
                    chunk_size=self.chunk_size,
                    chunk_overlap=self.chunk_overlap,
                )
            if ext == ".js":
                return RecursiveCharacterTextSplitter.from_language(
                    language=Language.JS,
                    chunk_size=self.chunk_size,
                    chunk_overlap=self.chunk_overlap,
                )
            if ext == ".ts":
                return RecursiveCharacterTextSplitter.from_language(
                    language=Language.TS,
                    chunk_size=self.chunk_size,
                    chunk_overlap=self.chunk_overlap,
                )
        return RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )

    def chunk_documents(self, docs: List[Document]) -> List[Document]:
        chunked: List[Document] = []
        for doc in docs:
            ext = Path(doc.metadata.get("file_path", "")).suffix.lower()
            splitter = self._get_splitter_for_ext(ext)
            pieces = splitter.split_documents([doc])
            for idx, piece in enumerate(pieces):
                piece.metadata["chunk_index"] = idx
                chunked.append(piece)
        logger.info("Chunked into %s documents", len(chunked))
        return chunked

    def ingest(self, github_url: str) -> List[Document]:
        local_path = self.clone_repo(github_url)
        docs = self.load_files(local_path, repo_url=github_url)
        return self.chunk_documents(docs)
