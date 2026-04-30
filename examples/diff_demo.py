"""
Trace Diff Demo: Contrast two agent runs and pinpoint the decision that caused divergence.

Usage:
    python examples/diff_demo.py

This demonstrates the killer feature:
    Not "what happened" — that's LangSmith.
    But "WHY did this run differ from that one?" — that's AgentTrace.
"""
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent_obs.execution_graph import TraceCapture, TraceCompiler
from agent_obs.trace_export import TraceExporter
from agent_obs.trace_viewer import TraceViewer
from agent_obs.trace_diff import TraceDiffer, render_diff


# ============================================================
# Tools (same as real_agent_demo)
# ============================================================

def tool_calculator(expr: str) -> str:
    try:
        return str(eval(expr, {"__builtins__": {}}, {}))
    except Exception as e:
        return f"Error: {e}"

def tool_weather(city: str) -> str:
    db = {"paris": "Paris: 18C, cloudy", "tokyo": "Tokyo: 22C, sunny", "london": "London: 12C, rainy"}
    return db.get(city.lower(), f"No data for {city}")

def tool_search(query: str) -> str:
    kb = {
        "paris": "Paris: capital of France, population ~2.1M.",
        "tokyo": "Tokyo: capital of Japan, population ~14M.",
        "python": "Python: programming language, created 1991.",
    }
    for key, val in kb.items():
        if key in query.lower():
            return val
    return f"No info for: {query}"


# ============================================================
# Agent (same structure as real_agent_demo)
# ============================================================

def run_query_agent(query: str, capture: TraceCapture) -> str:
    """Run the agent: think → call tool → branch on result → maybe fallback → merge → output."""
    q = query.lower()

    capture.record_llm(prompt=query, output="Let me handle this...")
    time.sleep(0.002)

    # Decide which tool
    if "math" in q or "calculate" in q or "2+2" in q:
        tool_name = "calculator"
        tool_args = {"expr": "2+2"}
    elif "weather" in q:
        tool_name = "weather"
        # Extract city from query
        city = "paris"
        for c in ["paris", "tokyo", "london", "mars", "moon"]:
            if c in q:
                city = c
                break
        tool_args = {"city": city}
    else:
        tool_name = "search"
        tool_args = {"query": query}

    # Call tool
    tools = {"calculator": tool_calculator, "weather": tool_weather, "search": tool_search}
    tool_result = tools[tool_name](**tool_args)
    capture.record_tool(name=tool_name, args=tool_args, result=tool_result)
    time.sleep(0.005)

    # Branch
    is_good = tool_result and "Error" not in tool_result and "No " not in tool_result
    capture.record_branch(
        condition="result_sufficient",
        value=is_good,
        true_step="output_final",
        false_step="tool_fallback",
        merge_step="merge_final",
    )

    if not is_good:
        fb_result = tool_search(query)
        capture.record_tool(name="search", args={"query": query}, result=fb_result,
                           status="success" if "No " not in fb_result else "error",
                           error=fb_result if "No " in fb_result else None,
                           step_id="tool_fallback")
        tool_result = fb_result

    capture.record_merge(step_id="merge_final")
    capture.record_output(var="final_answer", value=tool_result, step_id="output_final")

    return str(tool_result)


# ============================================================
# Pipeline: run agent → compile → export
# ============================================================

def run_and_export(label: str, query: str):
    """Run one agent session and produce a TraceExport."""
    capture = TraceCapture()
    result = run_query_agent(query, capture)

    compiler = TraceCompiler()
    graph = compiler.compile(capture.get_trace())

    exporter = TraceExporter(
        graph=graph,
        branches=compiler.branches,
        step_to_node=compiler.step_to_node,
        steps=capture.steps,
    )
    export = exporter.export()

    print(f"  [{label}] query='{query}' → result='{result[:60]}'")
    return export


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  AgentTrace — Semantic Trace Diff")
    print("  \"Why did this run differ from that one?\"")
    print("=" * 60)

    # ── Run A: Valid city → tool succeeds → true path → direct output ──
    print("\n[1] Running two agents...")
    export_a = run_and_export("Run A", "weather in paris")

    # ── Run B: Unknown city → tool fails → false path → fallback search ──
    export_b = run_and_export("Run B", "weather in mars")

    # ── Diff ──
    differ = TraceDiffer(export_a, export_b)
    diff_result = differ.diff()

    # ── Render ──
    print(render_diff(diff_result))

    # ── Also show individual trace trees (optional, for context) ──
    show_trees = "--trees" in sys.argv
    if show_trees:
        print("\n  Run A Tree:")
        TraceViewer(export_a).print("tree")
        print("\n  Run B Tree:")
        TraceViewer(export_b).print("tree")

    # ── JSON output ──
    if "--json" in sys.argv:
        print("\n  JSON:")
        print(diff_result.to_json())
