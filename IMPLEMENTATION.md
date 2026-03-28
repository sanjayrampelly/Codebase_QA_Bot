# Phase Implementation Notes

This document records what has now been implemented for the custom JWT authentication, authorization, and RBAC roadmap.

Implemented scope:

- Phase 1: Database Foundation
- Phase 2: User And JWT Service Layer
- Phase 3: Login, Logout, And Streamlit Session Flow
- Phase 4: RBAC Enforcement
- Phase 5: Repository Ownership And Repository Access Control
- Phase 6: Admin Management Features
- Phase 7: Audit Logging And Security Hardening
- Swagger-enabled FastAPI backend

## Phase 1: Database Foundation

### What Was Implemented

- database connection setup in `app/db.py`
- SQLAlchemy models in `app/models.py`
- automatic schema creation with `init_db()`
- default roles and permissions seeding in `app/user_service.py`
- initial admin bootstrap support using environment variables
- auth-related environment variables added to `.env.example`
- database files ignored in `.gitignore`

### Files Added

- `app/db.py`
- `app/models.py`

### Files Updated

- `app/user_service.py`
- `.env.example`
- `.gitignore`
- `requirements.txt`

### Database Coverage

The schema now includes:

- `users`
- `roles`
- `permissions`
- `user_roles`
- `role_permissions`
- `repositories`
- `repository_access`
- `refresh_tokens`
- `audit_logs`
- `login_attempts`

### Notes

- The current implementation uses SQLAlchemy `create_all()` for schema creation.
- `alembic` was added as a dependency, but migration scripts have not been scaffolded yet.
- This keeps the Streamlit app moving quickly now, while leaving room to add real migrations next.

## Phase 2: User And JWT Service Layer

### What Was Implemented

- password hashing and verification using `bcrypt`
- user lookup by username or email
- custom JWT generation for:
  - access tokens
  - refresh tokens
- JWT validation with token type checking
- refresh token persistence in the database
- logout revocation
- session restoration from access token or refresh token
- refresh token rotation on refresh
- login attempt tracking for throttling

### Files Added

- `app/jwt_service.py`
- `app/auth.py`
- `app/audit.py`

### Files Updated

- `app/user_service.py`
- `requirements.txt`

### JWT Claims Implemented

- `sub`
- `username`
- `roles`
- `permissions`
- `token_type`
- `jti`
- `iat`
- `exp`

### Notes

- The app expects a proper `JWT_SECRET_KEY` from `.env`.
- For production use, the secret should be at least 32 bytes long.
- Refresh tokens now rotate when used to mint a new access token.

## Phase 3: Login, Logout, And Streamlit Session Flow

### What Was Implemented

- login screen before the main app is shown
- authenticated session tracking in `st.session_state`
- logout action in the sidebar
- automatic session restoration on rerun
- automatic refresh-token fallback when access token expires
- protected app rendering so unauthenticated users cannot use indexing or Q&A flows
- user identity, roles, and permissions shown in the UI
- repo/chat session reset when the user logs out or the session becomes invalid

### Files Updated

- `ui/streamlit_app.py`

### Session State Added

- `access_token`
- `refresh_token`
- `current_user`
- `auth_notice`

## Phase 4: RBAC Enforcement

### What Was Implemented

- permission helper layer in `app/authorization.py`
- global permission checks for:
  - indexing
  - re-indexing
  - asking questions
  - admin access
- deny-path audit logging for blocked actions
- UI button disabling based on permissions

### Files Added

- `app/authorization.py`

### Files Updated

- `ui/streamlit_app.py`

### Notes

- Role names are still available, but action gating is permission-driven.
- Current default role model:
  - `admin`
  - `editor`
  - `viewer`

## Phase 5: Repository Ownership And Repository Access Control

### What Was Implemented

- repository service layer in `app/repository_service.py`
- persistent repository records after indexing
- automatic access grant to the indexing user
- automatic admin access grant for indexed repositories
- database-driven repository dropdown based on user access
- repository-level checks before:
  - switching repos
  - re-indexing
  - asking questions
- repository access management helpers for admins

### Files Added

- `app/repository_service.py`

### Files Updated

- `ui/streamlit_app.py`

### Notes

- The dropdown is no longer intended to be just session memory.
- Accessible repositories are now rebuilt from database records each rerun.
- Existing Pinecone namespaces are treated as protected resources and must map back to an allowed repository record.

## Phase 6: Admin Management Features

### What Was Implemented

- admin panel in Streamlit
- user creation UI
- role assignment UI
- repository access grant/update UI
- role definition display
- audit log viewer in the admin panel

### Files Updated

- `ui/streamlit_app.py`
- `app/user_service.py`
- `app/repository_service.py`
- `app/audit.py`

### Notes

- Admin features are intentionally simple and Streamlit-native for now.
- The UI is enough to manage users, roles, and repository grants without building a separate backend admin app yet.

## Phase 7: Audit Logging And Security Hardening

### What Was Implemented

- centralized audit event writing through `app/audit.py`
- audit records for:
  - login success
  - login failure
  - logout
  - refresh token rotation
  - permission denied
  - repository indexing
  - repository re-indexing
  - repository access grants
  - question asking
  - admin user creation
  - admin role updates
