import sys
from pathlib import Path

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.authorization import has_permission, is_admin
from utils.api_client import APIClient, APIClientError
from utils.config import get_env, load_environment
from utils.github_utils import normalize_repo_url
from utils.logger import get_logger

load_environment(PROJECT_ROOT)
logger = get_logger(__name__)

st.set_page_config(page_title="Codebase Q&A Bot", layout="wide")

API_BASE_URL = get_env("API_BASE_URL", "http://127.0.0.1:8000") or "http://127.0.0.1:8000"

SESSION_DEFAULTS = {
    "chat_history": [],
    "last_context": "",
    "repo_input": "",
    "active_repo_url": "",
    "active_repository_id": None,
    "repo_registry": {},
    "selected_repo_option": "",
    "access_token": None,
    "refresh_token": None,
    "current_user": None,
    "auth_notice": "",
}

for key, value in SESSION_DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value


@st.cache_resource
def get_api_client(base_url: str) -> APIClient:
    return APIClient(base_url=base_url)


client = get_api_client(API_BASE_URL)


def backend_ready() -> bool:
    try:
        client.health()
        return True
    except APIClientError:
        return False


def clear_active_repo() -> None:
    st.session_state.active_repo_url = ""
    st.session_state.active_repository_id = None
    st.session_state.selected_repo_option = ""
    st.session_state.last_context = ""


def reset_repo_state() -> None:
    st.session_state.chat_history = []
    st.session_state.last_context = ""
    st.session_state.repo_input = ""
    st.session_state.repo_registry = {}
    clear_active_repo()


def apply_auth_payload(payload: dict) -> None:
    st.session_state.access_token = payload.get("accessToken")
    st.session_state.refresh_token = payload.get("refreshToken")
    st.session_state.current_user = payload.get("user")
    st.session_state.auth_notice = ""


def clear_auth_state(*, revoke_refresh_token: bool) -> None:
    access_token = st.session_state.get("access_token")
    refresh_token = st.session_state.get("refresh_token")
    if revoke_refresh_token and access_token and refresh_token:
        try:
            client.logout(access_token, refresh_token)
        except APIClientError:
            logger.exception("Failed to revoke refresh token during logout.")
    st.session_state.access_token = None
    st.session_state.refresh_token = None
    st.session_state.current_user = None
    reset_repo_state()


def sync_auth_session() -> bool:
    access_token = st.session_state.get("access_token")
    refresh_token = st.session_state.get("refresh_token")
    if not access_token:
        st.session_state.current_user = None
        return False

    try:
        response = client.me(access_token)
        st.session_state.current_user = response.get("user")
        return True
    except APIClientError as exc:
        if exc.status_code is None:
            st.session_state.auth_notice = str(exc)
            return st.session_state.current_user is not None

        if exc.status_code == 401 and refresh_token:
            try:
                refreshed = client.refresh(refresh_token)
                st.session_state.access_token = refreshed.get("accessToken")
                if refreshed.get("refreshToken"):
                    st.session_state.refresh_token = refreshed.get("refreshToken")
                me_payload = client.me(st.session_state.access_token)
                st.session_state.current_user = me_payload.get("user")
                return True
            except APIClientError as refresh_exc:
                clear_auth_state(revoke_refresh_token=False)
                st.session_state.auth_notice = str(refresh_exc)
                return False

        clear_auth_state(revoke_refresh_token=False)
        st.session_state.auth_notice = str(exc)
        return False


def refresh_repo_registry() -> None:
    current_user = st.session_state.current_user
    access_token = st.session_state.get("access_token")
    if not current_user or not access_token or not has_permission(current_user, "repo:view"):
        st.session_state.repo_registry = {}
        clear_active_repo()
        return

    try:
        payload = client.list_repositories(access_token)
    except APIClientError as exc:
        st.warning(f"Could not load repositories from backend: {exc}")
        st.session_state.repo_registry = {}
        return

    repo_registry = {}
    for repo in payload.get("items", []):
        repo_registry[repo["repoUrl"]] = {
            "id": repo["id"],
            "namespace": repo["namespace"],
            "chunk_count": repo.get("chunkCount") or 0,
            "access_level": repo.get("accessLevel") or "unknown",
            "can_view": repo.get("canView", False),
            "can_ask": repo.get("canAsk", False),
            "can_index": repo.get("canIndex", False),
            "can_reindex": repo.get("canReindex", False),
        }
    st.session_state.repo_registry = repo_registry

    active_repo_url = st.session_state.active_repo_url
    if active_repo_url and active_repo_url not in repo_registry:
        clear_active_repo()
    elif active_repo_url:
        sync_active_repo(active_repo_url)


