# Codebase Q&A Bot

Codebase Q&A Bot is a retrieval-augmented generation (RAG) application that indexes a GitHub repository and lets you ask natural-language questions about the codebase. Answers are grounded in source files and returned with file-level citations so you can trace where the response came from.

The project is built with LangChain for orchestration, Pinecone for vector search, Hugging Face sentence-transformer embeddings, Groq for low-latency LLM inference, and Streamlit for the UI.

## What It Does

- Clone a public GitHub repository into a temporary workspace
- Load supported source and text files from the repository
- Chunk files into retrieval-friendly LangChain documents
- Generate embeddings with a Hugging Face model
- Store vectors in Pinecone using the repository URL as the namespace
- Retrieve relevant chunks and answer questions with Groq
- Return answers with file citations
- Boost retrieval when the question explicitly mentions a file like `requirements.txt`, `README.md`, or a path

## Tech Stack

- `LangChain`: ingestion flow, retriever integration, prompt orchestration
- `LangChain Pinecone`: vector store integration
- `Pinecone`: hosted vector database
- `Hugging Face`: embeddings via `sentence-transformers`
- `Groq`: LLM backend for answer generation
- `Streamlit`: web UI
- `GitPython`: repository cloning
- `python-dotenv`: local environment and secrets loading

## Project Structure

- `app/`
  Core application logic
- `app/ingestor.py`
  Clones repositories, loads files, chunks documents, attaches metadata
- `app/embedder.py`
  Loads and caches the Hugging Face embeddings model
- `app/vectorstore.py`
  Creates and connects to Pinecone, upserts documents, builds retrievers
- `app/llm.py`
  Configures the Groq chat model
- `app/rag_chain.py`
  Formats retrieved context, applies file-aware retrieval boosting, runs the answer chain
- `ui/streamlit_app.py`
  Streamlit UI for indexing and asking questions
- `utils/`
  Shared helpers
- `utils/github_utils.py`
  Validates and clones GitHub repositories
- `utils/file_filters.py`
  Controls which file types are indexed
- `utils/config.py`
  Loads environment variables and normalizes config values
- `tests/`
  Local and integration-style tests

## Supported Files

The ingestor currently indexes these file types:

- `.py`
- `.js`
- `.ts`
- `.java`
- `.cpp`
- `.go`
- `.rs`
- `.md`
- `.txt`
- `.json`
- `.yaml`
- `.yml`

Directories like `.git`, `node_modules`, `venv`, `.venv`, `dist`, `build`, and `__pycache__` are skipped. Files ending in `.lock` are also skipped.

## How It Works

1. The user enters a GitHub repository URL in the Streamlit UI.
2. The repository is cloned locally into a temp directory.
3. Supported files are loaded and converted into LangChain `Document` objects.
4. Each document is chunked and enriched with metadata such as:
   `file_path`, `file_name`, `language`, `repo_url`, and `chunk_index`
5. Chunks are embedded with a Hugging Face sentence-transformer model.
6. Embeddings are stored in Pinecone under a namespace derived from the repository URL.
7. When a user asks a question, Pinecone retrieves matching chunks.
8. If the question names a file explicitly, retrieval is boosted toward chunks from that file.
9. Groq generates the answer using only the retrieved context.

## Setup

### 1. Create and activate a virtual environment

PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```powershell
pip install -r requirements.txt
```

### 3. Configure environment variables

Create a `.env` file in the project root. You can start from `.env.example`.

Required and supported keys:

```env
PINECONE_API_KEY=
PINECONE_INDEX_NAME=codebase-qna
GROQ_API_KEY=
GROQ_MODEL=llama3-70b-8192
HUGGINGFACE_API_KEY=
HUGGINGFACE_MODEL=sentence-transformers/all-MiniLM-L6-v2
LOG_LEVEL=INFO
```

Notes:

- `PINECONE_INDEX_NAME` controls the Pinecone index used by the app.
- `HUGGINGFACE_API_KEY` is optional for public models, but recommended to avoid stricter anonymous rate limits.
- The app normalizes some env edge cases, including BOM-prefixed `.env` keys and null-like values.

### 4. Start the app

```powershell
streamlit run ui/streamlit_app.py
```

Streamlit usually opens at:

```text
http://localhost:8501
```

## Using the App

1. Enter a public GitHub repository URL.
2. Click `Index Repo`.
3. Wait for the repository to be cloned, chunked, embedded, and uploaded to Pinecone.
4. Ask a question about the codebase.
5. Review the answer and cited source files.

The UI also supports:

- `Re-index` for refreshing an already indexed repository
- a small in-session chat history
- a debug view for retrieved chunks

## Example Questions

- `Where is authentication implemented?`
- `How are routes configured?`
- `What dependencies are used in requirements.txt?`
- `Which file defines the database connection?`
- `What environment variables does this project expect?`

## Testing

Run the test suite with:

```powershell
pytest tests -q
```

What to expect:

- local tests run without external services
- Pinecone and Groq integration tests are skipped when API keys are not set

## Current Behavior and Notes

- Pinecone indexes are auto-created if missing.
- Repository URLs are used as Pinecone namespaces.
- Explicit file mentions like `requirements.txt` and `README.md` are retrieval-boosted.
- The embeddings model is cached to reduce repeated reloads in Streamlit.
- On the first run, model download and embedding initialization can take noticeably longer.

## Re-indexing Matters

When ingestion metadata changes, previously indexed repositories do not automatically gain the new metadata in Pinecone. If you pull code changes that affect retrieval behavior, re-index the repository from the UI so Pinecone stores the updated document metadata.

## Limitations

- The current GitHub flow is designed for public repositories.
- Retrieval quality depends on chunking, embeddings, and the phrasing of the question.
- Very large repositories may take longer to embed and upload.
- This project does not yet implement advanced retry policies or background jobs for long-running indexing tasks.

## Future Improvements

- Better support for private repositories
- Hybrid retrieval with semantic plus keyword search
- Stronger repository-level caching
- Background indexing workers
- Deployment-ready auth and usage controls
- More structured answer formatting in the UI
