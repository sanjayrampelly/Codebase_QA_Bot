# Custom JWT Authentication, Authorization, and RBAC Plan

## Goal

Add user functionality to the Codebase Q&A Bot with:

- custom JWT-based authentication
- authorization checks on protected actions
- role-based access control
- per-user repository access
- auditability for security-sensitive actions

This document is a plan only. It does not implement the feature.

## Why This Matters

The current app is effectively single-user and trusts Streamlit session state for access flow. Any user of the current UI can:

- index repositories
- re-index repositories
- switch repositories in the dropdown
- ask questions against active Pinecone namespaces

Once multiple users are involved, the app needs to answer:

- who is the current user
- whether the user is authenticated
- which repositories the user can see
- which repositories the user can index or re-index
- which repositories the user can ask questions against
- who can manage users, roles, and access grants

## Recommended Direction

The best path for this app is:

1. add a small relational database for users, roles, permissions, repositories, and audit logs
2. implement custom JWT creation and verification inside the app
3. keep short-lived access tokens and longer-lived refresh tokens
4. enforce authorization checks before indexing, switching repos, re-indexing, and asking questions
5. move repository visibility from Streamlit session memory into persistent repository access records
6. add admin tooling for user and role management

## Why Custom JWT

Custom JWT is a good fit here because:

- you control token claims
- you can embed role and permission data in the token
- it works well if you later split the UI and backend
- it keeps the authentication model explicit and app-owned
- it gives you a clean path toward API endpoints later

## High-Level Architecture

### Core Components

- `User`
  authenticated application user
- `Role`
  named set of permissions
- `Permission`
  granular capability such as `repo:index` or `repo:ask`
- `RepositoryRecord`
  persisted record for an indexed repository and its namespace
- `RepositoryAccess`
  mapping of which users can view, ask, index, or re-index a repo
- `JWT Service`
  creates, validates, refreshes, and revokes tokens
- `AuditLog`
  stores login, token, indexing, and permission events

### Suggested Persistence

Start with:

- SQLite for development
- PostgreSQL for production

Suggested libraries:

- `SQLAlchemy`
- `alembic`
- `bcrypt` or `passlib[bcrypt]`
- `PyJWT`

## JWT Token Design

## Token Types

Use two token types:

- `access_token`
  short-lived token used for authorization checks
- `refresh_token`
  longer-lived token used to issue a new access token

Recommended lifetimes:

- access token: `15 to 30 minutes`
- refresh token: `7 to 30 days`

## JWT Claims

Include at least:

- `sub`
  user id
- `username`
- `roles`
- `permissions`
- `token_type`
  `access` or `refresh`
- `jti`
  token id for tracking and revocation
- `iat`
- `exp`

Optional later:

- `email`
- `is_active`
- `repo_scope`
  if you want short-lived repo-scoped tokens in the future

## Signing Strategy

Initial recommendation:

- algorithm: `HS256`
- a strong secret from environment variables

Later upgrade path:

- `RS256` with key rotation

## Refresh and Revocation Strategy

Refresh tokens should be tracked in persistent storage.

Recommended:

- store refresh token `jti`
- store `user_id`
- store `expires_at`
- store `is_revoked`

On logout:

- revoke the refresh token record
- clear auth state from the UI session

Optional hardening:

- rotate refresh tokens on each refresh
- blacklist active access token `jti` for immediate revocation on sensitive actions

## Suggested Data Model

## `users`

- `id`
- `username`
- `email`
- `password_hash`
- `is_active`
- `created_at`
- `last_login_at`

## `roles`

- `id`
- `name`
- `description`

## `permissions`

- `id`
- `name`
- `description`

## `user_roles`

- `user_id`
- `role_id`

## `role_permissions`

- `role_id`
- `permission_id`

## `repositories`

- `id`
- `repo_url`
- `namespace`
- `display_name`
- `indexed_by_user_id`
- `created_at`
- `last_indexed_at`
- `chunk_count`
- `is_active`

## `repository_access`

- `id`
- `repository_id`
- `user_id`
- `access_level`

Optional explicit booleans if you want finer control:

- `can_view`
- `can_ask`
- `can_index`
- `can_reindex`

## `refresh_tokens`

- `id`
- `user_id`
- `jti`
- `expires_at`
- `is_revoked`
- `created_at`

## `audit_logs`

- `id`
- `user_id`
- `action`
- `repo_url`
- `namespace`
- `details`
- `created_at`

## Recommended Roles

Start with three roles:

## `admin`

- manage users
- manage roles
- grant repository access
- index and re-index any repository
- ask questions on any allowed repository
- inspect audit logs

## `editor`

