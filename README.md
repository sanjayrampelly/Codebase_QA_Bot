# Codebase Q&A Bot


Codebase Q&A Bot is a production-style RAG application for indexing GitHub repositories and asking grounded questions about the codebase. It now includes a FastAPI backend with Swagger docs, custom JWT authentication, role-based access control, repository-level authorization, and a Streamlit frontend that talks to the backend over HTTP.

## What The Project Does

- Index public GitHub repositories into Pinecone
- Chunk and embed code/text files with LangChain + Hugging Face
- Answer repository-specific questions with Groq-backed RAG
- Return file-level citations with answers
- Support custom JWT auth with login, refresh, logout, and registration
- Support RBAC for admin vs viewer/editor-style access
- Support repository-level access grants
- Expose backend APIs through Swagger UI and ReDoc
- Let the Streamlit UI use the backend instead of calling core services directly

## Current Architecture

The app now has two layers:

1. `FastAPI backend`
   Handles authentication, authorization, repository management, indexing, Q&A, audit logs, and Swagger docs.
2. `Streamlit frontend`
   Handles login/register UX, repository selection, chat, and admin workflows by calling backend APIs.

High-level flow:

1. User logs in or registers through Streamlit or Swagger
2. Backend issues custom JWT access and refresh tokens
3. User indexes a repository through the backend
4. Backend clones the repo, chunks documents, embeds them, and stores vectors in Pinecone
5. User asks questions against a selected repository
6. Backend enforces permissions and repository access before running retrieval + generation

## Architecture Diagram

```text
+-------------------+         +-------------------+         +------------------------+
|       User        | <-----> |   Streamlit UI    | <-----> |     FastAPI Backend    |
+-------------------+         +-------------------+         +------------------------+
                                                                     |            |
                                                                     |            |
                                                        +------------+            +------------------+
                                                        |                                              |
                                                        v                                              v
                                           +------------------------+                    +------------------------+
                                           |   JWT Auth + RBAC      |                    |  Repository Services   |
                                           +------------------------+                    +------------------------+
                                                        |                                              |
                                                        v                                              v
                                           +------------------------+                    +------------------------+
                                           | SQLite / SQLAlchemy DB |                    | GitHub Repo Ingestion  |
                                           +------------------------+                    +------------------------+
                                                                                                    |
                                                                                                    v
                                                                                       +------------------------+
                                                                                       | HF Embeddings Model    |
                                                                                       +------------------------+
                                                                                                    |
                                                                                                    v
                                                                                       +------------------------+
                                                                                       | Pinecone Vector Store  |
                                                                                       +------------------------+
                                                                                                    |
                                                                                                    v
                                                                                       +------------------------+
                                                                                       | RAG Chain + Groq LLM   |
                                                                                       +------------------------+
                                                                                                    |
                                                                                                    v
                                                                                       +------------------------+
                                                                                       | Answer + File Sources  |
                                                                                       +------------------------+
```

The diagram shows the current runtime flow:

- the user interacts with `Streamlit`
- `Streamlit` calls the `FastAPI` backend
- the backend handles `JWT auth`, `RBAC`, and repository access using the app database
- indexing pulls code from `GitHub`, chunks it, embeds it, and stores vectors in `Pinecone`
- question answering runs through the `RAG chain`, retrieves from `Pinecone`, and generates answers with `Groq`

## Tech Stack

- `FastAPI`: backend API and Swagger docs
- `Streamlit`: frontend UI
- `LangChain`: ingestion, retrieval, and RAG orchestration
- `langchain-pinecone`: Pinecone vector-store integration
- `Pinecone`: vector database
- `Hugging Face`: embeddings via sentence-transformer models
- `Groq`: LLM inference
- `SQLAlchemy`: app database models and persistence
- `PyJWT`: custom JWT creation and validation
- `bcrypt`: password hashing
- `GitPython`: repository cloning
- `python-dotenv`: environment loading

## Main Features

