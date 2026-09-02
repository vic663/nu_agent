"""Provider-agnostic chat-model factory.

Model selection is by a single string ``provider:model`` (LangChain's
``init_chat_model`` convention), e.g.

- ``anthropic:claude-sonnet-4-5``      (needs ``ANTHROPIC_API_KEY``)
- ``openai:gpt-4o``                    (needs ``OPENAI_API_KEY``)
- ``openai:llama3.1``                  with ``OPENAI_BASE_URL=http://localhost:11434/v1`` (Ollama / vLLM —
                                       any OpenAI-compatible server, i.e. fully on-premise)

so the same workflow runs against a hosted model on a laptop and against a
local model on an air-gapped cluster.
"""

from __future__ import annotations

import os

from langchain_core.language_models import BaseChatModel

DEFAULT_MODEL = "anthropic:claude-sonnet-4-5"


def get_chat_model(model: str | None = None, temperature: float = 0.0, **kwargs) -> BaseChatModel:
    from langchain.chat_models import init_chat_model

    spec = model or os.environ.get("NUAGENT_LLM_MODEL", DEFAULT_MODEL)
    provider, _, name = spec.partition(":")
    if not name:  # bare model name -> let LangChain infer the provider
        return init_chat_model(spec, temperature=temperature, **kwargs)
    extra = dict(kwargs)
    if provider == "openai" and os.environ.get("OPENAI_BASE_URL"):
        extra.setdefault("base_url", os.environ["OPENAI_BASE_URL"])
        extra.setdefault("api_key", os.environ.get("OPENAI_API_KEY", "not-needed"))
    return init_chat_model(name, model_provider=provider, temperature=temperature, **extra)