def sync_active_repo(url: str) -> None:
    repo_info = st.session_state.repo_registry.get(url)
    if repo_info is None:
        return
    st.session_state.active_repo_url = url
    st.session_state.active_repository_id = repo_info["id"]


def get_active_repo_info():
    active_repo_url = st.session_state.active_repo_url
    if not active_repo_url:
        return None
    repo_info = st.session_state.repo_registry.get(active_repo_url)
    if repo_info is None:
        return None
    return {"repo_url": active_repo_url, **repo_info}


def handle_repo_selection() -> None:
    selected_repo = st.session_state.selected_repo_option
    if selected_repo:
        sync_active_repo(selected_repo)
        return
    clear_active_repo()


def format_repo_option(repo: str) -> str:
    if not repo:
        return "Select a repository"

    repo_info = st.session_state.repo_registry.get(repo, {})
    chunk_count = repo_info.get("chunk_count", 0)
    access_level = repo_info.get("access_level", "unknown")
    return f"{repo} ({chunk_count} chunks, {access_level})"


def render_auth_view() -> None:
    st.title("Codebase Q&A Bot")
    st.caption(f"Backend API: `{API_BASE_URL}`")

    if st.session_state.auth_notice:
        st.warning(st.session_state.auth_notice)
        st.session_state.auth_notice = ""

    if not backend_ready():
        st.error(
            "Backend API is not reachable. Start the FastAPI server first with "
            "`uvicorn api.main:app --reload`."
        )
        st.stop()

    login_tab, register_tab = st.tabs(["Login", "Register"])

    with login_tab:
        with st.form("login_form"):
            identifier = st.text_input("Username or email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login")

        if submitted:
            try:
                payload = client.login(identifier, password)
                apply_auth_payload(payload)
                st.rerun()
            except APIClientError as exc:
                st.error(str(exc))

    with register_tab:
        st.caption("Self-registration creates a standard viewer account.")
        with st.form("register_form"):
            username = st.text_input("New username")
            email = st.text_input("Email")
            password = st.text_input("New password", type="password")
            registered = st.form_submit_button("Register")

        if registered:
            try:
                payload = client.register(username, email, password)
                apply_auth_payload(payload)
                st.success("Registration succeeded. You are now logged in.")
                st.rerun()
            except APIClientError as exc:
                st.error(str(exc))


def index_repo(url: str, force_reindex: bool = False) -> None:
    access_token = st.session_state.get("access_token")
    if not access_token:
        st.error("Please log in again.")
        return

    normalized_url = normalize_repo_url(url) if url else ""
    existing_repo = st.session_state.repo_registry.get(normalized_url) if normalized_url else None

    if not force_reindex and existing_repo:
        sync_active_repo(normalized_url)
        st.info(f"Switched to existing repo `{normalized_url}`.")
        return

    try:
        with st.spinner("Sending indexing request to backend..."):
            if force_reindex:
                active_repo = get_active_repo_info()
                if not active_repo:
                    st.warning("Select a repository to re-index first.")
                    return
                response = client.reindex_repository(access_token, active_repo["id"])
                target_url = active_repo["repo_url"]
            else:
                response = client.index_repository(access_token, url, force_reindex=False)
                target_url = response["repoUrl"]
    except APIClientError as exc:
        st.error(str(exc))
        return

    refresh_repo_registry()
    if target_url in st.session_state.repo_registry:
        sync_active_repo(target_url)
    st.success(response.get("message") or "Repository operation completed.")


