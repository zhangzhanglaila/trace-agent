"""
AgentTrace CLI: agent-run, agent-diff, agent-debug.

Usage:
    python -m agent_obs.cli_main run run.py --input "query"
    python -m agent_obs.cli_main diff trace1.json trace2.json
    python -m agent_obs.cli_main debug run.py --input "A" --input2 "B"
"""
import sys
import os
import json
import argparse
import importlib.util
from pathlib import Path

from .trace_core import TracedAgent, explain_diff
from .trace_export import TraceExport
from .trace_diff import TraceDiffer, render_diff


# ============================================================
# Helpers
# ============================================================

def _load_module(path: str):
    """Dynamically import a Python module from a file path."""
    path = os.path.abspath(path)
    name = os.path.splitext(os.path.basename(path))[0]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _find_agent(mod):
    """
    Find an agent in a module. Tries common conventions:
    - Variable named 'agent'
    - Class named 'Agent' (instantiate it)
    - First object with a .run() method
    """
    # 1. Look for 'agent' variable
    if hasattr(mod, "agent"):
        return mod.agent

    # 2. Look for 'Agent' class
    if hasattr(mod, "Agent"):
        return mod.Agent()

    # 3. Look for anything with a .run() method
    for name in dir(mod):
        if name.startswith("_"):
            continue
        obj = getattr(mod, name)
        if hasattr(obj, "run") and callable(obj.run):
            return obj

    raise ValueError(
        f"No agent found in {mod.__file__}. "
        f"Define a variable 'agent' or a class 'Agent' with a .run() method."
    )


def _resolve_input(input_val: str):
    """Resolve input: a string, a @filepath, or a JSON string."""
    if input_val.startswith("@"):
        # Read from file
        path = input_val[1:]
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    return input_val


# ============================================================
# agent-run
# ============================================================

def cmd_run(args):
    """Run an agent with tracing and export the trace."""
    print(f"AgentTrace: Loading {args.script}...")
    mod = _load_module(args.script)
    agent = _find_agent(mod)
    print(f"  Agent: {agent.__class__.__name__}")

    traced = TracedAgent(agent, out_dir=os.path.dirname(args.out) or ".")

    input_data = _resolve_input(args.input)
    print(f"  Input: {input_data[:80]}")

    try:
        result = traced.run(input_data)
    except Exception as e:
        print(f"  ERROR: {e}")
        result = str(e)

    # Export
    out_path = args.out
    if traced.last_trace_path and out_path != traced.last_trace_path:
        # Copy/re-export to requested path
        export_data = json.loads(open(traced.last_trace_path, encoding="utf-8").read())
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
    elif traced.last_trace_path:
        out_path = traced.last_trace_path

    print(f"  Trace: {out_path}")
    print(f"  Result: {str(result)[:120]}")
    return 0


# ============================================================
# agent-diff
# ============================================================

def cmd_diff(args):
    """Load two trace JSON files and show the semantic diff."""
    print(f"AgentTrace: Loading traces...")
    trace_a = TraceExport.from_file(args.trace1)
    trace_b = TraceExport.from_file(args.trace2)
    print(f"  Run A: {trace_a.trace_id} ({len(trace_a.runs)} steps)")
    print(f"  Run B: {trace_b.trace_id} ({len(trace_b.runs)} steps)")

    differ = TraceDiffer(trace_a, trace_b)
    diff_result = differ.diff()

    print(render_diff(diff_result))

    if args.json:
        print(diff_result.to_json())

    return 0


# ============================================================
# agent-debug
# ============================================================

