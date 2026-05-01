"""
AgentTrace DevTools Server — API + static file serving for the Vue3 debug UI.

Usage:
    python server.py --port 8765                   # API only (needs separate frontend)
    python server.py --port 8765 --static          # Serve built frontend from dist/

Endpoints:
    GET  /api/trace/demo?bug=on|off     # Generate demo trace with bug toggle
    GET  /api/trace/dev                 # Serve pre-generated dev trace
    GET  /api/trace/list                # List available traces on disk
    POST /api/trace/what-if             # Generate counterfactual "fixed" run
    GET  /health
    GET  /                              # Served from dist/index.html (with --static)
"""

import sys
import os
import json
import time
import argparse
import glob as glob_mod
import mimetypes
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT.parent))

from agent_obs.frontend_adapter import generate_demo_json, adapt_diff_result
from agent_obs.trace_export import TraceExport
from agent_obs.trace_diff import TraceDiffer
from agent_obs.cli_main import _load_module, _find_agent, _parse_script_ref


# ── In-memory agent registry (replaces file-based agent_status.json) ──
# Supports multiple simultaneous agents. Agents register via HTTP POST.
# Stale entries (no heartbeat for 30s) are auto-cleaned.
_active_agents: dict = {}  # agent_id -> {agent_name, pid, timestamp, ...}
_agent_lock = __import__('threading').Lock()


def _cleanup_stale_agents(ttl: float = 30.0):
    """Remove agents that haven't sent a heartbeat within TTL."""
    now = time.time()
    with _agent_lock:
        stale = [aid for aid, d in _active_agents.items()
                 if now - d.get("timestamp", 0) > ttl]
        for aid in stale:
            del _active_agents[aid]


def build_trace(bug_enabled: bool = True) -> str:
    """Run the Travel Planner agent and return unified JSON."""
    examples_dir = str(ROOT.parent / "examples")
    if examples_dir not in sys.path:
        sys.path.insert(0, examples_dir)
    from examples.travel_planner import TravelPlanner
    from agent_obs.trace_core import TracedAgent, explain_diff

    import examples.travel_planner as tp
    tp.LLM_MISROUTE_ENABLED = bug_enabled

    # Run A: Tokyo (always correct)
    agent_a = TravelPlanner(enable_bug=False, max_steps=8)
    traced_a = TracedAgent(agent_a, out_dir=".")
    traced_a.run("Plan a trip to Tokyo for hiking")
    export_a = TraceExport.from_file(traced_a.last_trace_path)

    # Run B: Paris (bug if enabled)
    agent_b = TravelPlanner(enable_bug=bug_enabled, max_steps=5 if bug_enabled else 8)
    traced_b = TracedAgent(agent_b, out_dir=".")
    traced_b.run("Plan a trip to Paris for hiking")
    export_b = TraceExport.from_file(traced_b.last_trace_path)

    # Diff
    differ = TraceDiffer(export_a, export_b)
    diff_result = differ.diff()
    if traced_a.last_ctx and traced_b.last_ctx:
        diff_result.causal_narrative = explain_diff(traced_a.last_ctx, traced_b.last_ctx)

    result = adapt_diff_result(diff_result, export_a, export_b)
    result["meta"]["bug_enabled"] = bug_enabled

    # Cleanup
    for t in [traced_a.last_trace_path, traced_b.last_trace_path]:
        try:
            os.remove(t)
        except OSError:
            pass

    return json.dumps(result, indent=2, ensure_ascii=False)


def _resolve_agent_path(agent_path: str) -> str:
    """Resolve a user-provided agent path to an absolute script path."""
    project_root = str(ROOT.parent)
    if os.path.isabs(agent_path):
        return agent_path
    return os.path.join(project_root, agent_path)


