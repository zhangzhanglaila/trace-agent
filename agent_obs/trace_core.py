"""
Trace Core: Semantic trace context, span stack, and TracedAgent wrapper.

Semantic layer: every node has a user-facing type and name, plus
produces/consumes keys for dependency tracking.

Usage:
    from agent_obs.trace_core import (trace_root, trace_span, trace_decision,
                                      TracedAgent, get_trace_context)

    with trace_root("my_agent") as ctx:
        with trace_span("classify_intent", SEM.LLM, inputs={"prompt": "..."}) as s:
            result = llm(...)
            s["outputs"] = {"result": result}
            s["produces"] = {"intent": result}

        trace_decision("should_search", value=True,
                       consumes={"intent": "weather"})
"""
import threading
import time
import json
import os
from contextlib import contextmanager
from typing import Optional, Any, Dict, List, Callable

from .execution_graph import TraceCapture, TraceCompiler
from .trace_export import TraceExporter

# ============================================================
# Semantic Types
# ============================================================

class SEM:
    """Semantic node types — user-facing, not compiler-internal."""
    LLM = "LLM"              # LLM call: prompt → response
    TOOL = "TOOL"            # Tool invocation: args → result
    DECISION = "DECISION"   # Branch/routing decision
    CONTROL = "CONTROL"      # Merge, loop, control flow
    INPUT = "INPUT"          # Agent input
    OUTPUT = "OUTPUT"        # Agent output
    CHAIN = "CHAIN"          # Generic/unknown step


# ============================================================
# Thread-local context
# ============================================================

_local = threading.local()
_trace_counter = 0


def get_trace_context() -> Optional["TraceContext"]:
    """Get the current thread-local trace context, or None."""
    return getattr(_local, "trace_ctx", None)


# ============================================================
# TraceContext
# ============================================================

