"""
Frontend adapter: converts TraceDiffResult + TraceExport → unified JSON protocol.

Produces the single JSON the Vue3 debug UI consumes:
  { verdict, diagnosis, root_cause, graph: {nodes, edges}, diff: {first_divergence, path_impact} }
"""
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import json

from .trace_diff import (
    TraceDiffResult, _build_verdict, _extract_root_variable,
    _classify_error, _suggest_fix,
)
from .trace_export import TraceExport


# ── Node type constants ──
NODE_COLORS = {
    "llm":    "#409EFF",  # Blue
    "tool":   "#67C23A",  # Green
    "branch": "#E6A23C",  # Orange
    "merge":  "#909399",  # Grey
    "output": "#F56C6C",  # Red
    "error":  "#F56C6C",  # Red
}


def adapt_diff_result(diff: TraceDiffResult,
                      export_a: TraceExport,
                      export_b: TraceExport) -> Dict[str, Any]:
    """
    Convert a TraceDiffResult + two TraceExports into the unified frontend JSON.

    Args:
        diff: The diff result from TraceDiffer.diff()
        export_a: TraceExport for run A
        export_b: TraceExport for run B

    Returns:
        Dict matching the frontend TraceData protocol
    """
    narrative = diff.causal_narrative or ""
    output_a = str(diff.output_a)[:200] if diff.output_a else ""
    output_b = str(diff.output_b)[:200] if diff.output_b else ""

    # ── Verdict ──
    verdict = _build_verdict(diff, narrative)

    # ── Root cause ──
    root_var, var_a, var_b, var_source = _extract_root_variable(diff, narrative)

    # ── Diagnosis ──
    error_type, confidence, category = _classify_error(diff, narrative)
    fix_list = _suggest_fix(error_type, root_var, diff, narrative)
    fix_suggestion = "\n".join(fix_list) if fix_list else ""

    # ── Graph ──
    graph = _build_graph(export_a, export_b, diff)

    # ── Diff ──
    diff_section = _build_diff_section(diff)

    # ── Natural language explanation ──
    explanation = _build_explanation(verdict, root_var, var_a, var_b, diff, narrative)

    return {
        "verdict": verdict,
        "diagnosis": {
            "type": error_type,
            "confidence": confidence,
            "category": category,
        },
        "root_cause": {
            "variable": root_var,
            "run_a": var_a,
            "run_b": var_b,
            "source": var_source,
        },
        "graph": graph,
        "diff": diff_section,
        "output": {
            "run_a": output_a,
            "run_b": output_b,
            "diverged": diff.output_diverged,
        },
        "fix_suggestion": fix_suggestion,
        "explanation": explanation,
        "meta": {
            "trace_id_a": diff.trace_id_a,
            "trace_id_b": diff.trace_id_b,
            "run_a_steps": len(export_a.runs),
            "run_b_steps": len(export_b.runs),
        },
    }


def _build_explanation(verdict: str, root_var: str,
                      var_a: str, var_b: str,
                      diff: TraceDiffResult,
                      narrative: str) -> str:
    """Build a natural language explanation from diff data."""
    if not diff.has_diverged:
        return "Both runs produced identical outputs — no divergence detected."

    parts = [verdict.rstrip(".") if verdict else "Run B diverged from Run A."]

    if diff.first_divergence:
        fd = diff.first_divergence
        parts.append(
            f"The first divergence occurred at \"{fd.id}\": "
            f"Run A used {fd.run_a}, but Run B used {fd.run_b}."
        )

    if root_var and var_a and var_b:
        parts.append(
            f"Root cause: variable `{root_var}` was `{var_a}` in Run A "
            f"but `{var_b}` in Run B."
        )

    if diff.output_diverged:
        parts.append("This divergence caused the final outputs to differ.")

    return " ".join(parts)


