from __future__ import annotations

import os

from langchain_groq import ChatGroq

from utils.config import get_env


def get_llm():
    model = get_env("GROQ_MODEL", "llama3-70b-8192")
    return ChatGroq(
        api_key=get_env("GROQ_API_KEY"),
        model=model,
        temperature=0,
        max_tokens=1024,
    )