class TraceContext:
    """
    Thread-local trace context with nested span stack and semantic typing.

    Each span records:
    - semantic_type: LLM | TOOL | DECISION | CONTROL | INPUT | OUTPUT | CHAIN
    - semantic_name: human-readable label
    - produces: dict of key → value this node outputs
    - consumes: dict of key → value this node depends on
    """

    def __init__(self, run_name: str = "agent_run", out_dir: str = None):
        self.run_name = run_name
        self.out_dir = out_dir or "."
        self.capture = TraceCapture()
        self._span_stack: List[str] = []
        self._root_id: Optional[str] = None
        self._span_count = 0
        self._export_path: Optional[str] = None
        self._result: Any = None

    # ── Span management ──

    def start_span(self, name: str, semantic_type: str = SEM.CHAIN,
                   inputs: Dict = None) -> str:
        """
        Start a new span with semantic typing.

        Args:
            name: Human-readable name (e.g. "weather_api", "classify_intent")
            semantic_type: One of SEM.LLM / SEM.TOOL / SEM.DECISION / etc.
            inputs: Dict of input values

        Returns the step_id.
        """
        self._span_count += 1
        step_id = f"{semantic_type.lower()}_{self._span_count}"

        parent_id = self._span_stack[-1] if self._span_stack else None
        if self._root_id is None:
            self._root_id = step_id

        self._span_stack.append(step_id)

        if semantic_type == SEM.LLM:
            self.capture.record_llm(
                prompt=inputs.get("prompt", "") if inputs else "",
                output=None,
                step_id=step_id,
                parent_id=parent_id,
            )
        elif semantic_type == SEM.TOOL:
            self.capture.record_tool(
                name=name,
                args=inputs or {},
                result=None,
                step_id=step_id,
                parent_id=parent_id,
            )
        else:
            self._record_semantic(step_id, name, semantic_type, inputs, parent_id)

        # Patch semantic fields onto the step (record_llm/record_tool don't set them)
        for step in self.capture.steps:
            if step.get("id") == step_id:
                step["semantic_type"] = semantic_type
                step["semantic_name"] = f"[{semantic_type}] {name}"
                break

        return step_id

    def end_span(self, step_id: str = None, outputs: Dict = None,
                 status: str = "success", error: str = None,
                 produces: Dict = None, consumes: Dict = None):
        """End span, patching outputs/produces/consumes into the step."""
        if step_id is None:
            if not self._span_stack:
                return
            step_id = self._span_stack.pop()
        else:
            if step_id in self._span_stack:
                self._span_stack.remove(step_id)

        for step in self.capture.steps:
            if step.get("id") == step_id:
                if outputs:
                    step["outputs"] = outputs
                    if step.get("type") == "tool" and "result" in outputs:
                        step["result"] = outputs["result"]
                    if step.get("type") == "llm" and "result" in outputs:
                        step["output"] = outputs["result"]
                if produces:
                    step["produces"] = produces
                if consumes:
                    step["consumes"] = consumes
                step["status"] = status
                if error:
                    step["error"] = error
                break

    def record_decision(self, name: str, value: Any,
                        consumes: Dict = None,
                        true_branch: str = None,
                        false_branch: str = None) -> str:
        """
        Record a semantic decision point (routing/branch).

        Args:
            name: Decision name, e.g. "should_search", "result_sufficient"
            value: The decision value (True/False or any)
            consumes: What keys this decision depends on
            true_branch: Label for the true path
            false_branch: Label for the false path

        Returns step_id.
        """
        self._span_count += 1
        step_id = f"decision_{self._span_count}"

        parent_id = self._span_stack[-1] if self._span_stack else None

        self.capture._step_start(step_id)
        obs = self.capture._step_end(step_id)
        self.capture.steps.append({
            "type": "branch",
            "id": step_id,
            "name": name,
            "semantic_type": SEM.DECISION,
            "semantic_name": f"[Decision] {name}",
            "condition": name,
            "value": value,
            "true_branch": true_branch,
            "false_branch": false_branch,
            "inputs": {},
            "outputs": {"decision": value},
            "consumes": consumes or {},
            "produces": {name: value},
            "parent_id": parent_id,
            **obs,
        })
        return step_id

    def _record_semantic(self, step_id: str, name: str, semantic_type: str,
                         inputs: Dict, parent_id: Optional[str]):
        """Record a step with semantic metadata."""
        self.capture._step_start(step_id)
        obs = self.capture._step_end(step_id)
        self.capture.steps.append({
            "type": "chain",
            "id": step_id,
            "name": name,
            "semantic_type": semantic_type,
            "semantic_name": f"[{semantic_type}] {name}",
            "inputs": inputs or {},
            "outputs": {},
            "parent_id": parent_id,
            **obs,
        })

    # ── Export ──

    def export(self, path: str = None) -> str:
        """Compile trace and export to JSON."""
        global _trace_counter
        if path is None:
            _trace_counter += 1
            ts = int(time.time() * 1000)
            safe_name = self.run_name.replace(" ", "_").replace("/", "_")
            path = os.path.join(self.out_dir, f"trace_{safe_name}_{ts}_{_trace_counter}.json")

        compiler = TraceCompiler()
        graph = compiler.compile(self.capture.get_trace())

        exporter = TraceExporter(
            graph=graph,
            branches=compiler.branches,
            step_to_node=compiler.step_to_node,
            steps=self.capture.steps,
        )
        trace_export = exporter.export()

        with open(path, "w", encoding="utf-8") as f:
            f.write(trace_export.to_json())

        self._export_path = path
        return path

    # ── Dependency graph ──

    def build_dep_graph(self) -> Dict[str, List[str]]:
        """
        Build a dependency graph from produces/consumes keys.
        Returns {step_id: [dep_step_ids]} for backward slicing.
        """
        deps: Dict[str, List[str]] = {}
        producers: Dict[str, str] = {}

        # First pass: init all entries, index producers
        for step in self.capture.steps:
            sid = step["id"]
            deps[sid] = []
            for key in (step.get("produces") or {}):
                producers[key] = sid

        # Second pass: add data + parent + sequential deps
        prev_sid = None
        for step in self.capture.steps:
            sid = step["id"]

            # Data dependencies (consumes → produces)
            for key in (step.get("consumes") or {}):
                if key in producers and producers[key] != sid:
                    deps[sid].append(producers[key])

            # Parent dependency
            parent_id = step.get("parent_id")
            if parent_id and parent_id in deps and parent_id not in deps[sid]:
                deps[sid].append(parent_id)

            # Sequential dependency (previous step in trace order)
            if prev_sid and prev_sid in deps and prev_sid not in deps[sid]:
                deps[sid].append(prev_sid)
            prev_sid = sid

        return deps

    def backward_slice(self, target_step_id: str) -> List[str]:
        """
        Backward slice from a target step: find all upstream dependencies.
        Returns steps in causal order (root → target).
        """
        deps = self.build_dep_graph()
        visited: List[str] = []

        def walk(sid: str):
            if sid in visited:
                return
            for dep_id in deps.get(sid, []):
                walk(dep_id)
            if sid not in visited:
                visited.append(sid)

        walk(target_step_id)
        return visited

    # ── Causal Explanation ──

    def explain(self, target_step_id: str = None) -> "CausalExplanation":
        """
        Generate a human-readable causal explanation for a target step.

        Backward-slices from the target, filters to key nodes
        (DECISION, LLM, ERROR), and generates natural-language explanations.

        Returns a CausalExplanation with a chain of causal steps.
        """
        if target_step_id is None:
            # Default: last meaningful step
            for s in reversed(self.capture.steps):
                if s.get("semantic_type") in ("LLM", "TOOL", "DECISION", "OUTPUT"):
                    target_step_id = s["id"]
                    break
            if target_step_id is None and self.capture.steps:
                target_step_id = self.capture.steps[-1]["id"]

        if target_step_id is None:
            return CausalExplanation(chain=[], narrative="No trace data available.")

        chain_ids = self.backward_slice(target_step_id)

        # Build step lookup
        step_map = {s["id"]: s for s in self.capture.steps}

        # Filter to key causal nodes and generate explanations
        key_nodes = _filter_key_nodes(chain_ids, step_map)
        causal_steps = [_explain_step(sid, step_map) for sid in key_nodes]

        narrative = _build_narrative(causal_steps)

        return CausalExplanation(
            chain=causal_steps,
            narrative=narrative,
            target_step_id=target_step_id,
        )

    @property
    def export_path(self) -> Optional[str]:
        return self._export_path

    @property
    def result(self) -> Any:
        return self._result


