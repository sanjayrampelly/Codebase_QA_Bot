import os
import tempfile
from pathlib import Path

import pytest

from app.ingestor import CodeIngestor


def test_ingestor_local_repo():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "main.py").write_text("def hello():\n    return 'hi'\n", encoding="utf-8")
        (root / "README.md").write_text("# Sample\n", encoding="utf-8")

        ingestor = CodeIngestor(chunk_size=200, chunk_overlap=20)
        docs = ingestor.ingest(str(root))

        assert len(docs) > 0
        for doc in docs:
            assert "file_path" in doc.metadata
            assert "file_name" in doc.metadata
            assert "language" in doc.metadata
            assert "chunk_index" in doc.metadata
