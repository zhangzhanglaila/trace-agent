"""
Trace Diff Demo: Three contrasting cases that show the value of semantic diff.

Usage:
    python examples/diff_demo.py              # All 3 cases
    python examples/diff_demo.py --json       # + JSON output
    python examples/diff_demo.py --trees      # + individual trace trees

Three cases in one screen:
    Case 1: Same input -> same output (no diff)
    Case 2: Different city -> branch changes -> output diverges
    Case 3: Tool error -> error status propagates -> fallback fails

This is the product demo. One command, three stories.
"""
import sys
import os
import time
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent_obs.execution_graph import TraceCapture, TraceCompiler
from agent_obs.trace_export import TraceExporter
from agent_obs.trace_viewer import TraceViewer
from agent_obs.trace_diff import TraceDiffer, render_diff


# ============================================================
# Tools
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
# Agent
# ============================================================

def run_agent(query: str, capture: TraceCapture) -> str:
    """Run agent: think -> call tool -> branch on result -> maybe fallback -> merge -> output."""
    q = query.lower()

    capture.record_llm(prompt=query, output="Let me handle this...")
    time.sleep(0.002)

    # Decide which tool and extract args from query
    if "calculate" in q or re.search(r'[\d+\-*/]', q):
        tool_name = "calculator"
        # Extract expression
        expr_match = re.search(r'([\d\s+\-*/.()]+)$', query)
        expr = expr_match.group(1).strip() if expr_match else "2+2"
        tool_args = {"expr": expr}
    elif "weather" in q:
        tool_name = "weather"
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
    is_error = "Error" in tool_result
    capture.record_tool(
        name=tool_name, args=tool_args, result=tool_result,
        status="error" if is_error else "success",
        error=tool_result if is_error else None,
    )
    time.sleep(0.005)

    # Branch: is result sufficient?
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
        is_fb_error = "No " in fb_result or "Error" in fb_result
        capture.record_tool(
            name="search", args={"query": query}, result=fb_result,
            status="error" if is_fb_error else "success",
            error=fb_result if is_fb_error else None,
            step_id="tool_fallback",
        )
        tool_result = fb_result

    capture.record_merge(step_id="merge_final")
    is_final_error = "No " in str(tool_result) or "Error" in str(tool_result)
    capture.record_output(
        var="final_answer", value=tool_result, step_id="output_final",
        status="error" if is_final_error else "success",
    )

    return str(tool_result)


# ============================================================
# Pipeline
# ============================================================

def run_and_export(query: str):
    """Run one agent session -> compile -> export."""
    capture = TraceCapture()
    result = run_agent(query, capture)

    compiler = TraceCompiler()
    graph = compiler.compile(capture.get_trace())

    exporter = TraceExporter(
        graph=graph,
        branches=compiler.branches,
        step_to_node=compiler.step_to_node,
        steps=capture.steps,
    )
    return exporter.export(), result


def print_case_header(num: int, title: str, description: str):
    """Print a case header."""
    print()
    print("  " + "=" * 54)
    print(f"  CASE {num}: {title}")
    print(f"  {description}")
    print("  " + "=" * 54)


def run_case(num: int, title: str, description: str,
             query_a: str, query_b: str):
    """Run a single diff case: two agents, diff, render."""
    print_case_header(num, title, description)

    print(f"\n  [Run A] {query_a}")
    export_a, result_a = run_and_export(query_a)
    print(f"      -> {result_a[:70]}")

    print(f"  [Run B] {query_b}")
    export_b, result_b = run_and_export(query_b)
    print(f"      -> {result_b[:70]}")

    differ = TraceDiffer(export_a, export_b)
    diff_result = differ.diff()

    print(render_diff(diff_result))

    return diff_result


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    print("=" * 58)
    print("  AgentTrace - Semantic Trace Diff")
    print('  "Why did my agent behave differently?"')
    print("=" * 58)
    print()
    print("  Comparing agent runs to find the ROOT CAUSE of divergence.")
    print("  Not what happened - but WHY it happened.")

    results = []

    # ── Case 1: No difference ──
    results.append(run_case(
        num=1,
        title="No Difference",
        description="Same query, same path, same result.",
        query_a="weather in paris",
        query_b="weather in paris",
    ))

    # ── Case 2: Branch change ──
    results.append(run_case(
        num=2,
        title="Branch Change",
        description="Different city -> condition flips -> new path.",
        query_a="weather in paris",
        query_b="weather in mars",
    ))

    # ── Case 3: Error path ──
    results.append(run_case(
        num=3,
        title="Error Path",
        description="Tool returns error -> fallback also fails -> error propagates.",
        query_a="calculate: 2+2",
        query_b="calculate: 1/0",
    ))

    # ── Summary ──
    print()
    print("  " + "=" * 54)
    print("  ALL 3 CASES COMPLETE")
    print("  " + "=" * 54)
    print(f"  Case 1: {'No divergence' if not results[0].has_diverged else 'HAS DIVERGENCE'}")
    print(f"  Case 2: {'Diverged at: ' + results[1].first_divergence.id if results[1].first_divergence else 'No divergence'}")
    print(f"  Case 3: {'Diverged at: ' + results[2].first_divergence.id if results[2].first_divergence else 'No divergence'}")

    # ── Optionals ──
    if "--trees" in sys.argv:
        print("\n  TIP: re-run with --trees to see individual trace trees")

    if "--json" in sys.argv:
        print("\n  [JSON Export - Case 2]")
        print(results[1].to_json())