def _build_graph(export_a: TraceExport, export_b: TraceExport,
                 diff: TraceDiffResult) -> Dict[str, Any]:
    """Build the unified graph representation from both runs."""
    nodes: List[Dict] = []
    edges: List[Dict] = []

    # ── Determine which run is the "primary" view ──
    # Use the run with more steps (richer pipeline) as primary for graph display.
    # The secondary run's nodes are still available for comparison view.
    if len(export_b.runs) >= len(export_a.runs):
        primary_run = export_b
        secondary_run = export_a
    else:
        primary_run = export_a
        secondary_run = export_b

    # ── Collect divergence step names ──
    diverged_steps: set = set()
    first_div_id = None
    if diff.first_divergence:
        first_div_id = diff.first_divergence.id
    if diff.step_diffs:
        for sd in diff.step_diffs:
            if sd.diverged:
                diverged_steps.add(sd.step_name)

    # ── Build nodes from primary run ──
    for i, run in enumerate(primary_run.runs):
        node_type = _map_run_type(run.run_type)
        status = run.status
        if run.error:
            status = "error"

        # Check if this node is on a diverged path
        is_diverged = run.name in diverged_steps or run.id in diverged_steps

        node = {
            "id": run.id,
            "name": run.name or run.id,
            "type": node_type,
            "label": _node_label(run),
            "status": status,
            "inputs": _safe_dict(run.inputs),
            "outputs": _safe_dict(run.outputs),
            "error": run.error,
            "latency_ms": run.latency_ms,
            "diverged": is_diverged,
            "step_index": i,
        }
        nodes.append(node)

        # ── Edge from previous step ──
        if i > 0:
            prev = primary_run.runs[i - 1]
            edges.append({
                "source": prev.id,
                "target": run.id,
                "type": "sequential",
                "style": "solid",
            })

    # ── Add branch edges (from branch metadata) ──
    if export_a.branches:
        for branch in export_a.branches:
            branch_id = branch.get("branch_id", "")
            true_target = branch.get("true_target")
            false_target = branch.get("false_target")
            if true_target:
                edges.append({
                    "source": branch_id,
                    "target": true_target,
                    "type": "branch_true",
                    "style": "solid",
                    "label": "T",
                })
            if false_target:
                edges.append({
                    "source": branch_id,
                    "target": false_target,
                    "type": "branch_false",
                    "style": "dashed",
                    "label": "F",
                })

    # ── Mark divergence point ──
    if first_div_id:
        for node in nodes:
            if node["name"] == first_div_id or node["id"] == first_div_id:
                node["is_divergence_point"] = True
                break

    # ── Mark root cause node ──
    root_var, _, _, _ = _extract_root_variable(diff, diff.causal_narrative or "")
    if root_var:
        for node in nodes:
            outputs = node.get("outputs", {})
            if root_var in outputs or root_var in str(outputs):
                node["is_root_cause"] = True
                break

    # ── Also include secondary run nodes for comparison ──
    secondary_nodes = []
    for run in secondary_run.runs:
        secondary_nodes.append({
            "id": run.id,
            "name": run.name or run.id,
            "type": _map_run_type(run.run_type),
            "label": _node_label(run),
            "status": run.status if not run.error else "error",
            "error": run.error,
        })

    return {
        "nodes": nodes,
        "edges": edges,
        "primary_run": "run_b" if primary_run is export_b else "run_a",
        "secondary_nodes": secondary_nodes,
    }


def _build_diff_section(diff: TraceDiffResult) -> Dict[str, Any]:
    """Build the diff section of the protocol."""
    first_div = None
    if diff.first_divergence:
        first_div = {
            "type": diff.first_divergence.type,
            "id": diff.first_divergence.id,
            "description": diff.first_divergence.description,
            "run_a": str(diff.first_divergence.run_a)[:120] if diff.first_divergence.run_a else None,
            "run_b": str(diff.first_divergence.run_b)[:120] if diff.first_divergence.run_b else None,
        }

    step_diffs = []
    for sd in diff.step_diffs:
        step_diffs.append({
            "step_name": sd.step_name,
            "only_in": sd.only_in,
            "run_a_status": sd.run_a_status,
            "run_b_status": sd.run_b_status,
            "run_a_error": sd.run_a_error,
            "run_b_error": sd.run_b_error,
            "diverged": sd.diverged,
        })

    branch_diffs = []
    for bd in diff.branch_diffs:
        branch_diffs.append({
            "branch_id": bd.branch_id,
            "condition": bd.condition,
            "run_a_path": bd.run_a_path,
            "run_b_path": bd.run_b_path,
            "diverged": bd.diverged,
        })

    path_impact = _build_path_impact(diff)

    return {
        "first_divergence": first_div,
        "step_diffs": step_diffs,
        "branch_diffs": branch_diffs,
        "path_impact": path_impact,
        "has_diverged": diff.has_diverged,
        "output_diverged": diff.output_diverged,
    }


def _build_path_impact(diff: TraceDiffResult) -> List[Dict]:
    """Build step-by-step path comparison for the cascade view."""
    impact = []
    run_a = diff.run_a_path or []
    run_b = diff.run_b_path or []
    max_len = max(len(run_a), len(run_b))

    diverged = False
    for i in range(max_len):
        step_a = run_a[i] if i < len(run_a) else None
        step_b = run_b[i] if i < len(run_b) else None

        if not diverged and step_a != step_b:
            diverged = True

        impact.append({
            "index": i,
            "run_a": step_a,
            "run_b": step_b,
            "diverged": diverged,
        })

    return impact


