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
                 produces: Dict = None, consumes: Dict = None,
                 semantic_signal = None):
        """End span, patching outputs/produces/consumes/signal into the step."""
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
                if semantic_signal is not None:
                    step["semantic_signal"] = {
                        "type": semantic_signal.type,
                        "confidence": semantic_signal.confidence,
                        "source": semantic_signal.source,
                        "evidence": semantic_signal.evidence,
                    }
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

        def walk(sid: str, stack: set = None):
            if stack is None:
                stack = set()
            if sid in visited:
                return
            if sid in stack:
                return  # cycle detected — already in current DFS path
            stack.add(sid)
            for dep_id in deps.get(sid, []):
                if dep_id not in visited:
                    walk(dep_id, stack)
            stack.discard(sid)
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
# P3-2: Variable Graph — variable-level DAG
# ============================================================

class VarNode:
    """A variable in the causal graph."""
    def __init__(self, name: str, step_id: str, value: Any,
                 semantic_type: str = None):
        self.name = name          # e.g. "weather_data"
        self.step_id = step_id    # which step produces it
        self.value = value
        self.semantic_type = semantic_type

    def __repr__(self):
        return f"Var({self.name} = {_var_preview(self.value)})"


class VarEdge:
    """Directed edge: from_var → to_var (producer → consumer)."""
    def __init__(self, from_var: str, from_step: str,
                 to_var: str, to_step: str):
        self.from_var = from_var
        self.from_step = from_step
        self.to_var = to_var
        self.to_step = to_step

    def __repr__(self):
        return f"{self.from_var}@{self.from_step} → {self.to_var}@{self.to_step}"


class VarGraph:
    """
    Variable-level dependency DAG built from step produces/consumes.

    Usage:
        vg = VarGraph()
        vg.build(steps, dep_graph)
        chain = vg.trace("weather_data")  # → ['city', 'weather_data', 'result_sufficient']
    """

    def __init__(self):
        self.nodes: Dict[str, VarNode] = {}        # keyed by "step_id.var_name"
        self.edges: List[VarEdge] = []
        self._producers: Dict[str, str] = {}        # var_name → "step_id.var_name" node key
        self._node_by_var: Dict[str, List[str]] = {}  # var_name → [node_key, ...]

    def build(self, steps: List[Dict]):
        """Build variable graph from trace steps."""
        # First pass: index all produced variables
        for step in steps:
            sid = step.get("id", "")
            produces = step.get("produces", {})
            if not produces:
                continue
            for var_name, value in produces.items():
                node_key = f"{sid}.{var_name}"
                node = VarNode(
                    name=var_name, step_id=sid, value=value,
                    semantic_type=step.get("semantic_type"),
                )
                self.nodes[node_key] = node
                self._producers[var_name] = node_key

        # Second pass: add edges from producers to consumers
        for step in steps:
            sid = step.get("id", "")
            consumes = step.get("consumes", {})
            if not consumes:
                continue
            for var_name, _ in consumes.items():
                if var_name in self._producers:
                    producer_node_key = self._producers[var_name]
                    # Edge: producer_var → consumer_step consumes this var
                    self.edges.append(VarEdge(
                        from_var=var_name,
                        from_step=producer_node_key.rsplit(".", 1)[0],
                        to_var=var_name,
                        to_step=sid,
                    ))

    def trace(self, var_name: str) -> List[str]:
        """Trace a variable backward through the graph.

        Returns list of step descriptions forming the variable chain.
        """
        if var_name not in self._producers:
            return [f"?? {var_name}"]

        chain = []
        visited = set()
        queue = [var_name]

        while queue:
            v = queue.pop(0)
            if v in visited:
                continue
            visited.add(v)

            producer_key = self._producers.get(v)
            if producer_key and producer_key in self.nodes:
                node = self.nodes[producer_key]
                chain.append(f"{v} ← {node.step_id}")

            # Follow edges backward
            for edge in self.edges:
                if edge.to_var == v and edge.from_var not in visited:
                    queue.append(edge.from_var)

        return chain

    def diff(self, other: "VarGraph") -> List[str]:
        """Compare two variable graphs, return changed variable chains."""
        diffs = []
        all_vars = set(self._producers.keys()) | set(other._producers.keys())

        for var in sorted(all_vars):
            node_a = self.nodes.get(self._producers.get(var, ""))
            node_b = other.nodes.get(other._producers.get(var, ""))
            if node_a and node_b:
                if str(node_a.value) != str(node_b.value):
                    # Find what feeds this variable
                    upstream = self.trace(var)
                    chain_str = " ← ".join(upstream[:4]) if upstream else var
                    diffs.append(
                        f"{var}: {_var_preview(node_a.value)} → "
                        f"{_var_preview(node_b.value)}"
                    )
                    if upstream:
                        diffs.append(f"  chain: {chain_str}")
            elif node_a:
                diffs.append(f"{var}: only in Run A ({_var_preview(node_a.value)})")
            elif node_b:
                diffs.append(f"{var}: only in Run B ({_var_preview(node_b.value)})")

        return diffs


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

    # P3-1: Confidence tag (only for inferred types)
    signal = step.get("semantic_signal", {})
    conf_tag = ""
    if signal and signal.get("source") != "explicit" and signal.get("confidence", 1.0) < 0.95:
        conf_tag = f" [{signal.get('confidence', 0):.0%}]"

    if st == "LLM":
        outputs = step.get("outputs", {})
        result = outputs.get("result", step.get("output", ""))
        result_preview = str(result)[:80] if result else "?"
        desc = f"LLM `{name}` produced: {result_preview}{conf_tag}"

    elif st == "DECISION":
        value = step.get("value")
        produces = step.get("produces", {})
        cond_name = step.get("condition", step.get("name", "?"))
        desc = f"Decision `{cond_name}` = {value}"
        if step.get("true_branch"):
            desc += f" → took '{step['true_branch']}' path"
        desc += conf_tag

    elif st == "TOOL":
        if status == "error" or error:
            desc = f"Tool `{name}` FAILED: {error or 'unknown error'}{conf_tag}"
        else:
            result = step.get("result", step.get("outputs", {}).get("result", "?"))
            desc = f"Tool `{name}` returned: {str(result)[:80]}{conf_tag}"

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
# Diff explanation (P1: variable-level + impact-driven + graph alignment)
# ============================================================

