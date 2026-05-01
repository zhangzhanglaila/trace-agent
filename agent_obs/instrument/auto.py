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
import json
from typing import Optional, Any, Dict, Callable, List
from dataclasses import dataclass, field

from ..trace_core import get_trace_context, trace_span, SEM


# ============================================================
# Helpers
# ============================================================

def _safe_truncate(s: str, max_len: int) -> str:
    if len(s) <= max_len:
        return s
    return s[:max_len] + "..."


# ============================================================
# P3-1: Semantic Confidence System
# ============================================================

@dataclass
class SemanticSignal:
    """Typed, confidence-scored semantic classification.

    Replaces bare strings like SEM.LLM with evidence-backed signals.
    """
    type: str                              # SEM.LLM / SEM.TOOL / SEM.DECISION / SEM.CHAIN
    confidence: float                      # 0.0 - 1.0
    source: str                            # "explicit" | "pattern" | "runtime" | "combined"
    evidence: List[str] = field(default_factory=list)

    def __str__(self):
        return f"{self.type}(conf={self.confidence:.0%}, src={self.source})"

    def __repr__(self):
        return str(self)


# Pattern weights (weak signal — needs corroboration)
_PATTERN_WEIGHT = 0.65
_RUNTIME_WEIGHT = 0.85
_EXPLICIT_WEIGHT = 1.0

# LLM patterns: function names or module paths that indicate LLM calls
_LLM_FUNC_PATTERNS = [
    "llm", "chat", "completion", "generate", "predict", "classify",
    "summarize", "translate", "embed", "tokenize", "invoke",
]
_LLM_MODULE_PATTERNS = [
    "openai", "langchain", "anthropic", "gpt", "claude",
    "chatmodel", "chat_model", "basellm", "base_llm",
]

# Anti-patterns for LLM: functions that contain LLM keywords but aren't LLM calls
_LLM_ANTI_PATTERNS = [
    "history", "formatter", "format", "render", "display", "ui_",
    "cache", "store", "save", "load", "logger", "callback",
]

# Decision patterns: functions that evaluate conditions
_DECISION_FUNC_PATTERNS = [
    "is_", "should_", "check_", "validate_", "has_", "can_",
    "need_", "want_", "decide", "route", "branch", "condition",
    "guard", "filter", "choose", "select",
]

# Tool patterns: functions that perform external actions
_TOOL_FUNC_PATTERNS = [
    "search", "api", "tool", "call", "fetch", "get_", "query",
    "weather", "calculator", "database", "db_", "http", "request",
    "web_", "file_", "read_", "write_", "send_", "upload",
    "download", "scrape", "crawl", "parse", "extract",
]


def classify_semantic(func_name: str = None, module_name: str = None,
                      func: Callable = None, runtime_result: Any = None,
                      explicit_type: str = None) -> SemanticSignal:
    """
    Classify semantic type with confidence scoring.

    Evidence sources (in priority order):
    1. explicit_type: user specified @trace_llm etc. → confidence 1.0
    2. runtime_result: return value inspection → confidence 0.85
    3. pattern: function/module name matching → confidence 0.65

    Sources are combined for higher confidence when they agree.
    """
    evidence = []
    name = (func_name or "").lower()
    mod = (module_name or "").lower()
    if func is not None:
        mod = mod or getattr(func, "__module__", "").lower()

    # ── Source 1: Explicit annotation (highest confidence) ──
    if explicit_type and explicit_type != SEM.CHAIN:
        return SemanticSignal(
            type=explicit_type, confidence=_EXPLICIT_WEIGHT,
            source="explicit",
            evidence=[f"explicitly annotated as {explicit_type}"],
        )

    # ── Source 2: Pattern matching (medium confidence) ──
    pattern_type = SEM.CHAIN
    pattern_evidence = []

    # Check LLM patterns (with anti-patterns)
    anti_hit = any(ap in name for ap in _LLM_ANTI_PATTERNS)
    if not anti_hit:
        for pat in _LLM_FUNC_PATTERNS:
            if pat in name:
                pattern_type = SEM.LLM
                pattern_evidence.append(f"name matches '{pat}'")
                break
        if pattern_type != SEM.LLM:
            for pat in _LLM_MODULE_PATTERNS:
                if pat in mod:
                    pattern_type = SEM.LLM
                    pattern_evidence.append(f"module matches '{pat}'")
                    break

    # Check DECISION patterns
    if pattern_type == SEM.CHAIN:
        for pat in _DECISION_FUNC_PATTERNS:
            if name.startswith(pat) or pat in name:
                pattern_type = SEM.DECISION
                pattern_evidence.append(f"name matches '{pat}'")
                break

    # Check TOOL patterns
    if pattern_type == SEM.CHAIN:
        for pat in _TOOL_FUNC_PATTERNS:
            if pat in name:
                pattern_type = SEM.TOOL
                pattern_evidence.append(f"name matches '{pat}'")
                break

    if pattern_type == SEM.CHAIN and func is not None and _looks_like_tool(func):
        pattern_type = SEM.TOOL
        pattern_evidence.append("module structure suggests tool")

    # ── Source 3: Runtime evidence (higher confidence) ──
    runtime_type = None
    runtime_evidence = []
    if runtime_result is not None:
        runtime_type, runtime_evidence = _check_runtime_evidence(runtime_result)

    # ── Combine evidence ──
    if pattern_type != SEM.CHAIN and runtime_type and runtime_type == pattern_type:
        # Both agree → high confidence
        confidence = 0.90
        source = "combined"
        evidence = pattern_evidence + runtime_evidence
        final_type = pattern_type
    elif runtime_type:
        # Runtime overrides pattern (runtime is stronger)
        confidence = _RUNTIME_WEIGHT
        source = "runtime"
        evidence = runtime_evidence
        if pattern_type != SEM.CHAIN:
            evidence.append(f"(overrides pattern: {pattern_type})")
        final_type = runtime_type
    elif pattern_type != SEM.CHAIN:
        confidence = _PATTERN_WEIGHT
        source = "pattern"
        evidence = pattern_evidence
        final_type = pattern_type
    else:
        confidence = 0.40
        source = "default"
        evidence = ["no evidence matched"]
        final_type = SEM.CHAIN

    return SemanticSignal(
        type=final_type, confidence=confidence,
        source=source, evidence=evidence,
    )