# ============================================================
# Causal Explanation Types
# ============================================================

class CausalStep:
    """One step in a causal chain, with human-readable explanation."""
    def __init__(self, step_id: str, semantic_type: str, name: str,
                 description: str, is_critical: bool = False):
        self.step_id = step_id
        self.semantic_type = semantic_type
        self.name = name
        self.description = description
        self.is_critical = is_critical

    def __repr__(self):
        return f"[{self.semantic_type}] {self.description}"


class CausalExplanation:
    """Full causal explanation: chain of steps + narrative summary."""
    def __init__(self, chain: List[CausalStep], narrative: str,
                 target_step_id: str = None):
        self.chain = chain
        self.narrative = narrative
        self.target_step_id = target_step_id

    def __repr__(self):
        return self.narrative


# ============================================================
# Explanation helpers
# ============================================================

# Node types that carry causal weight
_KEY_SEMANTIC_TYPES = {"LLM", "DECISION"}

# Node types that are critical when they have errors
_ERROR_SENSITIVE_TYPES = {"LLM", "TOOL", "DECISION"}


def _filter_key_nodes(chain_ids: List[str],
                      step_map: Dict[str, Dict]) -> List[str]:
    """Filter a chain to nodes that carry causal weight."""
    result = []
    for sid in chain_ids:
        step = step_map.get(sid, {})
        st = step.get("semantic_type", "")
        status = step.get("status", "success")
        error = step.get("error")

        # Always keep DECISION and LLM nodes
        if st in _KEY_SEMANTIC_TYPES:
            result.append(sid)
            continue

        # Keep ERROR nodes
        if status == "error" or error:
            if st in _ERROR_SENSITIVE_TYPES:
                result.append(sid)
                continue

        # Keep TOOL nodes only if they error or are the target
        if st == "TOOL" and (status == "error" or error):
            result.append(sid)
            continue

    return result


