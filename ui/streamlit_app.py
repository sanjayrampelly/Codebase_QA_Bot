import os
import sys
import time
from pathlib import Path

import streamlit as st
from git.exc import GitCommandError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.embedder import CodeEmbedder
from app.ingestor import CodeIngestor
from app.llm import get_llm
from app.rag_chain import CodeQAChain
from app.vectorstore import PineconeStore
from utils.config import get_env, load_environment
from utils.github_utils import is_valid_github_url, normalize_repo_url
from utils.logger import get_logger

load_environment(PROJECT_ROOT)
logger = get_logger(__name__)

st.set_page_config(page_title="Codebase Q&A Bot", layout="wide")

if "namespace" not in st.session_state:
    st.session_state.namespace = ""
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "indexed" not in st.session_state:
    st.session_state.indexed = False
if "last_context" not in st.session_state:
    st.session_state.last_context = ""
if "repo_url" not in st.session_state:
    st.session_state.repo_url = ""
if "repo_input" not in st.session_state:
    st.session_state.repo_input = ""
if "active_repo_url" not in st.session_state:
    st.session_state.active_repo_url = ""
if "repo_registry" not in st.session_state:
    st.session_state.repo_registry = {}
if "selected_repo_option" not in st.session_state:
    st.session_state.selected_repo_option = ""
if "index_requests" not in st.session_state:
    st.session_state.index_requests = 0


@st.cache_resource
def get_embedder() -> CodeEmbedder:
    return CodeEmbedder()


@st.cache_resource
def get_store(index_name: str) -> PineconeStore:
    return PineconeStore(index_name=index_name)


embedder = get_embedder()
store = get_store(get_env("PINECONE_INDEX_NAME", "codebase-qna"))


def sync_active_repo(url: str) -> None:
    if not url:
        return
    repo_info = st.session_state.repo_registry.get(url)
    if not repo_info:
        return
    st.session_state.active_repo_url = url
    st.session_state.repo_url = url
    st.session_state.namespace = repo_info["namespace"]
    st.session_state.indexed = True


def get_active_repo_info():
    active_repo_url = st.session_state.active_repo_url
    if not active_repo_url:
        return None
    return st.session_state.repo_registry.get(active_repo_url)


def handle_repo_selection() -> None:
    selected_repo = st.session_state.selected_repo_option
    if selected_repo:
        sync_active_repo(selected_repo)


def index_repo(url: str, force_reindex: bool = False):
    if not url:
        st.error("Please provide a GitHub repo URL.")
        return
    if not is_valid_github_url(url):
        st.error("Invalid GitHub URL. Please provide a public repo URL.")
        return

    normalized_url = normalize_repo_url(url)
    existing_repo = st.session_state.repo_registry.get(normalized_url)
    if existing_repo and not force_reindex:
        sync_active_repo(normalized_url)
        st.info(
            f"Switched to already indexed repo. Using {existing_repo['chunk_count']} existing chunks."
        )
        return

    if st.session_state.index_requests >= 3:
        st.error("Indexing limit reached for this session. Please refresh to start a new session.")
        return

    namespace = normalize_repo_url(url)
    ingestor = CodeIngestor()
    try:
        with st.spinner("Cloning and indexing repository..."):
            docs = ingestor.ingest(url)
            store.delete_namespace(namespace)
            store.upsert_documents(docs, embedder, namespace=namespace)
    except ValueError as exc:
        st.error(str(exc))
        return
    except GitCommandError:
        st.error("GitHub clone failed. If this is a private repository, provide access or use a public URL.")
        return
    except Exception as exc:
        logger.exception("Repository indexing failed for %s", url)
        message = str(exc).lower()
        if "quota" in message or "limit" in message:
            st.error("Vector store quota or rate limit was reached. Please try again later.")
        else:
            st.error("Indexing failed. Please check your API keys and try again.")
        return

    st.session_state.repo_registry[normalized_url] = {
        "namespace": namespace,
        "chunk_count": len(docs),
    }
    sync_active_repo(normalized_url)
    st.session_state.index_requests += 1
    st.success(f"Indexed {len(docs)} chunks for {normalized_url}.")


st.title("Codebase Q&A Bot")

with st.sidebar:
    st.header("Settings")
    k = st.slider("Top-K", min_value=1, max_value=10, value=5)
    debug = st.checkbox("Debug: show retrieved chunks", value=False)

repo_options = [""] + list(st.session_state.repo_registry.keys())
if st.session_state.active_repo_url in repo_options:
    st.session_state.selected_repo_option = st.session_state.active_repo_url
if st.session_state.selected_repo_option not in repo_options:
    st.session_state.selected_repo_option = ""

st.selectbox(
    "Indexed Repositories",
    options=repo_options,
    key="selected_repo_option",
    on_change=handle_repo_selection,
    format_func=lambda repo: (
        "Select an indexed repo"
        if not repo
        else f"{repo} ({st.session_state.repo_registry[repo]['chunk_count']} chunks)"
    ),
)

repo_url = st.text_input("GitHub Repo URL For New Indexing", key="repo_input")
col1, col2 = st.columns([1, 1])

with col1:
    if st.button("Index Repo"):
        index_repo(repo_url, force_reindex=False)

with col2:
    if st.button("Re-index"):
        if st.session_state.active_repo_url:
            index_repo(st.session_state.active_repo_url, force_reindex=True)
        else:
            st.warning("Nothing to re-index yet.")

active_repo_info = get_active_repo_info()
if active_repo_info:
    st.caption(
        f"Active repo: {st.session_state.active_repo_url} | Indexed chunks: {active_repo_info['chunk_count']}"
    )

st.divider()

question = st.text_input("Ask a question about the codebase")

if st.button("Ask"):
    active_repo_info = get_active_repo_info()
    if not active_repo_info:
        st.warning("Please index or select a repository first.")
    elif not question:
        st.warning("Please enter a question.")
    else:
        try:
            retriever = store.get_retriever(
                embedder,
                active_repo_info["namespace"],
                k=k,
            )
            llm = get_llm()
            chain = CodeQAChain()
            start = time.time()
            with st.spinner(f"Thinking about {st.session_state.active_repo_url}..."):
                result = chain.ask(question, retriever, llm)
            elapsed = time.time() - start
        except Exception as exc:
            logger.exception(
                "Question answering failed for namespace %s", active_repo_info["namespace"]
            )
            message = str(exc).lower()
            if "rate limit" in message or "too many requests" in message:
                st.error("The LLM is rate limited right now. Please retry in a moment.")
            else:
                st.error(
                    "Question answering failed. Please verify your Pinecone and Groq configuration."
                )
        else:
            st.session_state.last_context = result.get("context", "")
            st.session_state.chat_history.append(
                {
                    "repo_url": st.session_state.active_repo_url,
                    "question": question,
                    "answer": result["answer"],
                    "sources": result["sources"],
                    "time": elapsed,
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

if debug and st.session_state.last_context:
    with st.expander("View retrieved chunks"):
        st.text(st.session_state.last_context)