def _check_runtime_evidence(result: Any) -> tuple:
    """Check return value for runtime semantic signals.

    Returns (type, evidence_list).
    """
    evidence = []

    # LLM-like: result has choices/message/content structure
    if hasattr(result, "choices"):
        evidence.append("return has 'choices' (LLM response pattern)")
        return (SEM.LLM, evidence)
    if hasattr(result, "content") and hasattr(result, "role"):
        evidence.append("return has content+role (chat message pattern)")
        return (SEM.LLM, evidence)

    # DECISION-like: bool return
    if isinstance(result, bool):
        evidence.append("returns bool (decision pattern)")
        return (SEM.DECISION, evidence)

    # TOOL-like: result is a dict with tool-like keys
    if isinstance(result, dict):
        tool_keys = {"result", "data", "response", "status", "error", "output"}
        if any(k in result for k in tool_keys):
            evidence.append(f"dict with tool-like keys: {set(result.keys()) & tool_keys}")
            return (SEM.TOOL, evidence)

    # LLM-like: string result that looks like natural language
    if isinstance(result, str) and len(result) > 50:
        # Check for JSON structure (common in structured LLM output)
        try:
            json.loads(result)
            evidence.append("string is valid JSON (structured LLM output)")
            return (SEM.LLM, evidence)
        except (json.JSONDecodeError, ValueError):
            pass

    return (None, [])


def infer_semantic_type(func_name: str = None, module_name: str = None,
                        func: Callable = None) -> str:
    """Backward-compat wrapper: returns bare type string from classify_semantic."""
    return classify_semantic(func_name=func_name, module_name=module_name,
                             func=func).type


def _looks_like_tool(func: Callable) -> bool:
    """Heuristic: does this function look like an external tool call?"""
    qual = getattr(func, "__qualname__", "").lower()
    mod = getattr(func, "__module__", "").lower()
    combined = f"{mod}.{qual}"

    for indicator in ["api", "client", "service", "tool", "util", "helper"]:
        if indicator in combined:
            return True

    if hasattr(func, "__wrapped__"):
        wrapped = func.__wrapped__
        wmod = getattr(wrapped, "__module__", "").lower()
        for indicator in ["api", "service", "client"]:
            if indicator in wmod:
                return True

    return False


# ============================================================
# P2: Auto Variable Extraction
# ============================================================

def auto_extract_produces(func_name: str, result: Any,
                          semantic_type: str = None) -> Dict[str, Any]:
    """
    Auto-extract produces keys from a function's return value.

    Rules:
    - dict return → use as-is (keys become variable names)
    - str/int/float return → {"result": value}
    - LLM type → {"llm_output": text}
    - None → {}
    """
    if result is None:
        return {}

    if isinstance(result, dict):
        return dict(result)

    key = "result"
    if semantic_type == SEM.LLM:
        key = "llm_output"
    elif semantic_type == SEM.TOOL:
        # Use function name as key for tool results
        safe_name = func_name.replace(".", "_").replace("-", "_")
        key = f"{safe_name}_result"

    return {key: result}