def build_trace_custom(bug_enabled: bool = True, input_a: str = "", input_b: str = "",
                       agent_path: str = "") -> str:
    """Run an agent with custom inputs from the UI.

    If agent_path is provided (e.g. 'my_agent.py:Agent'), dynamically load
    and run that agent. Otherwise use the built-in TravelPlanner demo.
    """
    examples_dir = str(ROOT.parent / "examples")
    if examples_dir not in sys.path:
        sys.path.insert(0, examples_dir)
    project_root = str(ROOT.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from agent_obs.trace_core import TracedAgent, explain_diff

    if agent_path:
        # ── Dynamic: load user's own agent ──
        script_ref, obj_ref = _parse_script_ref(agent_path)
        abs_path = _resolve_agent_path(script_ref)
        if not os.path.exists(abs_path):
            raise FileNotFoundError(
                f"Agent script not found: {abs_path}. "
                f"Provide a path relative to the project root or an absolute path."
            )
        # Load twice for two independent instances (Run A and Run B)
        agent_a = _find_agent(_load_module(abs_path), obj_ref)
        agent_b = _find_agent(_load_module(abs_path), obj_ref)
    else:
        # ── Default: built-in TravelPlanner demo ──
        import examples.travel_planner as tp
        from examples.travel_planner import TravelPlanner
        tp.LLM_MISROUTE_ENABLED = bug_enabled
        agent_a = TravelPlanner(enable_bug=False, max_steps=8)
        agent_b = TravelPlanner(enable_bug=bug_enabled, max_steps=5 if bug_enabled else 8)

    traced_a = TracedAgent(agent_a, out_dir=".")
    traced_a.run(input_a)
    export_a = TraceExport.from_file(traced_a.last_trace_path)

    traced_b = TracedAgent(agent_b, out_dir=".")
    traced_b.run(input_b)
    export_b = TraceExport.from_file(traced_b.last_trace_path)

    differ = TraceDiffer(export_a, export_b)
    diff_result = differ.diff()
    if traced_a.last_ctx and traced_b.last_ctx:
        diff_result.causal_narrative = explain_diff(traced_a.last_ctx, traced_b.last_ctx)

    result = adapt_diff_result(diff_result, export_a, export_b)
    result["meta"]["bug_enabled"] = bug_enabled

    for t in [traced_a.last_trace_path, traced_b.last_trace_path]:
        try:
            os.remove(t)
        except OSError:
            pass

    return json.dumps(result, indent=2, ensure_ascii=False)


def build_what_if() -> str:
    """Generate a counterfactual Run C."""
    examples_dir = str(ROOT.parent / "examples")
    if examples_dir not in sys.path:
        sys.path.insert(0, examples_dir)
    from examples.travel_planner import TravelPlanner
    from agent_obs.trace_core import TracedAgent, explain_diff

    import examples.travel_planner as tp
    tp.LLM_MISROUTE_ENABLED = True

    agent_a = TravelPlanner(enable_bug=False, max_steps=8)
    traced_a = TracedAgent(agent_a, out_dir=".")
    traced_a.run("Plan a trip to Tokyo for hiking")
    export_a = TraceExport.from_file(traced_a.last_trace_path)

    agent_b = TravelPlanner(enable_bug=True, max_steps=5)
    traced_b = TracedAgent(agent_b, out_dir=".")
    traced_b.run("Plan a trip to Paris for hiking")
    export_b = TraceExport.from_file(traced_b.last_trace_path)

    tp.LLM_MISROUTE_ENABLED = False
    agent_c = TravelPlanner(enable_bug=False, max_steps=8)
    traced_c = TracedAgent(agent_c, out_dir=".")
    traced_c.run("Plan a trip to Paris for hiking")
    export_c = TraceExport.from_file(traced_c.last_trace_path)

    differ_ab = TraceDiffer(export_a, export_b)
    diff_ab = differ_ab.diff()
    if traced_a.last_ctx and traced_b.last_ctx:
        diff_ab.causal_narrative = explain_diff(traced_a.last_ctx, traced_b.last_ctx)

    result_ab = adapt_diff_result(diff_ab, export_a, export_b)

    result = {
        "verdict": result_ab["verdict"],
        "diagnosis": result_ab["diagnosis"],
        "root_cause": result_ab["root_cause"],
        "graph": result_ab["graph"],
        "diff": result_ab["diff"],
        "output": result_ab["output"],
        "fix_suggestion": result_ab["fix_suggestion"],
        "explanation": result_ab.get("explanation", ""),
        "meta": result_ab["meta"],
        "what_if": {
            "run_c_output": str(traced_c._agent.run("Plan a trip to Paris for hiking")),
            "run_c_trace": {
                "steps": len(export_c.runs),
                "trace_id": export_c.trace_id,
            },
            "run_b_output": str(traced_b._agent.run("Plan a trip to Paris for hiking")),
            "fix_description": (
                "If the LLM had selected `activity_search` instead of `summarize` "
                "at step 2, the agent would have produced a complete travel plan "
                "instead of failing with an incomplete plan error."
            ),
            "would_fix": diff_ab.output_diverged,
        },
    }

    for t in [traced_a.last_trace_path, traced_b.last_trace_path, traced_c.last_trace_path]:
        try:
            os.remove(t)
        except OSError:
            pass

    return json.dumps(result, indent=2, ensure_ascii=False)


# ── MIME types for static serving ──
MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}