def render_admin_panel(current_user: dict) -> None:
    if not is_admin(current_user):
        return

    access_token = st.session_state.get("access_token")
    if not access_token:
        return

    try:
        users_payload = client.list_users(access_token)
        roles_payload = client.list_roles(access_token)
    except APIClientError as exc:
        st.error(f"Could not load admin data: {exc}")
        return

    users = users_payload.get("items", [])
    roles = roles_payload.get("items", [])
    role_names = [role["name"] for role in roles]

    st.divider()
    st.subheader("Admin")
    user_tab, role_tab, repo_tab, audit_tab = st.tabs(
        ["Users", "Roles", "Repo Access", "Audit Logs"]
    )

    with user_tab:
        st.markdown("### Create User")
        with st.form("admin_create_user_form"):
            new_username = st.text_input("Username")
            new_email = st.text_input("Email")
            new_password = st.text_input("Temporary password", type="password")
            new_roles = st.multiselect("Roles", options=role_names, default=["viewer"])
            create_user_submitted = st.form_submit_button("Create User")

        if create_user_submitted:
            try:
                client.create_user(
                    access_token,
                    {
                        "username": new_username,
                        "email": new_email,
                        "password": new_password,
                        "roleNames": new_roles,
                    },
                )
                st.success(f"Created user `{new_username}`.")
                st.rerun()
            except APIClientError as exc:
                st.error(str(exc))

        st.markdown("### Existing Users")
        if users:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "user_id": user["id"],
                            "username": user["username"],
                            "email": user.get("email"),
                            "roles": ", ".join(role["name"] for role in user.get("roles", [])),
                            "is_active": user.get("isActive"),
                        }
                        for user in users
                    ]
                ),
                use_container_width=True,
            )

            selected_username = st.selectbox(
                "Select user to update roles",
                options=[user["username"] for user in users],
                key="admin_selected_user",
            )
            selected_user = next((user for user in users if user["username"] == selected_username), None)
            current_roles = [role["name"] for role in selected_user.get("roles", [])] if selected_user else []
            updated_roles = st.multiselect(
                "Assign roles",
                options=role_names,
                default=current_roles,
                key="admin_role_update_selection",
            )
            if st.button("Update User Roles"):
                try:
                    client.update_user_roles(access_token, selected_user["id"], updated_roles)
                    st.success(f"Updated roles for `{selected_username}`.")
                    st.rerun()
                except APIClientError as exc:
                    st.error(str(exc))
        else:
            st.info("No users found.")

    with role_tab:
        st.markdown("### Role Definitions")
        if roles:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "role": role["name"],
                            "description": role.get("description"),
                            "permissions": ", ".join(permission["name"] for permission in role.get("permissions", [])),
                        }
                        for role in roles
                    ]
                ),
                use_container_width=True,
            )
        else:
            st.info("No roles available.")

    with repo_tab:
        st.markdown("### Grant Repository Access")
        repository_options = sorted(st.session_state.repo_registry.keys())
        user_options = {f"{user['username']} ({user['id']})": user["id"] for user in users}
        if repository_options and user_options:
            selected_repo_for_grant = st.selectbox(
                "Repository",
                options=repository_options,
                key="admin_repo_grant_repo",
            )
            selected_user_for_grant = st.selectbox(
                "User",
                options=list(user_options.keys()),
                key="admin_repo_grant_user",
            )
            access_level = st.selectbox(
                "Access level",
                options=["viewer", "editor", "admin"],
                key="admin_repo_grant_level",
            )
            if st.button("Grant / Update Access"):
                try:
                    repository_id = st.session_state.repo_registry[selected_repo_for_grant]["id"]
                    client.grant_repository_access(
                        access_token,
                        repository_id,
                        user_options[selected_user_for_grant],
                        access_level,
                    )
                    st.success("Repository access updated.")
                    st.rerun()
                except APIClientError as exc:
                    st.error(str(exc))

            try:
                repository_id = st.session_state.repo_registry[selected_repo_for_grant]["id"]
                access_rows = client.get_repository_access(access_token, repository_id).get("items", [])
            except APIClientError as exc:
                st.error(str(exc))
                access_rows = []
            if access_rows:
                st.markdown("### Current Access")
                st.dataframe(pd.DataFrame(access_rows), use_container_width=True)
        else:
            st.info("You need at least one repository and one user to manage access.")

    with audit_tab:
        st.markdown("### Recent Audit Events")
        try:
            audit_rows = client.get_audit_logs(access_token).get("items", [])
        except APIClientError as exc:
            st.error(str(exc))
            audit_rows = []
        if audit_rows:
            st.dataframe(pd.DataFrame(audit_rows), use_container_width=True)
        else:
            st.info("No audit events recorded yet.")


authenticated = sync_auth_session()
if not authenticated:
    render_auth_view()
    st.stop()

if not backend_ready():
    st.title("Codebase Q&A Bot")
    st.caption(f"Backend API: `{API_BASE_URL}`")
    st.error(
        "You are logged in, but the backend API is not reachable right now. "
        "Make sure FastAPI is running, then refresh the page."
    )
    if st.session_state.auth_notice:
        st.caption(st.session_state.auth_notice)
    with st.sidebar:
        if st.button("Logout"):
            clear_auth_state(revoke_refresh_token=False)
            st.rerun()
    st.stop()

