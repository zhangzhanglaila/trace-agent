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
from .trace_diff import TraceDiffer, render_diff, render_causal_verdict
from .instrument.auto import auto_trace


# ============================================================
# Helpers
# ============================================================

def _parse_script_ref(script: str):
    """
    Parse a script reference that may include an object path.

    Supports:
        my_agent.py                  → (my_agent.py, None)
        my_agent.py:agent            → (my_agent.py, "agent")
        my_agent.py:create_agent     → (my_agent.py, "create_agent")
        main.py:app.agent            → (main.py, "app.agent")
        pkg/module.py:MyClass.build  → (pkg/module.py, "MyClass.build")
    """
    if ":" in script:
        # Split on the LAST colon that precedes a Python identifier
        path_part, obj_part = script.rsplit(":", 1)
        if os.path.exists(path_part) or path_part.endswith(".py"):
            return path_part, obj_part
        # If path doesn't exist, maybe the colon is part of a Windows path (D:\...)
        # In that case there's no object reference
        return script, None
    return script, None


def _resolve_dotted(obj, path: str):
    """Resolve dotted attribute path on an object: 'app.agent' → obj.app.agent"""
    for part in path.split("."):
        if part.endswith("()"):
            # Callable invocation: 'create_agent()'
            part = part[:-2]
            obj = getattr(obj, part)
            obj = obj()
        else:
            obj = getattr(obj, part)
    return obj


def _load_module(path: str):
    """Dynamically import a Python module from a file path."""
    path = os.path.abspath(path)
    name = os.path.splitext(os.path.basename(path))[0]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _find_agent(mod, object_path: str = None):
    """
    Find an agent in a module.

    If object_path is given (from module:object syntax):
        Resolve dotted path from the module.
        If the result is callable, call it to get the agent.
        Otherwise return it directly.

    Otherwise, tries common conventions:
        - Variable named 'agent'
        - Class named 'Agent' (instantiate it)
        - First object with a .run() method
    """
    if object_path:
        try:
            obj = _resolve_dotted(mod, object_path)
        except AttributeError:
            raise ValueError(
                f"Object '{object_path}' not found in {mod.__file__}. "
                f"Check the module:object path."
            )
        if isinstance(obj, type):
            # It's a class — instantiate it
            obj = obj()
        elif callable(obj) and not hasattr(obj, "run"):
            # It's a factory function — call it to get the agent
            try:
                obj = obj()
            except TypeError:
                pass
        if hasattr(obj, "run") and callable(obj.run):
            return obj
        raise ValueError(
            f"Object '{object_path}' in {mod.__file__} does not have a .run() method. "
            f"Found: {type(obj).__name__}"
        )

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
    # Auto-enable framework patches (OpenAI, LangChain)
    auto_trace()

    script_path, obj_path = _parse_script_ref(args.script)

    print(f"AgentTrace: Loading {script_path}...")
    mod = _load_module(script_path)
    agent = _find_agent(mod, obj_path)
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
    # Auto-enable framework patches (OpenAI, LangChain)
    auto_trace()

    print("AgentTrace: Debug Mode")
    print("=" * 58)
    print()

    # Load agent
    script_path, obj_path = _parse_script_ref(args.script)
    mod = _load_module(script_path)
    agent = _find_agent(mod, obj_path)
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

    # Render the causal verdict (interview-ready format)
    print(render_causal_verdict(diff_result))

    # Show detailed causal chain if verbose
    if getattr(args, 'verbose', False) and diff_result.causal_narrative:
        print("=" * 58)
        print("  DETAILED CAUSAL CHAIN")
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
    p_debug.add_argument("--verbose", "-v", action="store_true",
                         help="Show detailed causal chain")
    p_debug.set_defaults(func=cmd_debug)

    # agent-demo
    p_demo = sub.add_parser("demo", help="One-click demo: run agent, start UI")
    p_demo.add_argument("--bug", choices=["on", "off"], default="on",
                        help="Enable/disable LLM misroute bug (default: on)")
    p_demo.add_argument("--port", type=int, default=8765,
                        help="Backend API port (default: 8765)")
    p_demo.add_argument("--no-browser", action="store_true",
                        help="Don't auto-open browser")
    p_demo.set_defaults(func=cmd_demo)

    # agent-dev
    p_dev = sub.add_parser("dev", help="One-command debugger: run your agent + open UI")
    p_dev.add_argument("script", help="Path to your agent script (e.g., my_agent.py)")
    p_dev.add_argument("--input", "-i", required=True,
                       help="Input for run A")
    p_dev.add_argument("--input2", "-j", required=True,
                       help="Input for run B (compare against)")
    p_dev.add_argument("--port", type=int, default=8765,
                       help="Backend API port (default: 8765)")
    p_dev.add_argument("--no-browser", action="store_true",
                       help="Don't auto-open browser")
    p_dev.set_defaults(func=cmd_dev)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1
    return args.func(args)


def cmd_demo(args):
    """One-click demo: run Travel Planner, start backend + frontend, open browser."""
    import os
    demo_script = os.path.join(os.path.dirname(os.path.dirname(__file__)), "demo.py")
    argv = [sys.executable, demo_script,
            "--bug", args.bug,
            "--port", str(args.port)]
    if args.no_browser:
        argv.append("--no-browser")
    os.execv(sys.executable, argv)


