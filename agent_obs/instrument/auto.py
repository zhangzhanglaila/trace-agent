"""
Auto-Instrumentation: Decorators and hooks with semantic typing.

Usage:
    from agent_obs.instrument import trace_step, trace_tool, trace_llm, auto_trace
    from agent_obs.trace_core import SEM

    @trace_llm("classify_intent")
    def classify(query: str) -> str: ...

    @trace_tool("weather")
    def weather_api(city: str) -> str: ...

    auto_trace()  # one-line LLM patch
"""
import functools
from typing import Optional, Any, Dict, Callable

from ..trace_core import get_trace_context, trace_span, SEM


# ============================================================
# Helpers
# ============================================================

def _safe_truncate(s: str, max_len: int) -> str:
    if len(s) <= max_len:
        return s
    return s[:max_len] + "..."


# ============================================================
# trace_step — function-level decorator
# ============================================================

def trace_step(name: str = None, semantic_type: str = SEM.CHAIN,
               capture_args: bool = True, capture_result: bool = True,
               produces_key: str = None, consumes_keys: Dict = None):
    """
    Decorator: auto-trace a function call as a semantic span.

    Args:
        name: Span name (default: function name)
        semantic_type: SEM.LLM / SEM.TOOL / SEM.DECISION / etc.
        capture_args: Include function arguments
        capture_result: Include return value
        produces_key: If set, auto-declare `produces = {key: result}`
        consumes_keys: If set, declare `consumes = {key: args[key]}`

    Usage:
        @trace_step("classify", SEM.LLM, produces_key="intent")
        def classify(prompt: str) -> str: ...
    """
    def decorator(func):
        step_name = name or func.__name__

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            ctx = get_trace_context()
            if ctx is None:
                return func(*args, **kwargs)

            inputs = {}
            if capture_args:
                # Use kwarg names if available
                if kwargs:
                    inputs = {k: _safe_truncate(str(v), 300) for k, v in kwargs.items()}
                else:
                    inputs["args"] = _safe_truncate(str(args), 300)

            with trace_span(step_name, semantic_type, inputs=inputs) as span:
                result = func(*args, **kwargs)
                if capture_result and span.get("step_id"):
                    span["outputs"] = {"result": _safe_truncate(str(result), 500)}
                    if produces_key:
                        span["produces"] = {produces_key: result}
                return result

        return wrapper
    return decorator


# ============================================================
# Specialized decorators
# ============================================================

def trace_tool(name: str = None, produces_key: str = None):
    """Decorator for tool functions with semantic typing."""
    return trace_step(
        name=name,
        semantic_type=SEM.TOOL,
        capture_args=True,
        capture_result=True,
        produces_key=produces_key or name,
    )


def trace_llm(name: str = "llm_call", produces_key: str = None):
    """Decorator for LLM calls with semantic typing."""
    return trace_step(
        name=name,
        semantic_type=SEM.LLM,
        capture_args=True,
        capture_result=True,
        produces_key=produces_key or "llm_response",
    )


# ============================================================
# OpenAI auto-patch
# ============================================================

_OPENAI_PATCHED = False
_openai_originals = {}


def patch_openai():
    """Monkey-patch OpenAI ChatCompletion.create for auto-tracing."""
    global _OPENAI_PATCHED
    if _OPENAI_PATCHED:
        return

    try:
        import openai
    except ImportError:
        return

    if hasattr(openai, "ChatCompletion") and hasattr(openai.ChatCompletion, "create"):
        _openai_originals["chat_create"] = openai.ChatCompletion.create
        original = openai.ChatCompletion.create

        @functools.wraps(original)
        def traced_create(*args, **kwargs):
            ctx = get_trace_context()
            if ctx is None:
                return original(*args, **kwargs)

            messages = kwargs.get("messages", [])
            model = kwargs.get("model", "unknown")
            prompt_preview = _safe_truncate(str(messages), 500)

            with trace_span(f"llm:{model}", SEM.LLM,
                           inputs={"model": model, "messages": prompt_preview}) as span:
                result = original(*args, **kwargs)
                if hasattr(result, "choices") and result.choices:
                    content = result.choices[0].message.content
                    span["outputs"] = {"result": _safe_truncate(str(content), 500)}
                    span["produces"] = {"llm_response": content}
                return result

        openai.ChatCompletion.create = traced_create
        _OPENAI_PATCHED = True


def unpatch_openai():
    """Restore original OpenAI functions."""
    global _OPENAI_PATCHED
    try:
        import openai
        for name, original in _openai_originals.items():
            if name == "chat_create":
                openai.ChatCompletion.create = original
        _openai_originals.clear()
        _OPENAI_PATCHED = False
    except ImportError:
        pass


# ============================================================
# auto_trace — one-line setup
# ============================================================

def auto_trace(patch_llm: bool = True):
    """
    One-line auto-instrumentation.

    Call at the start of your agent script:
        from agent_obs.instrument import auto_trace
        auto_trace()
    """
    if patch_llm:
        patch_openai()
