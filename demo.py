#!/usr/bin/env python3
"""
AgentTrace — One-Click Demo

Usage:
    agenttrace demo                    # Run with bug enabled (default)
    agenttrace demo --bug off          # Run without bug (baseline comparison)
    agenttrace demo --port 8765        # Custom backend port

This single command:
    1. Runs the Travel Planner Agent (generates trace)
    2. Starts the backend API server
    3. Starts the DevTools UI
    4. Opens your browser

Press Ctrl+C to stop all services.
"""
import sys
import os
import time
import json
import signal
import subprocess
import argparse
import webbrowser
from pathlib import Path

ROOT = Path(__file__).parent
UI_DIR = ROOT / "agent-trace-ui"


def generate_trace(bug_enabled: bool = True) -> bool:
    """Run the Travel Planner agent and export trace JSON for the UI."""
    print("\n" + "=" * 55)
    print("  Step 1/4: Generating agent trace...")
    print("=" * 55)

    os.chdir(str(ROOT))
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "examples"))

    from examples.travel_planner import TravelPlanner
    from agent_obs.trace_core import TracedAgent, explain_diff
    from agent_obs.trace_export import TraceExport
    from agent_obs.trace_diff import TraceDiffer
    from agent_obs.frontend_adapter import adapt_diff_result

    # If bug is off, also set LLM_MISROUTE_ENABLED = False
    import examples.travel_planner as tp
    tp.LLM_MISROUTE_ENABLED = bug_enabled

    print(f"  Bug injection: {'ON  (LLM will misroute)' if bug_enabled else 'OFF (baseline — both runs correct)'}")

    # Run A: Tokyo (always correct)
    print("  [Run A] Tokyo — correct path...")
    agent_a = TravelPlanner(enable_bug=False, max_steps=8)
    traced_a = TracedAgent(agent_a, out_dir=".")
    result_a = traced_a.run("Plan a trip to Tokyo for hiking")
    print(f"    => {str(result_a)[:100]}")

    # Run B: Paris (bug if enabled)
    print(f"  [Run B] Paris — {'bug active' if bug_enabled else 'correct path'}...")
    agent_b = TravelPlanner(enable_bug=bug_enabled, max_steps=5 if bug_enabled else 8)
    traced_b = TracedAgent(agent_b, out_dir=".")
    result_b = traced_b.run("Plan a trip to Paris for hiking")
    print(f"    => {str(result_b)[:100]}")

    # Diff
    export_a = TraceExport.from_file(traced_a.last_trace_path)
    export_b = TraceExport.from_file(traced_b.last_trace_path)
    differ = TraceDiffer(export_a, export_b)
    diff_result = differ.diff()
    if traced_a.last_ctx and traced_b.last_ctx:
        diff_result.causal_narrative = explain_diff(traced_a.last_ctx, traced_b.last_ctx)

    # Adapt to frontend JSON
    ui_json = adapt_diff_result(diff_result, export_a, export_b)

    # Add bug toggle state to meta
    ui_json["meta"]["bug_enabled"] = bug_enabled

    # Write to public dir
    out_path = UI_DIR / "public" / "demo_trace.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(ui_json, f, indent=2, ensure_ascii=False)

    print(f"  Trace exported: {out_path}")

    # Cleanup
    for t in [traced_a.last_trace_path, traced_b.last_trace_path]:
        try:
            os.remove(t)
        except OSError:
            pass

    # Print verdict
    print(f"\n  📋 {ui_json['verdict'][:120]}...")
    if ui_json.get("diagnosis"):
        d = ui_json["diagnosis"]
        print(f"  🏷  {d['type']} ({d['confidence']})")

    return True


def check_node_installed() -> bool:
    """Check if Node.js is available."""
    try:
        subprocess.run(["node", "--version"], capture_output=True, timeout=5)
        return True
    except Exception:
        return False


def check_npm_installed() -> bool:
    """Check if npm install has been run."""
    return (UI_DIR / "node_modules").exists()