refresh_repo_registry()
current_user = st.session_state.current_user or {}

st.title("Codebase Q&A Bot")
st.caption(f"Backend API: `{API_BASE_URL}`")
st.caption(f"Signed in as `{current_user.get('username', 'unknown')}`")

with st.sidebar:
    st.header("Session")
    st.caption("User: " + current_user.get("username", "unknown"))
    roles = current_user.get("roles") or []
    st.caption("Roles: " + (", ".join(roles) if roles else "none"))
    permissions = current_user.get("permissions") or []
    st.caption("Permissions: " + (", ".join(sorted(permissions)) if permissions else "none"))
    if st.button("Logout"):
        clear_auth_state(revoke_refresh_token=True)
        st.rerun()

    st.divider()
    st.header("Settings")
    k = st.slider("Top-K", min_value=1, max_value=10, value=5)
    include_context = st.checkbox("Include retrieved context", value=False)
    if st.button("Refresh Repositories"):
        refresh_repo_registry()
        st.rerun()

repo_options = [""] + list(st.session_state.repo_registry.keys())
if st.session_state.active_repo_url in repo_options:
    st.session_state.selected_repo_option = st.session_state.active_repo_url
if st.session_state.selected_repo_option not in repo_options:
    st.session_state.selected_repo_option = ""

st.selectbox(
    "Accessible Repositories",
    options=repo_options,
    key="selected_repo_option",
    on_change=handle_repo_selection,
    format_func=format_repo_option,
)

repo_url = st.text_input("GitHub Repo URL For New Indexing", key="repo_input")
can_index = has_permission(current_user, "repo:index")
can_reindex = has_permission(current_user, "repo:reindex")
col1, col2 = st.columns([1, 1])

with col1:
    if st.button("Index Repo", disabled=not can_index):
        index_repo(repo_url, force_reindex=False)

with col2:
    if st.button("Re-index", disabled=not can_reindex):
        active_repo = get_active_repo_info()
        if active_repo:
            index_repo(active_repo["repo_url"], force_reindex=True)
        else:
            st.warning("Nothing to re-index yet.")

active_repo_info = get_active_repo_info()
if active_repo_info:
    st.caption(
        f"Active repo: {st.session_state.active_repo_url} | "
        f"Indexed chunks: {active_repo_info['chunk_count']} | "
        f"Access: {active_repo_info['access_level']}"
    )

st.divider()

question = st.text_input("Ask a question about the codebase")

if st.button("Ask", disabled=not has_permission(current_user, "repo:ask")):
    active_repo_info = get_active_repo_info()
    if not active_repo_info:
        st.warning("Please select an accessible repository first.")
    elif not question:
        st.warning("Please enter a question.")
    else:
        try:
            with st.spinner(f"Thinking about {active_repo_info['repo_url']}..."):
                result = client.ask_question(
                    st.session_state.access_token,
                    active_repo_info["id"],
                    question,
                    top_k=k,
                    include_context=include_context,
                )
        except APIClientError as exc:
            st.error(str(exc))
        else:
            elapsed_ms = result.get("responseTimeMs", 0)
            st.session_state.last_context = result.get("context") or ""
            st.session_state.chat_history.append(
                {
                    "repo_url": active_repo_info["repo_url"],
                    "question": question,
                    "answer": result["answer"],
                    "sources": result["sources"],
                    "time": elapsed_ms / 1000 if elapsed_ms else 0,
                }
            )
            st.session_state.chat_history = st.session_state.chat_history[-5:]

if st.session_state.chat_history:
    st.subheader("Answer")
    latest = st.session_state.chat_history[-1]
    st.caption("Repository: " + latest["repo_url"])
    st.write(latest["answer"])
    if latest["sources"]:
        st.caption("Sources: " + ", ".join(latest["sources"]))
    st.caption(f"Response time: {latest['time']:.2f}s")

    st.subheader("History")
    for item in reversed(st.session_state.chat_history[:-1]):
        st.caption("Repository: " + item["repo_url"])
        st.markdown(f"**Q:** {item['question']}")
        st.markdown(f"**A:** {item['answer']}")
        if item["sources"]:
            st.caption("Sources: " + ", ".join(item["sources"]))
        st.caption(f"Response time: {item['time']:.2f}s")

if include_context and st.session_state.last_context:
    with st.expander("View retrieved context"):
        st.text(st.session_state.last_context)

render_admin_panel(current_user)