- refresh token rotation
- login attempt throttling using `login_attempts`

### Files Updated

- `app/auth.py`
- `app/audit.py`
- `ui/streamlit_app.py`
- `.env.example`

### Notes

- Login throttling is currently identifier-based and uses recent failed attempts within a configurable time window.
- Secret rotation planning is still a documentation concern; the code remains on `HS256` for now.
- Migration scaffolding is still pending even though the schema and hardening tables are in place.

## FastAPI Backend And Swagger

### What Was Implemented

- FastAPI backend entrypoint in `api/main.py`
- request/response schemas in `api/schemas.py`
- JWT bearer auth dependencies in `api/deps.py`
- Swagger UI via FastAPI `/docs`
- ReDoc via FastAPI `/redoc`

### Backend Endpoints Implemented

- auth:
  - `POST /auth/register`
  - `POST /auth/login`
  - `POST /auth/refresh`
  - `POST /auth/logout`
  - `GET /auth/me`
- users:
  - `GET /users`
  - `POST /users`
  - `GET /users/{user_id}`
  - `PATCH /users/{user_id}`
  - `PUT /users/{user_id}/roles`
- roles:
  - `GET /roles`
  - `POST /roles`
- repositories:
  - `GET /repositories`
  - `POST /repositories`
  - `GET /repositories/{repository_id}`
  - `POST /repositories/{repository_id}/reindex`
- repository access:
  - `GET /repositories/{repository_id}/access`
  - `POST /repositories/{repository_id}/access`
- q&a:
  - `POST /repositories/{repository_id}/questions`
- audit:
  - `GET /audit-logs`
- utility:
  - `GET /health`

### Notes

- The backend reuses the same auth, repository, and RAG services already built for the app.
- Heavy RAG imports were kept lazy in `api/main.py` so the API and Swagger docs start faster.
- The generated FastAPI OpenAPI schema is now the practical backend contract for local development.
- `openapi.yaml` still exists as the planning/spec artifact, but the running backend docs now come from the FastAPI app itself.

## Environment Variables Needed

At minimum, the current implementation expects:

- `JWT_SECRET_KEY`
- `INITIAL_ADMIN_USERNAME`
- `INITIAL_ADMIN_PASSWORD`

Recommended:

- `INITIAL_ADMIN_EMAIL`
- `DATABASE_URL`
- `JWT_ALGORITHM`
- `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`
- `JWT_REFRESH_TOKEN_EXPIRE_DAYS`
- `AUTH_SELF_REGISTRATION_ENABLED`
- `AUTH_REGISTRATION_DEFAULT_ROLE`
- `AUTH_MAX_LOGIN_ATTEMPTS`
- `AUTH_LOCKOUT_MINUTES`

## First-Time Setup

1. Add these values to `.env`:

```env
JWT_SECRET_KEY=replace-with-a-long-random-secret
INITIAL_ADMIN_USERNAME=admin
INITIAL_ADMIN_PASSWORD=change-me
INITIAL_ADMIN_EMAIL=admin@example.com
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7
AUTH_SELF_REGISTRATION_ENABLED=true
AUTH_REGISTRATION_DEFAULT_ROLE=viewer
AUTH_MAX_LOGIN_ATTEMPTS=5
AUTH_LOCKOUT_MINUTES=15
```

2. Install updated dependencies:

```powershell
.\venv\Scripts\pip.exe install -r requirements.txt
```

3. Run the app:

```powershell
streamlit run ui/streamlit_app.py
```

4. Log in with the bootstrapped admin credentials.

5. Use the admin panel to:

- create more users
- assign roles
- grant repository access
- inspect audit activity

## Running The Swagger Backend

Run the backend from the project root:

```powershell
.\venv\Scripts\uvicorn.exe api.main:app --reload
```

Then open:

- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`
- Health check: `http://127.0.0.1:8000/health`

### Backend-First Workflow

If you want to validate auth and RBAC before using Streamlit, this is the clean order:

1. start the FastAPI backend
2. open Swagger UI
3. call `POST /auth/login`
4. copy the bearer token into Swagger `Authorize`
5. exercise admin, repository, and Q&A endpoints
6. move to the Streamlit UI only after the backend behavior looks right

## Validation Performed

The following validation was completed during implementation:

- syntax compilation with:

```powershell
python -m compileall app ui utils
```

- runtime import and auth bootstrap checks
- local login / refresh rotation / logout validation
- local repository record + access grant validation
- backend import validation for `api.main`
- FastAPI route registration and OpenAPI generation checks

## Current Practical Limitations

- The schema currently relies on SQLAlchemy `create_all()` instead of real Alembic migrations.
- The admin UI is functional but still intentionally basic.
- The application still uses Streamlit session state for token storage, which is acceptable for the current internal app shape but not the final strongest production posture.
- `HS256` is still the active JWT signing strategy.
- The backend currently performs indexing synchronously in-request. For heavier production traffic, this should move to a background worker or job queue.

## Recommended Next Improvements

If we continue polishing from here, the best next moves are:

1. add real Alembic migrations
2. move auth/session handling behind a backend API with HTTP-only cookies
3. tighten secret management and optional `RS256` support
4. improve admin UX and access review flows