def start_backend(port: int, bug_enabled: bool) -> subprocess.Popen:
    """Start the Python backend API server."""
    print(f"\n  Step 2/4: Starting backend API (port {port})...")

    env = os.environ.copy()
    env["AGENTTRACE_BUG_ENABLED"] = str(bug_enabled).lower()

    proc = subprocess.Popen(
        [sys.executable, str(UI_DIR / "server.py"), "--port", str(port)],
        cwd=str(UI_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    time.sleep(1.5)
    print(f"  Backend: http://127.0.0.1:{port}")
    return proc


def start_frontend() -> subprocess.Popen:
    """Start the Vite dev server."""
    print(f"\n  Step 3/4: Starting DevTools UI...")

    if not check_node_installed():
        print("  ⚠ Node.js not found. Serving built files instead.")
        print("  Install Node.js from https://nodejs.org for full dev experience.")
        return None

    if not check_npm_installed():
        print("  Installing npm dependencies (first run)...")
        subprocess.run(["npm", "install"], cwd=str(UI_DIR), capture_output=True)

    proc = subprocess.Popen(
        ["npm", "run", "dev"],
        cwd=str(UI_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    time.sleep(3)
    print(f"  Frontend: http://localhost:5173")
    return proc


def open_browser():
    """Open the DevTools UI in the default browser."""
    print(f"\n  Step 4/4: Opening browser...")
    time.sleep(1)
    webbrowser.open("http://localhost:5173")
    print(f"  Browser opened.")


def main():
    parser = argparse.ArgumentParser(
        description="AgentTrace — One-Click Demo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  agenttrace demo                 # Full demo with LLM misroute bug
  agenttrace demo --bug off       # Baseline: both runs correct
  agenttrace demo --port 8766     # Custom backend port
        """,
    )
    parser.add_argument("--bug", choices=["on", "off"], default="on",
                        help="Enable/disable the LLM misroute bug (default: on)")
    parser.add_argument("--port", type=int, default=8765,
                        help="Backend API port (default: 8765)")
    parser.add_argument("--no-browser", action="store_true",
                        help="Don't auto-open browser")

    args = parser.parse_args()
    bug_enabled = args.bug == "on"

    print()
    print("╔" + "═" * 53 + "╗")
    print("║  🧠  AgentTrace — Agent Debugging DevTools          ║")
    if bug_enabled:
        print("║  Bug: ON  — LLM misroute will be demonstrated       ║")
    else:
        print("║  Bug: OFF — Baseline comparison (both runs correct) ║")
    print("╚" + "═" * 53 + "╝")

    # 1. Generate trace
    try:
        generate_trace(bug_enabled)
    except Exception as e:
        print(f"\n  ❌ Trace generation failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # 2. Start backend
    try:
        backend_proc = start_backend(args.port, bug_enabled)
    except Exception as e:
        print(f"\n  ❌ Backend failed: {e}")
        # Continue without backend — frontend has fallback demo data
        backend_proc = None

    # 3. Start frontend
    try:
        frontend_proc = start_frontend()
    except Exception as e:
        print(f"\n  ❌ Frontend failed: {e}")
        frontend_proc = None

    # 4. Open browser
    if not args.no_browser:
        try:
            open_browser()
        except Exception:
            print("  Could not open browser. Open http://localhost:5173 manually.")

    print()
    print("  ╔" + "═" * 53 + "╗")
    print("  ║  ✅ AgentTrace DevTools is running!              ║")
    print("  ║                                                   ║")
    print("  ║  UI:  http://localhost:5173                        ║")
    print(f"  ║  API: http://127.0.0.1:{args.port}/api/trace/demo  ║")
    print("  ║                                                   ║")
    print("  ║  Press Ctrl+C to stop all services                ║")
    print("  ╚" + "═" + 53 + "╝")
    print()

    # Wait for Ctrl+C
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
        # Keep alive
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown(None, None)


if __name__ == "__main__":
    main()
