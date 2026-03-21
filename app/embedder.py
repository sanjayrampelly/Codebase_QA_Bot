from __future__ import annotations

import os
from dataclasses import dataclass
from typing import ClassVar, List

from langchain_huggingface import HuggingFaceEmbeddings

from utils.config import get_env


@dataclass
class CodeEmbedder:
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    _shared_embeddings: ClassVar[dict[tuple[str, str, str], HuggingFaceEmbeddings]] = {}
    _embeddings: HuggingFaceEmbeddings | None = None

    def __post_init__(self) -> None:
        env_model = get_env("HUGGINGFACE_MODEL")
        if env_model:
            self.model_name = env_model

    def get_embeddings(self) -> HuggingFaceEmbeddings:
        if self._embeddings is not None:
            return self._embeddings
        cache_folder = os.getenv("HF_HOME") or os.path.join(os.getcwd(), ".hf_cache")
        model_kwargs = {}
        hf_token = get_env("HUGGINGFACE_API_KEY")
        if hf_token:
            model_kwargs["token"] = hf_token
        cache_key = (self.model_name, cache_folder, hf_token or "")
        if cache_key in self._shared_embeddings:
            self._embeddings = self._shared_embeddings[cache_key]
            return self._embeddings
        self._embeddings = HuggingFaceEmbeddings(
            model_name=self.model_name,
            cache_folder=cache_folder,
            model_kwargs=model_kwargs,
        )
        self._shared_embeddings[cache_key] = self._embeddings
        return self._embeddings

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        embeddings = self.get_embeddings()
        return embeddings.embed_documents(texts)

    def embed_query(self, query: str) -> List[float]:
        embeddings = self.get_embeddings()
        return embeddings.embed_query(query)
