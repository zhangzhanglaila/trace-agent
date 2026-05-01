"""
AgentTrace zero-invasion entry point.

Usage:
    # Option 1: enable() -- auto-trace, zero code changes
    from agent_obs import enable
    enable()

    # Option 2: enable(ui=True) -- auto-trace + auto-launch UI
    from agent_obs import enable
    enable(ui=True)
    # Now just run your agent -- the UI opens automatically

    # Option 3: enable(auto_attach=True) -- Chrome DevTools-style attach
    from agent_obs import enable
    enable(auto_attach=True)
    # Open http://127.0.0.1:8765 -- your agent appears as "Connected"

    # Option 4: dev() -- run twice, diff, open UI (Python API)
    from agent_obs import dev
    dev(my_agent, "Tokyo", "Paris")

    # Option 5: AGENTTRACE=1 env var
    #   $ AGENTTRACE=1 python my_agent.py
"""

import os
import sys
import json
import time
import signal
import atexit
import subprocess
import webbrowser
import threading
from pathlib import Path
from typing import Any, Optional

from .instrument.auto import auto_trace

_enabled = False
_server_started = False
_server_port = 8765
_ui_dir: Optional[Path] = None
_attached_agent_name: Optional[str] = None


def _status_file_path() -> Optional[Path]:
    """Path to the agent status file read by the UI server."""
    ui = _find_ui_dir()
    if not ui:
        return None
    status_dir = ui / "public"
    status_dir.mkdir(parents=True, exist_ok=True)
    return status_dir / "agent_status.json"


def _write_agent_status(status: str, agent_name: str = "", extra: dict = None):
    """Write agent status to the shared status file."""
    fp = _status_file_path()
    if not fp:
        return
    data = {
        "status": status,
        "agent_name": agent_name or _attached_agent_name or "Unknown",
        "pid": os.getpid(),
        "timestamp": time.time(),
    }
    if extra:
        data.update(extra)
    try:
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


def _clear_agent_status():
    """Remove the status file on agent exit."""
    fp = _status_file_path()
    if fp and fp.exists():
        try:
            fp.unlink()
        except OSError:
            pass


def enable(ui: bool = False, port: int = 8765, auto_attach: bool = False,
           agent_name: str = ""):
    """
    Enable AgentTrace auto-tracing. Add ONE line to your script.

        from agent_obs import enable
        enable(auto_attach=True)

    With auto_attach=True, the UI server detects your agent process and
    shows it as "Connected" — like Chrome DevTools for your agent.

    Args:
        ui: If True, start the debug UI server and open browser.
        port: Port for the UI server (default 8765).
        auto_attach: If True, register this process with the UI so it
                     appears as a connectable agent.
        agent_name: Human-readable name for the UI (default: class name).
    """
    global _enabled, _server_port, _attached_agent_name
    if _enabled:
        return
    _enabled = True
    _server_port = port
    _attached_agent_name = agent_name

    # Patch known frameworks (OpenAI, LangChain, etc.)
    auto_trace()

    # Set env for subprocess / nested awareness
    os.environ["AGENTTRACE_ENABLED"] = "1"
    os.environ["AGENTTRACE_PORT"] = str(port)

    if auto_attach:
        _write_agent_status("running", agent_name)
        atexit.register(_clear_agent_status)

    if ui or auto_attach:
        _launch_ui(port)