def _explain_step(sid: str, step_map: Dict[str, Dict]) -> CausalStep:
    """Generate a human-readable explanation for a single step."""
    step = step_map.get(sid, {})
    st = step.get("semantic_type", "?")
    # Build a clean display name (without [TYPE] prefix)
    name = step.get("name") or ""
    if not name:
        name = step.get("semantic_name", sid)
    if name.startswith("[") and "] " in name:
        name = name.split("] ", 1)[1]
    status = step.get("status", "success")
    error = step.get("error")

    # Determine if critical
    is_critical = (status == "error" or error is not None or
                   st == "DECISION")

    if st == "LLM":
        outputs = step.get("outputs", {})
        result = outputs.get("result", step.get("output", ""))
        result_preview = str(result)[:80] if result else "?"
        desc = f"LLM `{name}` produced: {result_preview}"

    elif st == "DECISION":
        value = step.get("value")
        produces = step.get("produces", {})
        cond_name = step.get("condition", step.get("name", "?"))
        desc = f"Decision `{cond_name}` = {value}"
        if step.get("true_branch"):
            desc += f" → took '{step['true_branch']}' path"

    elif st == "TOOL":
        if status == "error" or error:
            desc = f"Tool `{name}` FAILED: {error or 'unknown error'}"
        else:
            result = step.get("result", step.get("outputs", {}).get("result", "?"))
            desc = f"Tool `{name}` returned: {str(result)[:80]}"

    else:
        desc = f"Step `{name}` (type={st})"
        if error:
            desc += f" — ERROR: {error}"

    return CausalStep(
        step_id=sid,
        semantic_type=st,
        name=name,
        description=desc,
        is_critical=is_critical,
    )


def _build_narrative(causal_steps: List[CausalStep]) -> str:
    """Build a narrative summary from causal steps."""
    if not causal_steps:
        return "No causal chain found."

    # Find the critical steps
    critical = [s for s in causal_steps if s.is_critical]
    if not critical:
        critical = causal_steps

    # Build chain narrative
    lines = []
    for i, step in enumerate(causal_steps):
        prefix = "  ->" if i < len(causal_steps) - 1 else "  [!]"
        marker = " **" if step.is_critical else ""
        lines.append(f"{prefix}{marker} {step.description}")

    return "\n".join(lines)


# ============================================================
# Diff explanation
# ============================================================

def _filter_all_meaningful(chain_ids: List[str],
                          step_map: Dict[str, Dict]) -> List[str]:
    """Broader filter for diff comparison — includes TOOL/OUTPUT nodes."""
    result = []
    for sid in chain_ids:
        step = step_map.get(sid, {})
        st = step.get("semantic_type", "")
        if st in ("LLM", "DECISION", "TOOL", "OUTPUT"):
            result.append(sid)
    return result