# ── Helpers ──

def _map_run_type(run_type: str) -> str:
    """Map TraceRun.run_type to frontend node type."""
    mapping = {
        "llm": "llm",
        "tool": "tool",
        "chain": "tool",
        "branch": "branch",
        "merge": "merge",
        "output": "output",
    }
    return mapping.get(run_type, "tool")


def _node_label(run) -> str:
    """Build a human-readable label for a node."""
    run_type = run.run_type
    name = run.name or ""
    if run_type == "llm":
        prompt = str(run.inputs.get("prompt", ""))[:40] if run.inputs else ""
        return f"LLM: {prompt}" if prompt else f"LLM: {name}"
    elif run_type == "tool":
        tool_name = run.inputs.get("tool_name", "") if run.inputs else ""
        return tool_name or name or "Tool"
    elif run_type == "branch":
        condition = run.inputs.get("condition", "") if run.inputs else ""
        return f"Branch: {condition}" if condition else "Branch"
    elif run_type == "merge":
        return "Merge"
    elif run_type == "output":
        return "Output"
    return name or run_type


def _safe_dict(d) -> Dict[str, Any]:
    """Convert to dict safely, handling non-dict inputs."""
    if d is None:
        return {}
    if isinstance(d, dict):
        return {k: _safe_val(v) for k, v in d.items()}
    return {"_value": str(d)[:200]}


def _safe_val(v: Any) -> Any:
    """Truncate large values for display."""
    s = str(v)
    if len(s) > 300:
        return s[:300] + "..."
    return v


# ── Demo data generator ──