def dev(agent: Any,
        input_a: str,
        input_b: str,
        port: int = 8765,
        no_browser: bool = False) -> dict:
    """
    One-command debug: run agent twice, diff, open UI.

        from agent_obs import dev
        result = dev(my_agent, "Tokyo", "Paris")

    Returns the unified trace JSON dict.
    """
    from .trace_core import TracedAgent, explain_diff
    from .trace_export import TraceExport
    from .trace_diff import TraceDiffer
    from .frontend_adapter import adapt_diff_result

    global _ui_dir
    if _ui_dir is None:
        _ui_dir = _find_ui_dir()

    enable()

    print()
    print("=" * 55)
    print("  AgentTrace Dev - Live Debugger")
    print("=" * 55)
    print(f"  Agent: {agent.__class__.__name__}")

    # Run A
    traced_a = TracedAgent(agent)
    print(f"\n  [Run A] Input: {input_a[:80]}")
    result_a = traced_a.run(input_a)
    trace_a_path = traced_a.last_trace_path
    print(f"    => {str(result_a)[:100]}")

    # Run B
    traced_b = TracedAgent(agent, out_dir=os.path.dirname(trace_a_path) or ".")
    print(f"\n  [Run B] Input: {input_b[:80]}")
    result_b = traced_b.run(input_b)
    trace_b_path = traced_b.last_trace_path
    print(f"    => {str(result_b)[:100]}")

    # Diff
    print(f"\n  Diffing...")
    export_a = TraceExport.from_file(trace_a_path)
    export_b = TraceExport.from_file(trace_b_path)
    differ = TraceDiffer(export_a, export_b)
    diff_result = differ.diff()

    if traced_a.last_ctx and traced_b.last_ctx:
        diff_result.causal_narrative = explain_diff(traced_a.last_ctx, traced_b.last_ctx)

    ui_json = adapt_diff_result(diff_result, export_a, export_b)

    # Write to public/dev_trace.json
    if _ui_dir:
        dev_path = _ui_dir / "public" / "dev_trace.json"
        dev_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dev_path, "w", encoding="utf-8") as f:
            json.dump(ui_json, f, indent=2, ensure_ascii=False)

    # Cleanup raw traces
    for t in [trace_a_path, trace_b_path]:
        try:
            os.remove(t)
        except OSError:
            pass

    # Print verdict
    print(f"\n  [verdict] {ui_json['verdict'][:120]}")
    if ui_json.get("diagnosis"):
        d = ui_json["diagnosis"]
        print(f"  [diagnosis] {d['type']} ({d['confidence']})")

    # Launch UI
    if not no_browser:
        _launch_ui(port, blocking=True)

    return ui_json


# ── Internal: UI launcher ──

def _find_ui_dir() -> Optional[Path]:
    """Locate the agent-trace-ui directory."""
    candidates = [
        Path(__file__).parent.parent / "agent-trace-ui",
        Path.cwd() / "agent-trace-ui",
    ]
    for d in candidates:
        if d.exists():
            return d
    return None


def _launch_ui(port: int, blocking: bool = False):
    """
    Start the backend server + open browser.
    Uses built dist/ files -- no npm required.
    """
    global _server_started, _ui_dir

    if _ui_dir is None:
        _ui_dir = _find_ui_dir()

    if not _ui_dir:
        print("  [WARN] Could not find agent-trace-ui directory")
        return

    # Start backend server in background thread
    if not _server_started:
        _server_started = True
        t = threading.Thread(target=_run_server, args=(port,), daemon=True)
        t.start()
        time.sleep(0.5)  # Wait for server to bind

    # Open browser
    url = f"http://127.0.0.1:{port}"
    print(f"  UI: {url}")
    webbrowser.open(url)

    if blocking:
        print("  Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n  Shutting down.")


def _run_server(port: int):
    """Run the backend server (called from background thread)."""
    ui_dir = _find_ui_dir()
    if not ui_dir:
        return

    server_py = ui_dir / "server.py"
    if not server_py.exists():
        print(f"  [WARN] server.py not found at {server_py}")
        return

    # Run server in a subprocess (cleaner isolation)
    try:
        subprocess.run(
            [sys.executable, str(server_py), "--port", str(port)],
            cwd=str(ui_dir),
            capture_output=False,
        )
    except Exception as e:
        print(f"  [WARN] Server failed: {e}")


def _check_node() -> bool:
    try:
        subprocess.run(["node", "--version"], capture_output=True, timeout=5)
        return True
    except Exception:
        return False


# ── Auto-enable via AGENTTRACE=1 env var ──
if os.environ.get("AGENTTRACE_ENABLED") == "1":
    enable(ui=os.environ.get("AGENTTRACE_UI") == "1")