- index repositories they own or are allowed to manage
- re-index repositories they are allowed to manage
- ask questions on repositories they are allowed to access

## `viewer`

- view repositories they can access
- ask questions on repositories they can access
- cannot index or re-index

## Recommended Permissions

Use explicit permissions instead of hardcoding role names:

- `user:manage`
- `role:manage`
- `repo:view`
- `repo:index`
- `repo:reindex`
- `repo:delete`
- `repo:ask`
- `audit:view`
- `token:refresh`

## Authentication Flow Plan

## Login Flow

1. User opens the app.
2. App shows a login screen if there is no valid access token.
3. User submits username or email and password.
4. App verifies password hash from the database.
5. App generates:
   - an access token
   - a refresh token
6. App stores auth state for the current Streamlit session.
7. App renders only the authorized UI for that user.

## Access Token Validation Flow

Every protected action should:

1. read the current access token
2. decode and validate signature, expiry, and token type
3. load user identity from claims
4. optionally reload user and repository access from the database for fresh authorization checks

## Refresh Flow

1. Access token expires.
2. App validates refresh token.
3. App checks refresh token record is not revoked.
4. App issues a new access token.
5. Optional:
   rotate refresh token and revoke the previous one.

## Logout Flow

1. Revoke refresh token record.
2. Clear token state from Streamlit session.
3. Return user to login screen.

## JWT Storage Plan In Streamlit

Initial pragmatic approach:

- store access token in `st.session_state`
- store refresh token in `st.session_state`
- validate access token before each protected UI action

Important note:

- this is acceptable for an initial internal version
- for stronger production security, move token handling behind a backend service and HTTP-only cookies later

## Authorization Plan

Authorization should happen at two levels:

## 1. App-Level Authorization

Controls whether the user can:

- access the app
- see admin UI
- manage users and roles

## 2. Repository-Level Authorization

Controls whether the user can:

- see a repository in the dropdown
- index that repository
- re-index that repository
- ask questions against that repository

This matters because two users may have different access to the same Pinecone namespace.

## Enforcement Points In Current App

Checks will need to be added before:

- `index_repo(...)` in `ui/streamlit_app.py`
- repo dropdown population in `ui/streamlit_app.py`
- repository switching in `ui/streamlit_app.py`
- `Re-index` handling in `ui/streamlit_app.py`
- `Ask` flow in `ui/streamlit_app.py`
- any future admin views

## Repository Ownership and Access Plan

When a user indexes a repository:

- create or update a `repositories` record
- persist the namespace
- record which user indexed it
- grant that user access automatically
- optionally grant admins access automatically

The repo dropdown should no longer be driven only by Streamlit session state. It should be built from:

- current authenticated user
- repository access records from the database

## Pinecone Namespace Security Plan

Keep using repo URL-derived namespaces, but never trust a namespace only because it appears in UI state.

Before querying Pinecone:

- validate the access token
- identify the user
- verify that the user has access to the repository record for that namespace

## UI Plan

## Login View

Add a login screen before the main app content:

- username or email
- password
- login button
- logout button after authentication
- expired session messaging
- refresh or re-login behavior

## Authenticated View

Show:

- current username
- current roles
- only repositories the user can access
- only actions the user is allowed to perform

## Admin View

Add an admin section for:

- creating users
- assigning roles
- granting repository access
- viewing audit logs
- revoking refresh tokens if needed

## Audit Logging Plan

Log at least:

- login success
- login failure
- logout
- access token validation failure
- refresh token issuance
- refresh token use
- refresh token revocation
- permission denied
- repository indexing
- repository re-indexing
- question asked

## Phase-Based Implementation Roadmap

This section is the implementation sequence to follow. Each phase is intended to be completed and validated before moving to the next one.

## Phase 0: Preparation And Design Freeze

### Goal

Lock the baseline decisions before writing auth code.

### Decisions To Finalize

- database choice for local development: `SQLite`
- production database target: `PostgreSQL`
- JWT algorithm for first release: `HS256`
- password hashing library: `passlib[bcrypt]` or `bcrypt`
- initial roles: `admin`, `editor`, `viewer`
- initial permission catalog
- bootstrap strategy for the first admin user

### Tasks

- confirm JWT claim structure
- confirm token lifetimes
- confirm table names and relationships
- confirm which current Streamlit actions become protected
- confirm naming for repository ownership and access levels

### Deliverable

- frozen scope for Phase 1 to Phase 5

### Exit Criteria

- no unresolved questions around schema, roles, or token design

## Phase 1: Database Foundation

### Goal

Introduce a persistent source of truth for users, roles, permissions, repositories, access grants, refresh tokens, and audit logs.