def cmd_dev(args):
    """One-command debugger: run YOUR agent twice, diff, open UI."""
    import os
    import json
    import time
    import signal
    import subprocess
    import webbrowser

    auto_trace()

    script_path, obj_path = _parse_script_ref(args.script)
    script_path = os.path.abspath(script_path)
    ui_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "agent-trace-ui")
    dev_json_path = os.path.join(ui_dir, "public", "dev_trace.json")

    print()
    print("=" * 55)
    print("  AgentTrace Dev :: Live Debugger")
    print("=" * 55)
    print()

    # ── Step 1: Load & run agent ──
    print("=" * 55)
    print("  Step 1/3: Running your agent (2x)...")
    print("=" * 55)

    mod = _load_module(script_path)
    agent = _find_agent(mod, obj_path)
    print(f"  Agent: {agent.__class__.__name__}")
    if obj_path:
        print(f"  Entry: {script_path}:{obj_path}")
    print(f"  Script: {script_path}")

    input_a = _resolve_input(args.input)
    input_b = _resolve_input(args.input2)

    traced_a = TracedAgent(agent)
    print(f"\n  [Run A] Input: {input_a[:80]}")
    result_a = traced_a.run(input_a)
    trace_a_path = traced_a.last_trace_path
    print(f"    => {str(result_a)[:100]}")

    traced_b = TracedAgent(agent, out_dir=os.path.dirname(trace_a_path) or ".")
    print(f"\n  [Run B] Input: {input_b[:80]}")
    result_b = traced_b.run(input_b)
    trace_b_path = traced_b.last_trace_path
    print(f"    => {str(result_b)[:100]}")

    # ── Step 2: Diff & generate UI JSON ──
    print(f"\n  Diffing traces...")
    from .frontend_adapter import adapt_diff_result

    export_a = TraceExport.from_file(trace_a_path)
    export_b = TraceExport.from_file(trace_b_path)
    differ = TraceDiffer(export_a, export_b)
    diff_result = differ.diff()

    if traced_a.last_ctx and traced_b.last_ctx:
        diff_result.causal_narrative = explain_diff(traced_a.last_ctx, traced_b.last_ctx)
        _enrich_causal_chain(diff_result, traced_a.last_ctx, traced_b.last_ctx)

    ui_json = adapt_diff_result(diff_result, export_a, export_b)

    # Write to public/dev_trace.json
    os.makedirs(os.path.dirname(dev_json_path), exist_ok=True)
    with open(dev_json_path, "w", encoding="utf-8") as f:
        json.dump(ui_json, f, indent=2, ensure_ascii=False)
    print(f"  Trace written: {dev_json_path}")

    # Print verdict
    print(f"\n  [verdict] {ui_json['verdict'][:120]}")
    if ui_json.get("diagnosis"):
        d = ui_json["diagnosis"]
        print(f"  [diagnosis]  {d['type']} ({d['confidence']})")

    # Cleanup raw trace files
    for t in [trace_a_path, trace_b_path]:
        try:
            os.remove(t)
        except OSError:
            pass

    # ── Step 3: Start backend + frontend ──
    print(f"\n" + "=" * 55)
    print(f"  Step 2/3: Starting backend + frontend...")
    print("=" * 55)

    port = args.port

    # Backend
    backend_proc = subprocess.Popen(
        [sys.executable, os.path.join(ui_dir, "server.py"), "--port", str(port)],
        cwd=ui_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    time.sleep(1.5)
    print(f"  Backend: http://127.0.0.1:{port}")

    # Frontend
    node_ok = False
    try:
        subprocess.run(["node", "--version"], capture_output=True, timeout=5)
        node_ok = True
    except Exception:
        pass

    if node_ok:
        try:
            if not os.path.exists(os.path.join(ui_dir, "node_modules")):
                print("  Installing npm dependencies (first run)...")
                subprocess.run(["npm", "install"], cwd=ui_dir, capture_output=True)

            frontend_proc = subprocess.Popen(
                ["npm", "run", "dev"],
                cwd=ui_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            time.sleep(3)
            print(f"  Frontend: http://localhost:5173")
        except Exception as e:
            print(f"  [WARN] Frontend failed: {e}")
            frontend_proc = None
    else:
        print("  [WARN] Node.js not found. Open agent-trace-ui/dist/index.html manually.")
        frontend_proc = None

    # ── Step 4: Open browser ──
    print(f"\n" + "=" * 55)
    print(f"  Step 3/3: Opening browser...")
    print("=" * 55)

    if not args.no_browser:
        time.sleep(1)
        webbrowser.open("http://localhost:5173")
        print(f"  Browser opened.")

    print()
    print("  ╔" + "═" * 53 + "╗")
    print("  ║  [OK] AgentTrace Dev is live!                        ║")
    print("  ║                                                   ║")
    print("  ║  UI:  http://localhost:5173                        ║")
    print(f"  ║  API: http://127.0.0.1:{port}/api/trace/dev        ║")
    print("  ║                                                   ║")
    print("  ║  Press Ctrl+C to stop all services                ║")
    print("  ╚" + "═" + 53 + "╝")
    print()

    def shutdown(sig, frame):
        print("\n  Shutting down...")
        if frontend_proc:
            frontend_proc.terminate()
        if backend_proc:
            backend_proc.terminate()
        print("  Done.")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown(None, None)


if __name__ == "__main__":
    sys.exit(main())