def explain_diff(ctx_a: TraceContext, ctx_b: TraceContext) -> str:
    """
    Compare two trace contexts and generate a causal explanation
    of why they diverged.

    Returns a human-readable narrative.
    """
    # Use broader filter for diff comparison
    target_a = _find_last_meaningful(ctx_a)
    target_b = _find_last_meaningful(ctx_b)

    if not target_a and not target_b:
        return "No meaningful steps found in either trace."

    chain_ids_a = ctx_a.backward_slice(target_a) if target_a else []
    chain_ids_b = ctx_b.backward_slice(target_b) if target_b else []

    step_map_a = {s["id"]: s for s in ctx_a.capture.steps}
    step_map_b = {s["id"]: s for s in ctx_b.capture.steps}

    key_a = _filter_all_meaningful(chain_ids_a, step_map_a)
    key_b = _filter_all_meaningful(chain_ids_b, step_map_b)

    chain_a = [_explain_step(sid, step_map_a) for sid in key_a]
    chain_b = [_explain_step(sid, step_map_b) for sid in key_b]

    # Build the comparison narrative
    lines = []
    lines.append("Causal Chain Comparison:")
    lines.append("-" * 40)

    # Build index by description for alignment
    descs_a = [s.description for s in chain_a]
    descs_b = [s.description for s in chain_b]

    # Find shared prefix
    shared_count = 0
    for i in range(min(len(chain_a), len(chain_b))):
        if chain_a[i].description == chain_b[i].description:
            shared_count = i + 1
        else:
            break

    # Show shared prefix
    for i in range(shared_count):
        lines.append(f"  =  {chain_a[i].description}")

    # Find divergence: match by type+name
    remaining_a = chain_a[shared_count:]
    remaining_b = chain_b[shared_count:]

    # Simple alignment: compare by semantic type
    found_divergence = len(remaining_a) > 0 or len(remaining_b) > 0
    if found_divergence:
        lines.append(f"  ** FIRST DIVERGENCE **")

    # Show diverging pairs (same type) then exclusive steps
    matched_b = set()
    for sa in remaining_a:
        # Try to find matching step in B by semantic type
        paired = None
        for j, sb in enumerate(remaining_b):
            if j in matched_b:
                continue
            if sa.semantic_type == sb.semantic_type:
                paired = (j, sb)
                break
        if paired:
            matched_b.add(paired[0])
            sb = paired[1]
            if sa.description == sb.description:
                lines.append(f"  =  {sa.description}")
            else:
                lines.append(f"  A: {sa.description}")
                lines.append(f"  B: {sb.description}")
        else:
            lines.append(f"  A: {sa.description}")
            lines.append(f"  B: (none)")

    # Show B-exclusive steps
    for j, sb in enumerate(remaining_b):
        if j not in matched_b:
            lines.append(f"  A: (none)")
            lines.append(f"  B: {sb.description}")

    # Root cause analysis
    lines.append("")
    lines.append("Root Cause Analysis:")
    lines.append("-" * 40)

    max_len = max(len(chain_a), len(chain_b))
    found_root_cause = False
    for i in range(max_len):
        sa = chain_a[i] if i < len(chain_a) else None
        sb = chain_b[i] if i < len(chain_b) else None

        if sa and sb and sa.description != sb.description:
            if sa.semantic_type == "LLM":
                lines.append(f"The root cause is a change in LLM output:")
                lines.append(f"  Run A: {sa.description}")
                lines.append(f"  Run B: {sb.description}")
                if i + 1 < len(chain_a) and chain_a[i+1].semantic_type == "DECISION":
                    lines.append(f"This caused the decision to change:")
                    lines.append(f"  {chain_a[i+1].description}")
                found_root_cause = True
                break
            elif sa.semantic_type == "DECISION":
                lines.append(f"The root cause is a different decision:")
                lines.append(f"  Run A: {sa.description}")
                lines.append(f"  Run B: {sb.description}")
                found_root_cause = True
                break
            elif sa.semantic_type == "TOOL":
                lines.append(f"The root cause is a tool result difference:")
                lines.append(f"  Run A: {sa.description}")
                lines.append(f"  Run B: {sb.description}")
                found_root_cause = True
                break
        elif sa and not sb:
            lines.append(f"The root cause is a path difference:")
            lines.append(f"  Run A includes: {sa.description}")
            lines.append(f"  Run B does not.")
            found_root_cause = True
            break
        elif sb and not sa:
            lines.append(f"The root cause is a path difference:")
            lines.append(f"  Run B includes: {sb.description}")
            lines.append(f"  Run A does not.")
            found_root_cause = True
            break

    if not found_divergence and not found_root_cause:
        lines.append("Both runs followed identical causal chains.")

    return "\n".join(lines)


def _find_last_meaningful(ctx) -> Optional[str]:
    """Find the last meaningful step ID in a context."""
    for s in reversed(ctx.capture.steps):
        st = s.get("semantic_type", "")
        if st in ("LLM", "TOOL", "DECISION", "OUTPUT"):
            return s["id"]
    return ctx.capture.steps[-1]["id"] if ctx.capture.steps else None


# ============================================================
# Context Managers
# ============================================================

@contextmanager
def trace_root(run_name: str = "agent_run", out_dir: str = None,
               auto_export: bool = True):
    """
    Create a root trace context. Auto-exports trace.json on exit.

    Usage:
        with trace_root("my_agent") as ctx:
            ...
        # trace_my_agent_xxx.json written here
    """
    ctx = TraceContext(run_name, out_dir)
    _local.trace_ctx = ctx

    try:
        ctx.start_span(run_name, SEM.CHAIN, inputs={"run_name": run_name})
        yield ctx
    except Exception as e:
        ctx.end_span(error=str(e), status="error")
        if auto_export:
            ctx.export()
        raise
    else:
        ctx.end_span(status="success")
        if auto_export:
            ctx.export()
    finally:
        _local.trace_ctx = None