### Scope

- database connection setup
- SQLAlchemy models
- Alembic migrations
- seed data for roles and permissions

### Tasks

- create `app/db.py`
- create `app/models.py`
- define models for:
  - `users`
  - `roles`
  - `permissions`
  - `user_roles`
  - `role_permissions`
  - `repositories`
  - `repository_access`
  - `refresh_tokens`
  - `audit_logs`
- create migration setup
- add seed script or startup seeding for default roles and permissions
- add initial admin bootstrap plan

### Files Affected

- new: `app/db.py`
- new: `app/models.py`
- new: migration files
- update: `utils/config.py`
- update: `requirements.txt`
- update: `README.md`

### Deliverable

- working database schema with seeded permissions and roles

### Exit Criteria

- app can connect to the database
- migrations run cleanly
- default roles and permissions exist
- first admin bootstrap path is defined

## Phase 2: User And JWT Service Layer

### Goal

Create the reusable authentication layer that handles passwords, JWT creation, JWT validation, refresh token storage, and revocation.

### Scope

- password hashing
- credential verification
- access token generation
- refresh token generation
- token validation
- refresh token persistence
- logout revocation

### Tasks

- create `app/user_service.py`
- create `app/jwt_service.py`
- create `app/auth.py`
- implement password hashing helpers
- implement login credential verification
- implement JWT creation with:
  - `sub`
  - `username`
  - `roles`
  - `permissions`
  - `token_type`
  - `jti`
  - `iat`
  - `exp`
- implement access token verification
- implement refresh token verification
- store refresh token records in the database
- implement revoke-on-logout behavior

### Files Affected

- new: `app/user_service.py`
- new: `app/jwt_service.py`
- new: `app/auth.py`
- update: `utils/config.py`
- update: `requirements.txt`

### Deliverable

- reusable custom JWT service layer with database-backed refresh tokens

### Exit Criteria

- valid user can log in at the service layer
- access token can be created and validated
- refresh token can be created and validated
- logout can revoke refresh token state

## Phase 3: Login, Logout, And Streamlit Session Flow

### Goal

Integrate the JWT auth service into the Streamlit UI so users must authenticate before using the app.

### Scope

- login form
- logout action
- session token storage
- token refresh behavior
- expired session handling

### Tasks

- update `ui/streamlit_app.py` to show login view before app content
- store `access_token` and `refresh_token` in `st.session_state`
- validate access token before rendering protected sections
- add refresh path when access token expires
- clear session state on logout
- show current username and roles after login

### Files Affected

- update: `ui/streamlit_app.py`
- update: `app/auth.py`
- update: `app/jwt_service.py`

### Deliverable

- working end-to-end login/logout/refresh flow in Streamlit

### Exit Criteria

- anonymous user cannot use the app
- logged-in user can stay in session with access + refresh token flow
- expired or invalid tokens return the user to a safe auth state

## Phase 4: RBAC Enforcement

### Goal

Add permission-aware and role-aware access control to application actions.

### Scope

- permission helper functions
- role checks
- protected action guards

### Tasks

- create `app/authorization.py`
- implement helper methods such as:
  - `has_role(...)`
  - `has_permission(...)`
  - `require_permission(...)`
- define mapping between actions and required permissions
- gate these actions:
  - repo indexing
  - repo re-indexing
  - repo switching
  - question asking
  - admin screens
- define permission denied behavior in UI

### Files Affected

- new: `app/authorization.py`
- update: `ui/streamlit_app.py`
- update: `app/auth.py`

### Deliverable

- role-aware protected app behavior

### Exit Criteria

- viewer cannot index or re-index
- editor can act only within allowed permissions
- admin-only screens are hidden or blocked for non-admin users

## Phase 5: Repository Ownership And Repository Access Control

### Goal

Move repository visibility and repository permissions from Streamlit session memory into persistent database-backed access control.

### Scope

- persisted repository records
- per-user repository grants
- repo dropdown filtering
- namespace authorization checks

### Tasks

- create `app/repository_service.py`
- create `RepositoryRecord` creation/update logic on indexing
- create `RepositoryAccess` creation logic
- auto-grant access to indexing user
- optionally auto-grant access to admins
- filter repo dropdown from `repository_access`
- verify repository access before:
  - switching repos
  - indexing
  - re-indexing
  - Pinecone retrieval
  - question answering

### Files Affected

- new: `app/repository_service.py`
- update: `ui/streamlit_app.py`
- update: `app/vectorstore.py`
- update: `app/rag_chain.py`

### Deliverable

- per-user repo visibility and repo-level authorization

### Exit Criteria