def cmd_debug(args):
    """Run an agent twice with different inputs, diff, and explain."""
    print("AgentTrace: Debug Mode")
    print("=" * 58)
    print()

    # Load agent
    mod = _load_module(args.script)
    agent = _find_agent(mod)
    traced = TracedAgent(agent)

    # Run A
    input_a = _resolve_input(args.input)
    print(f"[Run A] Input: {input_a[:80]}")
    result_a = traced.run(input_a)
    trace_a_path = traced.last_trace_path
    print(f"  Result: {str(result_a)[:80]}")
    print(f"  Trace: {trace_a_path}")
    print()

    # Run B (new TracedAgent to get separate trace file)
    input_b = _resolve_input(args.input2)
    traced_b = TracedAgent(agent, out_dir=os.path.dirname(trace_a_path) or ".")
    print(f"[Run B] Input: {input_b[:80]}")
    result_b = traced_b.run(input_b)
    trace_b_path = traced_b.last_trace_path
    print(f"  Result: {str(result_b)[:80]}")
    print(f"  Trace: {trace_b_path}")
    print()

    # Diff with causal enrichment
    trace_a = TraceExport.from_file(trace_a_path)
    trace_b = TraceExport.from_file(trace_b_path)
    differ = TraceDiffer(trace_a, trace_b)
    diff_result = differ.diff()

    # Enrich with causal explanation from TraceContext
    if traced.last_ctx and traced_b.last_ctx:
        causal_narrative = explain_diff(traced.last_ctx, traced_b.last_ctx)
        diff_result.causal_narrative = causal_narrative
        _enrich_causal_chain(diff_result, traced.last_ctx, traced_b.last_ctx)

    # Render engineer-level diff
    print(render_diff(diff_result, level=2))

    # Show causal explanation if available
    if diff_result.causal_narrative:
        print("=" * 58)
        print("  CAUSAL EXPLANATION")
        print("=" * 58)
        print(diff_result.causal_narrative)
        print()

    return 0


def _enrich_causal_chain(diff_result, ctx_a, ctx_b):
    """Add causal chain to diff result by comparing backward slices."""
    if not diff_result.has_diverged:
        return

    # Get backward slices from the last meaningful step in each trace
    steps_a = ctx_a.capture.steps
    steps_b = ctx_b.capture.steps

    # Find the last tool/decision/llm step (not input/output wrapper)
    def _last_meaningful(steps):
        for s in reversed(steps):
            st = s.get("semantic_type", "")
            if st in ("LLM", "TOOL", "DECISION"):
                return s
        return steps[-1] if steps else None

    last_a = _last_meaningful(steps_a)
    last_b = _last_meaningful(steps_b)

    if last_a and last_b:
        chain_a = ctx_a.backward_slice(last_a["id"])
        chain_b = ctx_b.backward_slice(last_b["id"])

        # Build step name lookup
        names_a = {s["id"]: s.get("semantic_name", s["id"]) for s in steps_a}
        names_b = {s["id"]: s.get("semantic_name", s["id"]) for s in steps_b}

        # Find where chains diverge
        causal = []
        for i, (sa, sb) in enumerate(zip(chain_a, chain_b)):
            na = names_a.get(sa, sa)
            nb = names_b.get(sb, sb)
            if na == nb:
                causal.append(na)
            else:
                causal.append(f"{na} (A) / {nb} (B)")
                break
        diff_result.causal_chain = causal


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        prog="agenttrace",
        description="AgentTrace: Trace, Diff, and Debug agent executions.",
    )
    sub = parser.add_subparsers(dest="command", help="Commands")

    # agent-run
    p_run = sub.add_parser("run", help="Run an agent with tracing")
    p_run.add_argument("script", help="Path to agent script (e.g., run.py)")
    p_run.add_argument("--input", "-i", required=True,
                       help="Input to the agent (use @file to read from file)")
    p_run.add_argument("--out", "-o", default="trace.json",
                       help="Output trace JSON path")
    p_run.set_defaults(func=cmd_run)

    # agent-diff
    p_diff = sub.add_parser("diff", help="Diff two trace JSON files")
    p_diff.add_argument("trace1", help="First trace JSON")
    p_diff.add_argument("trace2", help="Second trace JSON")
    p_diff.add_argument("--json", action="store_true",
                        help="Also output JSON diff")
    p_diff.set_defaults(func=cmd_diff)

    # agent-debug
    p_debug = sub.add_parser("debug", help="Run twice, diff, explain")
    p_debug.add_argument("script", help="Path to agent script")
    p_debug.add_argument("--input", "-i", required=True,
                         help="Input for run A")
    p_debug.add_argument("--input2", "-j", required=True,
                         help="Input for run B")
    p_debug.set_defaults(func=cmd_debug)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