class TraceHandler(BaseHTTPRequestHandler):
    serve_static = False
    static_dir = None

    def _send_json(self, data: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(data.encode("utf-8"))

    def _send_file(self, path: str):
        if not os.path.isfile(path):
            self._send_json(json.dumps({"error": "not found"}), 404)
            return
        ext = os.path.splitext(path)[1].lower()
        mime = MIME_TYPES.get(ext, "application/octet-stream")
        with open(path, "rb") as f:
            content = f.read()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", len(content))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)

    def _read_body(self) -> dict:
        content_len = int(self.headers.get("Content-Length", 0))
        if content_len == 0:
            return {}
        return json.loads(self.rfile.read(content_len))

    def _serve_static_file(self, path: str) -> bool:
        """Serve a static file from dist/. Returns True if file exists."""
        if not self.serve_static or not self.static_dir:
            return False
        clean_path = path.lstrip("/")
        file_path = os.path.join(self.static_dir, clean_path) if clean_path else os.path.join(self.static_dir, "index.html")
        if os.path.isfile(file_path):
            self._send_file(file_path)
            return True
        return False

    def _serve_spa_fallback(self) -> bool:
        """Serve index.html for SPA routing. Returns True if served."""
        if not self.serve_static or not self.static_dir:
            return False
        index_path = os.path.join(self.static_dir, "index.html")
        if os.path.isfile(index_path):
            self._send_file(index_path)
            return True
        return False

    def do_OPTIONS(self):
        self._send_json("{}")

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        # ── API routes (checked first) ──

        if path == "/api/trace/demo":
            bug = params.get("bug", ["on"])[0]
            bug_enabled = bug.lower() != "off"
            try:
                self._send_json(build_trace(bug_enabled))
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._send_json(json.dumps({"error": str(e)}), 500)

        elif path == "/api/trace/dev":
            try:
                dev_file = os.path.join(os.path.dirname(__file__), "public", "dev_trace.json")
                if os.path.exists(dev_file):
                    with open(dev_file, "r", encoding="utf-8") as f:
                        self._send_json(f.read())
                else:
                    self._send_json(json.dumps({"error": "no dev trace found"}), 404)
            except Exception as e:
                self._send_json(json.dumps({"error": str(e)}), 500)

        elif path == "/api/trace/list":
            try:
                traces = _list_traces()
                self._send_json(json.dumps({"traces": traces}))
            except Exception as e:
                self._send_json(json.dumps({"error": str(e)}), 500)

        elif path == "/api/trace/agents":
            try:
                extra = params.get("dir", [None])[0]
                agents = _scan_agents(extra_dir=extra)
                self._send_json(json.dumps({"agents": agents}))
            except Exception as e:
                self._send_json(json.dumps({"error": str(e)}), 500)

        elif path == "/api/trace/agents/active":
            try:
                _cleanup_stale_agents()
                with _agent_lock:
                    agents_list = [
                        {"agent_id": aid, **{k: v for k, v in d.items()}}
                        for aid, d in _active_agents.items()
                    ]
                self._send_json(json.dumps({"agents": agents_list}))
            except Exception as e:
                self._send_json(json.dumps({"error": str(e)}), 500)

        elif path == "/health":
            self._send_json(json.dumps({"status": "ok"}))

        # ── Static file serving (tried after API routes) ──
        elif self._serve_static_file(path):
            return

        # ── SPA fallback (for Vue Router paths like /debug) ──
        elif self._serve_spa_fallback():
            return

        else:
            self._send_json(json.dumps({"error": "not found"}), 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/trace/agents/register":
            body = self._read_body()
            agent_id = body.get("agent_id", f"agent_{body.get('pid', 'unknown')}")
            agent_name = body.get("agent_name", "Unknown")
            pid = body.get("pid", 0)
            with _agent_lock:
                _active_agents[agent_id] = {
                    "agent_name": agent_name,
                    "pid": pid,
                    "timestamp": time.time(),
                    "status": "running",
                }
            self._send_json(json.dumps({"ok": True, "agent_id": agent_id}))

        elif path == "/api/trace/agents/unregister":
            body = self._read_body()
            agent_id = body.get("agent_id", "")
            with _agent_lock:
                _active_agents.pop(agent_id, None)
            self._send_json(json.dumps({"ok": True}))

        elif path == "/api/trace/what-if":
            try:
                self._send_json(build_what_if())
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._send_json(json.dumps({"error": str(e)}), 500)

        elif path == "/api/trace/run":
            body = self._read_body()
            bug = body.get("bug", True)
            input_a = body.get("input_a", "Plan a trip to Tokyo for hiking")
            input_b = body.get("input_b", "Plan a trip to Paris for hiking")
            agent_path = body.get("agent_path", "")
            try:
                self._send_json(build_trace_custom(
                    bug_enabled=bug,
                    input_a=input_a,
                    input_b=input_b,
                    agent_path=agent_path,
                ))
            except FileNotFoundError as e:
                self._send_json(json.dumps({"error": str(e)}), 404)
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._send_json(json.dumps({"error": str(e)}), 500)

        else:
            self._send_json(json.dumps({"error": "not found"}), 404)

    def log_message(self, format, *args):
        print(f"[server] {args[0]}")


def _list_traces() -> list:
    """List available trace files on disk."""
    traces = []
    # Check for dev trace
    dev_file = os.path.join(os.path.dirname(__file__), "public", "dev_trace.json")
    if os.path.exists(dev_file):
        try:
            mtime = os.path.getmtime(dev_file)
            traces.append({
                "id": "dev",
                "name": "Dev Trace",
                "path": "dev",
                "mtime": mtime,
            })
        except OSError:
            pass
    # Check current directory for trace files
    for f in glob_mod.glob("trace_*.json"):
        try:
            mtime = os.path.getmtime(f)
            traces.append({
                "id": os.path.basename(f).replace(".json", ""),
                "name": os.path.basename(f),
                "path": os.path.abspath(f),
                "mtime": mtime,
            })
        except OSError:
            pass
    traces.sort(key=lambda t: t.get("mtime", 0), reverse=True)
    return traces


# Extra directories to scan for agents (set via CLI --project-dir)
_extra_scan_dirs: list = []


def _collect_scan_dirs(extra_dir: str = None) -> list:
    """Collect all directories to scan for agent discovery.

    Priority order:
      1. AGENTTRACE_PROJECT_DIR env var
      2. CLI --project-dir args
      3. Current working directory
      4. AgentTrace project root (for built-in examples)
      5. extra_dir (from ?dir= query param or explicit argument)
    """
    dirs = []
    env_dir = os.environ.get("AGENTTRACE_PROJECT_DIR")
    if env_dir and os.path.isdir(env_dir):
        dirs.append(os.path.abspath(env_dir))
    for d in _extra_scan_dirs:
        d = os.path.abspath(d)
        if os.path.isdir(d) and d not in dirs:
            dirs.append(d)
    cwd = os.getcwd()
    if cwd not in dirs:
        dirs.append(cwd)
    project_root = str(ROOT.parent)
    if project_root not in dirs:
        dirs.append(project_root)
    if extra_dir and os.path.isdir(extra_dir):
        extra_dir = os.path.abspath(extra_dir)
        if extra_dir not in dirs:
            dirs.append(extra_dir)
    return [d for d in dirs if os.path.isdir(d)]


def _scan_agents(scan_dirs=None, extra_dir=None) -> list:
    """Scan directories for Python files that look like agent scripts.

    Args:
        scan_dirs: List of directories to scan. If None, auto-discovers via
                   _collect_scan_dirs().
        extra_dir: Additional directory to append to the scan list.

    Returns a list of {id, path, name, entry} candidates.
    """
    import re
    if scan_dirs is None:
        scan_dirs = _collect_scan_dirs(extra_dir)
    elif isinstance(scan_dirs, str):
        scan_dirs = [scan_dirs]
    if extra_dir and os.path.isdir(extra_dir):
        extra_dir = os.path.abspath(extra_dir)
        if extra_dir not in scan_dirs:
            scan_dirs = list(scan_dirs) + [extra_dir]

    candidates = []
    for scan_dir in scan_dirs:
        if not os.path.isdir(scan_dir):
            continue
        for root, dirs, files in os.walk(scan_dir):
            # Skip hidden, venv, node_modules, __pycache__, .git
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in
                        ("venv", "node_modules", "__pycache__", "dist", ".git")]
            for f in files:
                if not f.endswith(".py") or f.startswith("_"):
                    continue
                fpath = os.path.join(root, f)
                try:
                    with open(fpath, "r", encoding="utf-8") as fh:
                        content = fh.read()
                except (OSError, UnicodeDecodeError):
                    continue
                rel = os.path.relpath(fpath, scan_dir).replace("\\", "/")
                # Look for agent-like patterns
                has_agent_class = bool(re.search(r'class\s+(\w*[Aa]gent\w*)', content))
                has_agent_var = bool(re.search(r'^\s*agent\s*=\s*', content, re.MULTILINE))
                if not (has_agent_class or has_agent_var):
                    continue
                # Determine entry reference
                entry_candidates = []
                if has_agent_var:
                    entry_candidates.append(f"{rel}:agent")
                for m in re.finditer(r'class\s+(\w*[Aa]gent\w*)', content):
                    cname = m.group(1)
                    entry_candidates.append(f"{rel}:{cname}")
                for entry in entry_candidates:
                    agent_id = entry.rsplit(":", 1)[-1] if ":" in entry else entry
                    candidates.append({
                        "id": agent_id,
                        "path": rel,
                        "name": f,
                        "entry": entry,
                    })
    # Deduplicate by entry
    seen = set()
    unique = []
    for c in candidates:
        if c["entry"] not in seen:
            seen.add(c["entry"])
            unique.append(c)
    return unique


def start_server(port: int = 8765, static: bool = True):
    """Start the HTTP server. Non-blocking — call from background thread."""
    handler = TraceHandler
    handler.serve_static = static
    handler.static_dir = str(ROOT / "dist") if static else None

    if static and not os.path.isdir(handler.static_dir):
        print(f"[server] No dist/ found at {handler.static_dir} — static serving disabled")
        handler.serve_static = False

    server = HTTPServer(("127.0.0.1", port), handler)
    print(f"[server] AgentTrace DevTools started")
    if handler.serve_static:
        print(f"[server]   UI: http://127.0.0.1:{port}")
    print(f"[server]   API: http://127.0.0.1:{port}/api/trace/demo")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[server] Shutting down.")


def main():
    parser = argparse.ArgumentParser(description="AgentTrace DevTools Server")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--static", action="store_true",
                        help="Serve built frontend from dist/ directory")
    parser.add_argument("--no-static", action="store_true",
                        help="Disable static file serving")
    parser.add_argument("--project-dir", action="append", default=[],
                        help="Additional project directory to scan for agents (repeatable)")
    args = parser.parse_args()

    global _extra_scan_dirs
    _extra_scan_dirs = args.project_dir

    serve_static = args.static or not args.no_static

    TraceHandler.serve_static = serve_static
    TraceHandler.static_dir = str(ROOT / "dist") if serve_static else None

    if serve_static and not os.path.isdir(TraceHandler.static_dir):
        print(f"[server] No dist/ at {TraceHandler.static_dir} — static serving disabled")
        TraceHandler.serve_static = False

    server = HTTPServer(("127.0.0.1", args.port), TraceHandler)
    print(f"AgentTrace DevTools Server")
    if TraceHandler.serve_static:
        print(f"  UI:  http://127.0.0.1:{args.port}")
    print(f"  API: http://127.0.0.1:{args.port}/api/trace/demo")
    print(f"Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")


if __name__ == "__main__":
    main()