- Public GitHub repository ingestion
- File-aware retrieval boosting for direct file questions like `requirements.txt`
- Repository namespaces in Pinecone
- Custom JWT access + refresh token flow
- Self-registration for standard users
- Bootstrap admin user from `.env`
- Role-based permissions
- Repository-specific access control
- Audit logging
- Swagger-first backend development
- Streamlit UI backed by API calls

## Roles And Access

Current behavior is designed around role-based and repository-based access:

- `admin`
  Can manage users, roles, repository access, indexing, re-indexing, audit logs, and question answering.
- `viewer`
  Can view accessible repositories and ask questions where access is granted.
- Additional roles
  Can be added through the API/admin workflows.

Repository access is checked separately from global role permissions. A user may have permission to ask questions in general, but still needs access to the specific repository.

## Project Structure

- `api/main.py`
  FastAPI app with auth, users, roles, repositories, access control, Q&A, and audit endpoints
- `api/deps.py`
  Bearer token auth dependencies and permission guards
- `api/schemas.py`
  Request/response models for the API
- `app/ingestor.py`
  Repository cloning, file loading, chunking, and metadata enrichment
- `app/embedder.py`
  Hugging Face embedding model loading and caching
- `app/vectorstore.py`
  Pinecone store initialization, upsert, retrieval, namespace deletion
- `app/rag_chain.py`
  RAG answer assembly with file-aware retrieval behavior
- `app/llm.py`
  Groq LLM setup
- `app/db.py`
  SQLAlchemy engine/session/bootstrap helpers
- `app/models.py`
  Users, roles, permissions, repositories, refresh tokens, audit logs, and login attempts
- `app/auth.py`
  Login, logout, refresh, session restoration, throttling
- `app/jwt_service.py`
  Custom JWT generation and decoding
- `app/authorization.py`
  Permission and role helper functions
- `app/repository_service.py`
  Repository record sync and repository access management
- `app/user_service.py`
  User creation, role assignment, bootstrap admin logic
- `app/audit.py`
  Audit event persistence and queries
- `ui/streamlit_app.py`
  Streamlit frontend using backend API calls
- `utils/api_client.py`
  API client used by Streamlit
- `utils/config.py`
  `.env` loading and normalization helpers
- `tests/`
  Ingestion and RAG-related tests
- `openapi.yaml`
  API spec file for preview and iteration
- `AUTH_RBAC_PLAN.md`
  JWT/RBAC implementation plan
- `IMPLEMENTATION.md`
  Phase-by-phase implementation notes

## Supported Repository Files

The ingestor currently indexes:

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

Skipped directories include:

- `.git`
- `node_modules`
- `venv`
- `.venv`
- `dist`
- `build`
- `__pycache__`

Files ending in `.lock` are skipped.

## Environment Variables

Create a `.env` file in the project root. Start from `.env.example`.

```env
PINECONE_API_KEY=
PINECONE_INDEX_NAME=codebase-qna
GROQ_API_KEY=
GROQ_MODEL=llama3-70b-8192
HUGGINGFACE_API_KEY=
HUGGINGFACE_MODEL=sentence-transformers/all-MiniLM-L6-v2
API_BASE_URL=http://127.0.0.1:8000
DATABASE_URL=
JWT_SECRET_KEY=
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7
AUTH_SELF_REGISTRATION_ENABLED=true
AUTH_REGISTRATION_DEFAULT_ROLE=viewer
AUTH_MAX_LOGIN_ATTEMPTS=5
AUTH_LOCKOUT_MINUTES=15
INITIAL_ADMIN_USERNAME=
INITIAL_ADMIN_EMAIL=
INITIAL_ADMIN_PASSWORD=
LOG_LEVEL=INFO
```

Notes:

- `INITIAL_ADMIN_*` is used to bootstrap the first admin user if the database has no users yet.
- `AUTH_SELF_REGISTRATION_ENABLED=true` allows public registration through `/auth/register`.
- `API_BASE_URL` is used by Streamlit to call the backend.
- `HUGGINGFACE_API_KEY` is recommended to reduce anonymous rate limits.
- `utils/config.py` normalizes BOM-prefixed keys and null-like values in `.env`.

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

### 3. Configure `.env`

Copy `.env.example` to `.env` and fill in your keys and auth settings.