- users see only repos they are allowed to access
- repo switching is permission-aware
- Pinecone namespace access is validated through repository records

## Phase 6: Admin Management Features

### Goal

Give administrators the tools required to manage users, roles, and repository grants.

### Scope

- user management UI
- role assignment UI
- repository access management UI
- audit log visibility

### Tasks

- add admin section in `ui/streamlit_app.py`
- create user creation and activation/deactivation flows
- create role assignment flows
- create repository access grant/revoke flows
- create audit log view
- optionally add refresh token revoke actions

### Files Affected

- update: `ui/streamlit_app.py`
- update: `app/user_service.py`
- update: `app/repository_service.py`
- new or update: `app/audit.py`

### Deliverable

- basic admin tooling for security and access management

### Exit Criteria

- admin can create users
- admin can assign roles
- admin can grant repo access
- admin can inspect audit activity

## Phase 7: Audit Logging And Security Hardening

### Goal

Make the system safer, more observable, and closer to production-grade behavior.

### Scope

- better audit coverage
- token lifecycle hardening
- brute-force protection
- secret management planning
- validation and failure handling

### Tasks

- centralize audit logging in `app/audit.py`
- log:
  - login success
  - login failure
  - logout
  - refresh use
  - refresh revocation
  - permission denied
  - repo index
  - repo re-index
  - question asked
- add refresh token rotation
- add login attempt throttling or lockout strategy
- add stronger validation and clearer user-facing auth errors
- add secret rotation notes for future `RS256`

### Files Affected

- new or update: `app/audit.py`
- update: `app/jwt_service.py`
- update: `app/auth.py`
- update: `ui/streamlit_app.py`
- update: `README.md`

### Deliverable

- production-hardened JWT auth model with stronger observability

### Exit Criteria

- critical auth and access events are auditable
- refresh tokens can be rotated and revoked
- login failure and invalid token behavior are clearly handled

## Suggested Sprint Grouping

If you want to execute this in smaller implementation batches, use this grouping:

### Sprint 1

- Phase 0
- Phase 1

### Sprint 2

- Phase 2
- Phase 3

### Sprint 3

- Phase 4
- Phase 5

### Sprint 4

- Phase 6
- Phase 7

## Recommended Order To Actually Code This

Use this exact sequence while implementing:

1. database connection and models
2. migrations and role/permission seeding
3. password hashing and user lookup
4. JWT create/validate helpers
5. refresh token persistence and revocation
6. login/logout/refresh Streamlit flow
7. authorization helper utilities
8. repository records and repository access grants
9. repo dropdown filtering by user access
10. permission checks on ask/index/re-index/switch
11. admin screens
12. audit logging and hardening

## Current Code Areas That Will Change

## New modules likely needed

- `app/auth.py`
- `app/jwt_service.py`
- `app/authorization.py`
- `app/models.py`
- `app/db.py`
- `app/user_service.py`
- `app/repository_service.py`
- `app/audit.py`

## Existing files that will be updated

- `ui/streamlit_app.py`
  add login flow, token-aware auth state, user-aware repo dropdown, authorization checks
- `app/vectorstore.py`
  validate namespace access through repository records before use
- `utils/config.py`
  add database and JWT config values
- `README.md`
  add setup instructions for database, admin bootstrap, and JWT config

## Environment Variables To Plan For

- `DATABASE_URL=`
- `JWT_SECRET_KEY=`
- `JWT_ALGORITHM=HS256`
- `JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30`
- `JWT_REFRESH_TOKEN_EXPIRE_DAYS=7`
- `INITIAL_ADMIN_USERNAME=`
- `INITIAL_ADMIN_PASSWORD=`

Optional later:

- `JWT_PRIVATE_KEY=`
- `JWT_PUBLIC_KEY=`

## Acceptance Criteria

The feature is complete when:

- users must log in to use the app
- the app issues and validates custom JWTs
- only authorized users can see repositories in the dropdown
- only authorized users can index or re-index repositories
- viewers can ask questions only on repositories they can access
- admins can manage users, roles, and access grants
- audit logs exist for important security actions

## Recommended Build Order

1. database and models
2. password hashing and JWT service
3. login/logout and refresh flow
4. role and permission helpers
5. repository ownership and access records
6. filtered repository dropdown
7. admin UI
8. audit logging and hardening

## Notes For This Streamlit App

- Streamlit is fine for a first JWT-enabled version, but it should not be the only source of truth for access decisions.
- JWTs should be validated by your own auth utilities on every protected action.
- repository access should be driven by database records, not just session memory
- Pinecone namespaces should be treated as protected resources
- this is a good fit for phased delivery: JWT auth first, then RBAC, then admin tooling
