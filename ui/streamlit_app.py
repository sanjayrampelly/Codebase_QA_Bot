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
if "index_requests" not in st.session_state:
    st.session_state.index_requests = 0

st.title("Codebase Q&A Bot")

with st.sidebar:
    st.header("Settings")
    k = st.slider("Top-K", min_value=1, max_value=10, value=5)
    debug = st.checkbox("Debug: show retrieved chunks", value=False)

repo_url = st.text_input("GitHub Repo URL", value=st.session_state.repo_url)
col1, col2 = st.columns([1, 1])

@st.cache_resource
def get_embedder() -> CodeEmbedder:
    return CodeEmbedder()


@st.cache_resource
def get_store(index_name: str) -> PineconeStore:
    return PineconeStore(index_name=index_name)


embedder = get_embedder()
store = get_store(get_env("PINECONE_INDEX_NAME", "codebase-qna"))


def index_repo(url: str):
    if not url:
        st.error("Please provide a GitHub repo URL.")
        return
    if not is_valid_github_url(url):
        st.error("Invalid GitHub URL. Please provide a public repo URL.")
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

    st.session_state.namespace = namespace
    st.session_state.repo_url = url
    st.session_state.indexed = True
    st.session_state.index_requests += 1
    st.success(f"Indexed {len(docs)} chunks.")


with col1:
    if st.button("Index Repo"):
        index_repo(repo_url)

with col2:
    if st.button("Re-index"):
        if st.session_state.namespace and st.session_state.repo_url:
            index_repo(st.session_state.repo_url)
        else:
            st.warning("Nothing to re-index yet.")

st.divider()

question = st.text_input("Ask a question about the codebase")

if st.button("Ask"):
    if not st.session_state.indexed:
        st.warning("Please index a repository first.")
    elif not question:
        st.warning("Please enter a question.")
    else:
        try:
            retriever = store.get_retriever(embedder, st.session_state.namespace, k=k)
            llm = get_llm()
            chain = CodeQAChain()
            start = time.time()
            with st.spinner("Thinking..."):
                result = chain.ask(question, retriever, llm)
            elapsed = time.time() - start
        except Exception as exc:
            logger.exception(
                "Question answering failed for namespace %s", st.session_state.namespace
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
    st.write(latest["answer"])
    if latest["sources"]:
        st.caption("Sources: " + ", ".join(latest["sources"]))
    st.caption(f"Response time: {latest['time']:.2f}s")

    st.subheader("History")
    for item in reversed(st.session_state.chat_history[:-1]):
        st.markdown(f"**Q:** {item['question']}")
        st.markdown(f"**A:** {item['answer']}")
        if item["sources"]:
            st.caption("Sources: " + ", ".join(item["sources"]))
        st.caption(f"Response time: {item['time']:.2f}s")

if debug and st.session_state.last_context:
    with st.expander("View retrieved chunks"):
        st.text(st.session_state.last_context)