At minimum you will typically want:

- `PINECONE_API_KEY`
- `PINECONE_INDEX_NAME`
- `GROQ_API_KEY`
- `GROQ_MODEL`
- `HUGGINGFACE_API_KEY` or public model access
- `JWT_SECRET_KEY`
- `INITIAL_ADMIN_USERNAME`
- `INITIAL_ADMIN_EMAIL`
- `INITIAL_ADMIN_PASSWORD`

## Run The Backend First

The frontend now depends on the API backend, so start FastAPI before Streamlit.

### Start FastAPI

```powershell
.\venv\Scripts\uvicorn.exe api.main:app --reload
```

Backend URLs:

- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`
- Health: `http://127.0.0.1:8000/health`

## Start The Streamlit UI

In a second terminal:

```powershell
.\venv\Scripts\Activate.ps1
streamlit run ui/streamlit_app.py
```

Streamlit usually opens at:

```text
http://localhost:8501
```

## Backend API Overview

Main endpoint groups:

- `Auth`
  - `POST /auth/login`
  - `POST /auth/register`
  - `POST /auth/refresh`
  - `POST /auth/logout`
  - `GET /auth/me`
- `Users`
  - `GET /users`
  - `POST /users`
  - `GET /users/{user_id}`
  - `PATCH /users/{user_id}`
  - `PUT /users/{user_id}/roles`
- `Roles`
  - `GET /roles`
  - `POST /roles`
- `Repositories`
  - `GET /repositories`
  - `POST /repositories`
  - `GET /repositories/{repository_id}`
  - `POST /repositories/{repository_id}/reindex`
- `Repository Access`
  - `GET /repositories/{repository_id}/access`
  - `POST /repositories/{repository_id}/access`
- `Q&A`
  - `POST /repositories/{repository_id}/questions`
- `Audit`
  - `GET /audit-logs`

## Streamlit UI Overview

The UI now supports:

- login and registration
- JWT-backed authenticated sessions
- repository dropdown for accessible repositories
- new repository indexing through the backend
- re-indexing for the selected repository
- question asking against the active repository
- response history
- optional retrieved-context display
- admin management panels for users, roles, repository access, and audit logs

If the backend is unavailable, the UI now shows a clearer error state instead of failing silently.

## Typical Usage Flow

### Standard user flow

1. Register through Swagger or Streamlit
2. Log in
3. Wait for an admin to grant repository access if needed
4. Select an accessible repository
5. Ask repository-specific questions

### Admin flow

1. Log in with the bootstrapped admin account
2. Index a repository
3. Grant repository access to users
4. Manage roles and users
5. Review audit logs

## Example Questions

- `Where is authentication implemented?`
- `How are routes configured?`
- `What dependencies are used in requirements.txt?`
- `Which file defines the database connection?`
- `What environment variables does this project expect?`

## Testing

Run tests with:

```powershell
pytest tests -q
```

Notes:

- Local tests can run without full external service access.
- Pinecone/Groq integration-style tests may skip when keys are missing.
- `pytest.ini` is used so tests can import the project correctly from the repo root.

## Current Notes

- Repository URLs are used as Pinecone namespaces.
- Re-indexing is important after ingestion metadata changes.
- File-aware retrieval boosting helps direct file questions.
- The embedding model is cached to reduce repeated load overhead.
- First-time embedding model downloads can take longer.
- Self-registration creates a standard non-admin user by default.
- Admin users are created from `.env` bootstrap config, not through public registration.

## Limitations

- Public GitHub repositories are the main supported flow today.
- Indexing is synchronous and can take time for large repositories.
- Background job workers are not yet implemented.
- Schema setup currently relies on SQLAlchemy bootstrap helpers instead of a full migration workflow.

## Related Docs

- `IMPLEMENTATION.md`
- `AUTH_RBAC_PLAN.md`
- `openapi.yaml`

## Future Improvements

- Private repository support
- Background indexing jobs
- Stronger migration management with Alembic
- More refined admin UX
- Better retry/backoff behavior for external providers
- Hybrid retrieval with semantic + keyword search