def auto_extract_consumes(func_name: str, args: tuple,
                          kwargs: dict) -> Dict[str, Any]:
    """
    Auto-extract consumes keys from function arguments.
    Uses parameter names from kwargs if available, otherwise positional.

    For bound methods, skips 'self'/'cls'.
    """
    if kwargs:
        # kwarg names are the cleanest signal
        return {k: _safe_truncate(str(v), 200) for k, v in kwargs.items()}

    # Try to get parameter names via inspect
    consumes = {}
    try:
        import inspect
        sig = inspect.signature(args[0]) if args else None
    except Exception:
        sig = None

    if args:
        consumes["args"] = _safe_truncate(str(args), 300)

    return consumes


# ============================================================
# trace_step — function-level decorator
# ============================================================

def trace_step(name: str = None, semantic_type: str = None,
               capture_args: bool = True, capture_result: bool = True,
               produces_key: str = None, consumes_keys: Dict = None,
               auto_infer: bool = True):
    """
    Decorator: auto-trace a function call as a semantic span.

    Args:
        name: Span name (default: function name)
        semantic_type: SEM.LLM / SEM.TOOL / SEM.DECISION / etc.
                       If None and auto_infer=True, inferred automatically.
        capture_args: Include function arguments
        capture_result: Include return value
        produces_key: If set, auto-declare `produces = {key: result}`
        consumes_keys: If set, declare `consumes = {key: args[key]}`
        auto_infer: Auto-infer semantic_type from function name/module (P2)

    Usage:
        @trace_step("classify", SEM.LLM, produces_key="intent")
        def classify(prompt: str) -> str: ...

        # P2: auto-infer works without explicit SEM
        @trace_step  # infers TOOL from name "weather_api"
        def weather_api(city: str) -> str: ...
    """
    def decorator(func):
        step_name = name or func.__name__

        # P3: pre-compute pattern-level signal (refined at runtime)
        signal = None
        if auto_infer:
            signal = classify_semantic(
                func_name=step_name, func=func,
                explicit_type=semantic_type if semantic_type != SEM.CHAIN else None,
            )
        _sem_type = semantic_type or (signal.type if signal else SEM.CHAIN)

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            nonlocal signal
            ctx = get_trace_context()
            if ctx is None:
                return func(*args, **kwargs)

            inputs = {}
            if capture_args:
                if kwargs:
                    inputs = {k: _safe_truncate(str(v), 300) for k, v in kwargs.items()}
                else:
                    inputs["args"] = _safe_truncate(str(args), 300)

            # Auto-extract consumes from args
            if consumes_keys:
                auto_consumes = {k: kwargs.get(k, args[0] if args else None)
                               for k in consumes_keys}
            else:
                auto_consumes = auto_extract_consumes(step_name, args, kwargs)

            with trace_span(step_name, _sem_type or SEM.CHAIN,
                          inputs=inputs) as span:
                result = func(*args, **kwargs)
                if capture_result and span.get("step_id"):
                    span["outputs"] = {"result": _safe_truncate(str(result), 500)}

                    # P3: refine semantic signal with runtime evidence
                    if signal is not None and signal.source != "explicit":
                        runtime_type, _ = _check_runtime_evidence(result)
                        if runtime_type and runtime_type != signal.type:
                            # Runtime overrides pattern
                            signal = SemanticSignal(
                                type=runtime_type,
                                confidence=_RUNTIME_WEIGHT,
                                source="runtime",
                                evidence=[f"runtime: {signal.type}→{runtime_type}"],
                            )
                        elif runtime_type == signal.type:
                            # Runtime corroborates → boost confidence
                            signal.confidence = 0.90
                            signal.source = "combined"
                            signal.evidence.append("runtime corroborates pattern")

                    # Attach semantic signal to span
                    if signal is not None:
                        span["semanticsignal"] = signal

                    # Auto-extract produces from return value
                    if produces_key:
                        span["produces"] = {produces_key: result}
                    else:
                        span["produces"] = auto_extract_produces(
                            step_name, result, _sem_type
                        )

                    # Attach auto-extracted consumes
                    if auto_consumes:
                        span["consumes"] = auto_consumes

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
# P2: OpenAI auto-patch
# ============================================================

_OPENAI_PATCHED = False
_openai_originals = {}