def _filter_all_meaningful(chain_ids: List[str],
                          step_map: Dict[str, Dict]) -> List[str]:
    """Broader filter for diff comparison — includes TOOL/OUTPUT nodes."""
    result = []
    for sid in chain_ids:
        step = step_map.get(sid, {})
        st = step.get("semantic_type", "")
        if st in ("LLM", "DECISION", "TOOL", "OUTPUT", "INPUT"):
            result.append(sid)
    return result


def _step_causal_key(sid: str, step_map: Dict[str, Dict]) -> str:
    """Generate a causal alignment key: produces_keys + semantic_type.

    Two steps align if they produce the same variables or have the same
    semantic role (name without values). This is position-independent.
    """
    step = step_map.get(sid, {})
    produces = step.get("produces", {})
    if produces:
        # Sort keys for stable matching
        return f"PRODUCES:{'|'.join(sorted(produces.keys()))}"
    # Fall back to semantic_name without value suffix
    sem_name = step.get("semantic_name", "")
    if sem_name:
        return f"NAME:{sem_name}"
    return f"TYPE:{step.get('semantic_type', '?')}"


def _align_by_causal_role(chain_a: List[str], chain_b: List[str],
                          step_map_a: Dict, step_map_b: Dict):
    """Align two causal chains by causal role, not position.

    Returns: (aligned_pairs, a_only, b_only)
      aligned_pairs: [(sid_a, sid_b, is_identical), ...]
    """
    # Build causal keys
    keys_a = [(sid, _step_causal_key(sid, step_map_a)) for sid in chain_a]
    keys_b = [(sid, _step_causal_key(sid, step_map_b)) for sid in chain_b]

    aligned = []
    used_b = set()
    a_only = []

    for sid_a, key_a in keys_a:
        # Find matching step in B by causal key
        match = None
        for j, (sid_b, key_b) in enumerate(keys_b):
            if j in used_b:
                continue
            if key_a == key_b or (
                # Also match by semantic_type + produces overlap
                key_a.startswith("PRODUCES:") and key_b.startswith("PRODUCES:") and
                key_a == key_b
            ):
                match = (j, sid_b)
                break
            # Fallback: match by simple TYPE if keys differ
            if (key_a.startswith("TYPE:") and key_b.startswith("TYPE:") and
                key_a == key_b):
                match = (j, sid_b)
                break

        if match:
            used_b.add(match[0])
            sid_b = match[1]
            step_a = step_map_a.get(sid_a, {})
            step_b = step_map_b.get(sid_b, {})
            is_identical = (
                step_a.get("semantic_type") == step_b.get("semantic_type") and
                step_a.get("produces") == step_b.get("produces") and
                step_a.get("value") == step_b.get("value")
            )
            aligned.append((sid_a, sid_b, is_identical))
        else:
            a_only.append(sid_a)

    b_only = [keys_b[j][0] for j in range(len(keys_b)) if j not in used_b]

    return aligned, a_only, b_only


