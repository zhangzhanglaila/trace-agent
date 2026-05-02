"""
LangChain adapter — one line to trace any LangChain agent.

    from agenttrace.adapters.langchain import enable
    enable()

This patches BaseChatModel.invoke() on langchain_core, so EVERY
LangChain agent (including LangGraph, langchain_openai, langchain_anthropic)
is automatically traced — no code changes needed.

Under the hood it wraps the existing patch_langchain() instrumentation,
which captures model name, prompt, response, and semantic type for every
LLM call in the execution graph.
"""

from ..instrument.auto import patch_langchain, unpatch_langchain
from ..enable import enable as _enable


def enable(port: int = 8765, auto_attach: bool = True):
    """
    One-line LangChain tracing.

    Call once at the top of your script, before creating any agents:

        from agenttrace.adapters.langchain import enable
        enable()

    Args:
        port: UI server port (default 8765).
        auto_attach: Register this process so it appears as "Connected"
                     in the DevTools UI (like Chrome DevTools for agents).
    """
    patch_langchain()
    _enable(port=port, auto_attach=auto_attach)