def patch_openai():
    """Monkey-patch OpenAI for auto-tracing. Supports v0.x and v1.x APIs."""
    global _OPENAI_PATCHED
    if _OPENAI_PATCHED:
        return

    try:
        import openai
    except ImportError:
        return

    # ── v0.x API: openai.ChatCompletion.create ──
    if hasattr(openai, "ChatCompletion") and hasattr(openai.ChatCompletion, "create"):
        original = openai.ChatCompletion.create

        def traced_chat_create(*args, **kwargs):
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
                    span["produces"] = {"llm_output": content}
                return result

        _openai_originals["chat_create"] = original
        openai.ChatCompletion.create = traced_chat_create
        _OPENAI_PATCHED = True
        return

    # ── v1.x API: openai.chat.completions.create ──
    try:
        if hasattr(openai, "chat") and hasattr(openai.chat, "completions"):
            completions = openai.chat.completions
            if hasattr(completions, "create"):
                original_v1 = completions.create

                def traced_v1_create(*args, **kwargs):
                    ctx = get_trace_context()
                    if ctx is None:
                        return original_v1(*args, **kwargs)

                    messages = kwargs.get("messages", [])
                    model = kwargs.get("model", "unknown")
                    prompt_preview = _safe_truncate(str(messages), 500)

                    with trace_span(f"llm:{model}", SEM.LLM,
                                   inputs={"model": model, "messages": prompt_preview}) as span:
                        result = original_v1(*args, **kwargs)
                        if hasattr(result, "choices") and result.choices:
                            content = result.choices[0].message.content
                            span["outputs"] = {"result": _safe_truncate(str(content), 500)}
                            span["produces"] = {"llm_output": content}
                        return result

                _openai_originals["chat_create_v1"] = original_v1
                completions.create = traced_v1_create
                _OPENAI_PATCHED = True
    except Exception:
        pass


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
# P2: LangChain auto-patch
# ============================================================

_LANGCHAIN_PATCHED = False
_langchain_originals = {}


def patch_langchain():
    """
    Monkey-patch LangChain BaseChatModel.invoke() / ainvoke() for auto-tracing.

    Covers: langchain, langchain_openai, langchain_anthropic, langgraph.
    """
    global _LANGCHAIN_PATCHED
    if _LANGCHAIN_PATCHED:
        return

    try:
        from langchain_core.language_models.chat_models import BaseChatModel
    except ImportError:
        return

    if hasattr(BaseChatModel, "invoke"):
        _langchain_originals["lc_invoke"] = BaseChatModel.invoke
        original_invoke = BaseChatModel.invoke

        @functools.wraps(original_invoke)
        def traced_invoke(self, input_data, *args, **kwargs):
            ctx = get_trace_context()
            if ctx is None:
                return original_invoke(self, input_data, *args, **kwargs)

            model_name = getattr(self, "model_name", getattr(self, "model", "unknown"))
            prompt_preview = _safe_truncate(str(input_data), 500)

            with trace_span(f"llm:{model_name}", SEM.LLM,
                           inputs={"model": str(model_name),
                                   "messages": prompt_preview}) as span:
                result = original_invoke(self, input_data, *args, **kwargs)
                # Extract content from LangChain response
                content = _extract_langchain_content(result)
                span["outputs"] = {"result": _safe_truncate(str(content), 500)}
                span["produces"] = {"llm_output": content}
                return result

        BaseChatModel.invoke = traced_invoke
        _LANGCHAIN_PATCHED = True


def _extract_langchain_content(result) -> str:
    """Extract text content from a LangChain response object."""
    if hasattr(result, "content"):
        content = result.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and "text" in item:
                    parts.append(item["text"])
                elif hasattr(item, "text"):
                    parts.append(item.text)
                else:
                    parts.append(str(item))
            return " ".join(parts)
        return str(content)
    return str(result)


def unpatch_langchain():
    """Restore original LangChain functions."""
    global _LANGCHAIN_PATCHED
    try:
        from langchain_core.language_models.chat_models import BaseChatModel
        for name, original in _langchain_originals.items():
            if name == "lc_invoke":
                BaseChatModel.invoke = original
        _langchain_originals.clear()
        _LANGCHAIN_PATCHED = False
    except ImportError:
        pass


# ============================================================
# auto_trace — one-line setup
# ============================================================

def auto_trace(patch_llm: bool = True, patch_frameworks: bool = True):
    """
    One-line auto-instrumentation.

    Call at the start of your agent script:
        from agent_obs.instrument import auto_trace
        auto_trace()

    Args:
        patch_llm: Monkey-patch OpenAI
        patch_frameworks: Monkey-patch LangChain and other frameworks
    """
    if patch_llm:
        patch_openai()
    if patch_frameworks:
        patch_langchain()