def _diff_variables(sid_a: str, sid_b: str,
                    step_map_a: Dict, step_map_b: Dict) -> List[str]:
    """Compare produces/consumes between two aligned steps.

    Returns list of "key: old → new" strings.
    """
    step_a = step_map_a.get(sid_a, {})
    step_b = step_map_b.get(sid_b, {})
    diffs = []

    # Compare produces keys
    prod_a = step_a.get("produces", {})
    prod_b = step_b.get("produces", {})
    all_keys = set(prod_a.keys()) | set(prod_b.keys())
    for key in sorted(all_keys):
        va = prod_a.get(key)
        vb = prod_b.get(key)
        if va != vb:
            diffs.append(f"{key}: {_var_preview(va)} → {_var_preview(vb)}")

    # Compare consumes keys
    cons_a = step_a.get("consumes", {})
    cons_b = step_b.get("consumes", {})
    all_cons = set(cons_a.keys()) | set(cons_b.keys())
    for key in sorted(all_cons):
        va = cons_a.get(key)
        vb = cons_b.get(key)
        if va != vb and key not in all_keys:  # avoid dupes
            diffs.append(f"input.{key}: {_var_preview(va)} → {_var_preview(vb)}")

    return diffs


def _var_preview(val) -> str:
    """Truncate variable value for display."""
    s = str(val)
    return f'"{s[:50]}"' if len(s) <= 50 else f'"{s[:47]}..."'


def _compute_downstream_impact(divergence_idx: int,
                                aligned: List[tuple],
                                a_only: List[str],
                                b_only: List[str]) -> int:
    """Count how many downstream steps are affected by a divergence point."""
    # Steps after the divergence that differ + exclusive steps
    downstream = 0
    for i in range(divergence_idx, len(aligned)):
        if not aligned[i][2]:  # not identical
            downstream += 1
    downstream += len(a_only) + len(b_only)
    return downstream