@contextmanager
def trace_span(name: str, semantic_type: str = SEM.CHAIN,
               inputs: Dict = None):
    """
    Create a child span within the current trace context.

    Yields a dict with keys: step_id, outputs, produces, consumes.
    Set these on the yielded dict to capture results and dependencies:

        with trace_span("weather_api", SEM.TOOL, inputs={"city": "paris"}) as span:
            result = call_weather("paris")
            span["outputs"] = {"result": result}
            span["produces"] = {"weather_data": result}
    """
    ctx = get_trace_context()
    if ctx is None:
        yield {"step_id": None, "outputs": None, "produces": None, "consumes": None}
        return

    step_id = ctx.start_span(name, semantic_type, inputs)
    span_info = {"step_id": step_id, "outputs": None,
                 "produces": None, "consumes": None}
    try:
        yield span_info
    except Exception as e:
        ctx.end_span(step_id, error=str(e), status="error")
        raise
    else:
        ctx.end_span(step_id,
                     outputs=span_info.get("outputs"),
                     produces=span_info.get("produces"),
                     consumes=span_info.get("consumes"),
                     status="success")


def trace_decision(name: str, value: Any,
                   consumes: Dict = None,
                   true_branch: str = None,
                   false_branch: str = None) -> Optional[str]:
    """
    Record a semantic decision point.

    Usage:
        trace_decision("should_search", True,
                       consumes={"intent": "weather"},
                       true_branch="call_search",
                       false_branch="direct_output")
    """
    ctx = get_trace_context()
    if ctx is None:
        return None
    return ctx.record_decision(name, value, consumes,
                               true_branch, false_branch)


# ============================================================
# TracedAgent — universal wrapper
# ============================================================

class TracedAgent:
    """
    Wrap any agent to auto-trace every run.

    Usage:
        agent = TracedAgent(my_agent, name="MyAgent")
        result = agent.run("what's the weather?")
        # trace written to ./trace_MyAgent_xxx.json
    """

    def __init__(self, agent, name: str = None, out_dir: str = "."):
        self._agent = agent
        self.name = name or getattr(agent, "__class__", type(agent)).__name__
        self.out_dir = out_dir
        self._last_ctx: Optional[TraceContext] = None

    def run(self, input_data: Any, **kwargs) -> Any:
        """Run the agent with full tracing. Trace auto-exported to JSON."""
        with trace_root(self.name, self.out_dir) as ctx:
            self._last_ctx = ctx

            ctx.start_span("input", SEM.INPUT,
                          inputs={"query": str(input_data)[:500]})
            ctx.end_span()

            try:
                result = self._call_agent(input_data, **kwargs)
                ctx._result = result
            except Exception as e:
                ctx._result = None
                raise

            ctx.start_span("output", SEM.OUTPUT,
                          inputs={"result": str(result)[:500]})
            ctx.end_span()

            return result

    def _call_agent(self, input_data: Any, **kwargs) -> Any:
        """Call the underlying agent via duck-typing."""
        agent = self._agent
        if callable(agent) and not hasattr(agent, "run"):
            return agent(input_data, **kwargs)
        if hasattr(agent, "run"):
            return agent.run(input_data, **kwargs)
        if hasattr(agent, "invoke"):
            return agent.invoke(input_data, **kwargs)
        if hasattr(agent, "__call__"):
            return agent(input_data, **kwargs)
        raise TypeError(
            f"Agent {type(agent)} has no recognizable interface. "
            f"Expected: callable, .run(), .invoke(), or .__call__()"
        )

    @property
    def last_trace_path(self) -> Optional[str]:
        if self._last_ctx:
            return self._last_ctx.export_path
        return None

    @property
    def last_trace(self):
        if self._last_ctx:
            return self._last_ctx.capture
        return None

    @property
    def last_ctx(self) -> Optional[TraceContext]:
        return self._last_ctx