def generate_demo_json() -> str:
    """Generate demo JSON for frontend development without running a full trace."""
    demo = {
        "verdict": "Run B failed because the LLM router selected `summarize` "
                   "instead of `activity_search` — the wrong tool received "
                   "incompatible arguments, triggering an error cascade.",
        "diagnosis": {
            "type": "LLM Hallucination → Error Cascade",
            "confidence": "High",
            "category": "Planning Error",
        },
        "root_cause": {
            "variable": "selected_tool",
            "run_a": "activity_search",
            "run_b": "summarize",
            "source": "LLM output (step 3)",
        },
        "graph": {
            "nodes": [
                {"id": "s1", "name": "classify_intent", "type": "llm",
                 "label": "LLM: classify_intent", "status": "success",
                 "inputs": {"prompt": "Trip to Paris for hiking"},
                 "outputs": {"intent": "advice_request"}, "latency_ms": 12.0,
                 "diverged": False, "step_index": 0,
                 "is_divergence_point": False, "is_root_cause": False},
                {"id": "s2", "name": "planner_llm", "type": "llm",
                 "label": "LLM: planner_llm", "status": "success",
                 "inputs": {"query": "Trip to Paris for hiking"},
                 "outputs": {"plan": {"tool": "weather_current", "args": {"city": "paris"}}},
                 "latency_ms": 8.0, "diverged": False, "step_index": 1},
                {"id": "s3", "name": "weather_current", "type": "tool",
                 "label": "Tool: weather_current", "status": "success",
                 "inputs": {"city": "paris"},
                 "outputs": {"weather_current_result": {"temp": 18, "condition": "cloudy"}},
                 "latency_ms": 5.0, "diverged": False, "step_index": 2},
                {"id": "s4", "name": "planner_llm", "type": "llm",
                 "label": "LLM: planner_llm", "status": "success",
                 "inputs": {"query": "Trip to Paris for hiking"},
                 "outputs": {"plan": {"tool": "activity_search"}},
                 "latency_ms": 9.0, "diverged": False, "step_index": 3},
                {"id": "s5", "name": "activity_search", "type": "tool",
                 "label": "Tool: activity_search", "status": "success",
                 "inputs": {"activity": "hiking"},
                 "outputs": {"activity_result": "Ideal hiking conditions."},
                 "latency_ms": 3.0, "diverged": False, "step_index": 4,
                 "is_divergence_point": True, "is_root_cause": True},
                {"id": "s5b", "name": "summarize", "type": "tool",
                 "label": "Tool: summarize", "status": "error",
                 "inputs": {"text": "hiking conditions"},
                 "outputs": {},
                 "error": "Summarization failed: model confidence too low",
                 "latency_ms": 2.0, "diverged": True, "step_index": 4},
                {"id": "s6", "name": "planner_llm", "type": "llm",
                 "label": "LLM: planner_llm (retry)", "status": "error",
                 "inputs": {"query": "retry: Trip to Paris for hiking"},
                 "outputs": {}, "latency_ms": 7.0,
                 "diverged": True, "step_index": 5},
                {"id": "s7", "name": "summarize", "type": "tool",
                 "label": "Tool: summarize (retry)", "status": "error",
                 "inputs": {"text": "retry context"},
                 "outputs": {},
                 "error": "Summarization failed: model confidence too low",
                 "latency_ms": 2.0, "diverged": True, "step_index": 6},
            ],
            "edges": [
                {"source": "s1", "target": "s2", "type": "sequential", "style": "solid"},
                {"source": "s2", "target": "s3", "type": "sequential", "style": "solid"},
                {"source": "s3", "target": "s4", "type": "sequential", "style": "solid"},
                {"source": "s4", "target": "s5", "type": "branch_true", "style": "solid", "label": "T"},
                {"source": "s4", "target": "s5b", "type": "branch_false", "style": "dashed", "label": "F"},
                {"source": "s5b", "target": "s6", "type": "sequential", "style": "solid"},
                {"source": "s6", "target": "s7", "type": "sequential", "style": "solid"},
            ],
            "primary_run": "run_b",
            "secondary_nodes": [],
        },
        "diff": {
            "first_divergence": {
                "type": "step",
                "id": "activity_search",
                "description": "Run A selected activity_search, Run B selected summarize",
                "run_a": "activity_search",
                "run_b": "summarize",
            },
            "step_diffs": [
                {"step_name": "classify_intent", "only_in": None, "run_a_status": "success",
                 "run_b_status": "success", "run_a_error": None, "run_b_error": None, "diverged": False},
                {"step_name": "planner_llm", "only_in": None, "run_a_status": "success",
                 "run_b_status": "success", "run_a_error": None, "run_b_error": None, "diverged": False},
                {"step_name": "weather_current", "only_in": None, "run_a_status": "success",
                 "run_b_status": "success", "run_a_error": None, "run_b_error": None, "diverged": False},
                {"step_name": "selected_tool", "only_in": None, "run_a_status": "success",
                 "run_b_status": "success", "run_a_error": None, "run_b_error": None, "diverged": True},
                {"step_name": "summarize", "only_in": "run_b", "run_a_status": None,
                 "run_b_status": "error", "run_a_error": None,
                 "run_b_error": "Summarization failed", "diverged": True},
            ],
            "branch_diffs": [],
            "path_impact": [
                {"index": 0, "run_a": "classify_intent", "run_b": "classify_intent", "diverged": False},
                {"index": 1, "run_a": "planner_llm", "run_b": "planner_llm", "diverged": False},
                {"index": 2, "run_a": "weather_current", "run_b": "weather_current", "diverged": False},
                {"index": 3, "run_a": "planner_llm", "run_b": "planner_llm", "diverged": False},
                {"index": 4, "run_a": "activity_search", "run_b": "summarize", "diverged": True},
                {"index": 5, "run_a": None, "run_b": "planner_llm (retry)", "diverged": True},
                {"index": 6, "run_a": None, "run_b": "summarize (retry)", "diverged": True},
            ],
            "has_diverged": True,
            "output_diverged": True,
        },
        "output": {
            "run_a": "[OK] Activity advice: Ideal hiking conditions.",
            "run_b": "[FAIL] Summarization failed: model confidence too low",
            "diverged": True,
        },
        "fix_suggestion": (
            "Consider adding a tool selection guardrail:\n"
            "  Define explicit preconditions for: activity_search, summarize\n"
            "  When weather is available, prefer activity_search over summarize."
        ),
        "explanation": (
            "Run B failed because at the decision step, the agent selected `summarize` "
            "instead of `activity_search`. This divergence at step 4 caused the summarize "
            "tool to receive incompatible activity data, which failed and triggered a retry "
            "cascade that exhausted the step budget. Root cause: variable `selected_tool` "
            "was `activity_search` in Run A but `summarize` in Run B. "
            "Recommendation: add a tool selection guardrail that checks preconditions before routing."
        ),
        "meta": {
            "trace_id_a": "trace_demo_a",
            "trace_id_b": "trace_demo_b",
            "run_a_steps": 5,
            "run_b_steps": 7,
        },
    }
    return json.dumps(demo, indent=2, ensure_ascii=False)