def explain_diff(ctx_a: TraceContext, ctx_b: TraceContext) -> str:
    """
    Compare two trace contexts with causal, variable-level analysis.

    Upgrades from P0.5:
    - Graph-based alignment (causal role, not position)
    - Variable-level diff (which key changed: old → new)
    - Impact-driven root cause (blast radius, not type heuristic)
    """
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

    # ── Graph-based alignment ──
    aligned, a_only, b_only = _align_by_causal_role(key_a, key_b, step_map_a, step_map_b)

    lines = []
    lines.append("Causal Chain Comparison:")
    lines.append("-" * 40)

    # Track divergence points for impact analysis
    divergence_points = []  # (index, variable_diffs, step_desc_a, step_desc_b)

    for i, (sid_a, sid_b, is_identical) in enumerate(aligned):
        step_a = step_map_a.get(sid_a, {})
        step_b = step_map_b.get(sid_b, {})
        ca = _explain_step(sid_a, step_map_a)
        cb = _explain_step(sid_b, step_map_b)

        if is_identical:
            lines.append(f"  =  {ca.description}")
        else:
            # Variable-level diff
            var_diffs = _diff_variables(sid_a, sid_b, step_map_a, step_map_b)
            divergence_points.append((i, var_diffs, ca, cb))
            lines.append(f"  A: {ca.description}")
            lines.append(f"  B: {cb.description}")
            if var_diffs:
                for vd in var_diffs:
                    lines.append(f"      var: {vd}")

    # Show exclusive steps
    for sid in a_only:
        ca = _explain_step(sid, step_map_a)
        lines.append(f"  A: {ca.description}")
        lines.append(f"  B: (none)")
    for sid in b_only:
        cb = _explain_step(sid, step_map_b)
        lines.append(f"  A: (none)")
        lines.append(f"  B: {cb.description}")

    # ── Impact-driven root cause ──
    lines.append("")
    lines.append("Root Cause Analysis:")
    lines.append("-" * 40)

    if not divergence_points and not a_only and not b_only:
        lines.append("Both runs followed identical causal chains.")
        return "\n".join(lines)

    # Score each divergence point by blast radius
    best_score = -1
    best_point = None
    for i, var_diffs, ca, cb in divergence_points:
        # Impact = downstream affected + variable count bonus
        downstream = _compute_downstream_impact(i, aligned, a_only, b_only)
        score = downstream * 2 + len(var_diffs)
        if score > best_score:
            best_score = score
            best_point = (i, var_diffs, ca, cb)

    # Build root cause narrative
    if best_point:
        i, var_diffs, ca, cb = best_point

        # Show variable-level root cause first (the key insight)
        if var_diffs:
            lines.append(f"Root cause: variable change")
            for vd in var_diffs:
                lines.append(f"  {vd}")
            lines.append(f"  └ caused by: {ca.description}")
        else:
            lines.append(f"Root cause: {ca.description}")

        # Show downstream cascade
        downstream = _compute_downstream_impact(i, aligned, a_only, b_only)
        if downstream > 0:
            lines.append(f"Downstream impact: {downstream} step(s) affected")
            # Show the cascade
            for j in range(i + 1, len(aligned)):
                if not aligned[j][2]:
                    step_a = _explain_step(aligned[j][0], step_map_a)
                    step_b = _explain_step(aligned[j][1], step_map_b)
                    lines.append(f"  └ {step_a.description}")

        # Show impact score
        total_steps = len(aligned) + len(a_only) + len(b_only)
        lines.append(f"Impact score: {best_score} (blast radius: {downstream}/{total_steps} steps)")

    # ── P3-2: Variable Graph ──
    lines.append("")
    lines.append("Variable Graph:")
    lines.append("-" * 40)

    vg_a = VarGraph()
    vg_a.build(ctx_a.capture.steps)
    vg_b = VarGraph()
    vg_b.build(ctx_b.capture.steps)

    var_diffs = vg_a.diff(vg_b)
    if var_diffs:
        for vd in var_diffs[:8]:  # limit to top 8 variable diffs
            lines.append(f"  {vd}")
    else:
        lines.append("  (no variable-level differences detected)")

    # Show exclusive path differences
    if a_only:
        lines.append(f"Run A exclusive path: {len(a_only)} step(s)")
    if b_only:
        lines.append(f"Run B exclusive path: {len(b_only)} step(s)")

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
        yield {"step_id": None, "outputs": None, "produces": None,
               "consumes": None, "semantic_signal": None}
        return

    step_id = ctx.start_span(name, semantic_type, inputs)
    span_info = {"step_id": step_id, "outputs": None,
                 "produces": None, "consumes": None,
                 "semantic_signal": None}
    try:
        yield span_info
    except Exception as e:
        ctx.end_span(step_id, error=str(e), status="error")
        raise
    else:
        outputs = span_info.get("outputs")
        produces = span_info.get("produces")
        consumes = span_info.get("consumes")
        signal = span_info.get("semantic_signal")

        # P2: auto-extract produces from outputs when not explicitly set
        if produces is None and outputs is not None:
            from .instrument.auto import auto_extract_produces
            result_val = outputs.get("result") if isinstance(outputs, dict) else outputs
            produces = auto_extract_produces(name, result_val, semantic_type)

        ctx.end_span(step_id,
                     outputs=outputs,
                     produces=produces,
                     consumes=consumes,
                     semantic_signal=signal,
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
                          inputs={"query": str(input_data)[:200]})
            ctx.end_span(outputs={"result": str(result)[:500]})

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
