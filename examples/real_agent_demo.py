"""
Real Agent Demo: Function-calling agent with full observability pipeline.

Complete flow: Agent → TraceCapture → TraceCompiler → TraceExporter → TraceViewer

Usage:
    python examples/real_agent_demo.py
"""
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent_obs.execution_graph import TraceCapture, TraceCompiler, AgentIR, ExogenousModel
from agent_obs.trace_export import TraceExporter
from agent_obs.trace_viewer import TraceViewer


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
# Simple Agent (single decision)
# ============================================================

def run_simple_agent(query: str, capture: TraceCapture) -> str:
    """Run a simple agent that makes one tool call and branches on the result."""
    q = query.lower()

    # Step 1: LLM thinks
    capture.record_llm(prompt=query, output="Let me handle this...")
    time.sleep(0.002)

    # Step 2: Decide which tool to call
    if "math" in q or "calculate" in q or "2+2" in q:
        tool_name = "calculator"
        tool_args = {"expr": "2+2"}
    elif "weather" in q:
        tool_name = "weather"
        tool_args = {"city": "paris"}
    else:
        tool_name = "search"
        tool_args = {"query": query}

    # Step 3: Call the tool
    tools = {"calculator": tool_calculator, "weather": tool_weather, "search": tool_search}
    tool_result = tools[tool_name](**tool_args)
    capture.record_tool(name=tool_name, args=tool_args, result=tool_result)
    time.sleep(0.005)

    # Step 4: Branch — is the result good enough?
    is_good = tool_result and "Error" not in tool_result and "No " not in tool_result
    capture.record_branch(
        condition="result_sufficient",
        value=is_good,
        true_step="output_final",
        false_step="tool_fallback",
        merge_step="merge_final",
    )

    # Step 5: Handle branch paths
    if is_good:
        # True path: output directly (no extra steps)
        pass
    else:
        # False path: try fallback search
        fb_result = tool_search(query)
        capture.record_tool(name="search", args={"query": query}, result=fb_result,
                           status="success" if "No " not in fb_result else "error",
                           error=fb_result if "No " in fb_result else None,
                           step_id="tool_fallback")
        tool_result = fb_result

    # Step 6: Merge
    capture.record_merge(step_id="merge_final")

    # Step 7: Output
    capture.record_output(var="final_answer", value=tool_result, step_id="output_final")

    return str(tool_result)


# ============================================================
# Multi-Step Agent (two branches)
# ============================================================

def run_multistep_agent(capture: TraceCapture) -> str:
    """Agent with nested decision: weather check → branch → population check."""
    # Step 1: LLM
    capture.record_llm(prompt="Weather and population of Paris",
                       output="Multi-step query: need weather AND population")
    time.sleep(0.003)

    # Step 2: Check weather
    w_result = tool_weather("paris")
    capture.record_tool(name="weather", args={"city": "paris"}, result=w_result)
    time.sleep(0.005)

    # Step 3: Branch — is weather severe?
    is_severe = "rain" in w_result.lower() or "storm" in w_result.lower()
    capture.record_branch(
        condition="weather_severe",
        value=is_severe,
        true_step="tool_alert",
        false_step="tool_population",
        merge_step="merge_main",
    )

    if is_severe:
        # True path: send alert
        capture.record_tool(name="search", args={"query": "emergency alert"},
                           result="ALERT: Severe weather warning issued",
                           step_id="tool_alert")
    else:
        # False path: get population info
        p_result = tool_search("paris population")
        capture.record_tool(name="search", args={"query": "paris population"},
                           result=p_result, step_id="tool_population")

    # Step 4: Merge
    capture.record_merge(step_id="merge_main")

    # Step 5: Output
    full_answer = f"{w_result}. Population: ~2.1M"
    capture.record_output(var="final_answer", value=full_answer, step_id="output_final")

    return full_answer


# ============================================================
# The Full Pipeline
# ============================================================

def run_pipeline(label: str, agent_fn, *args):
    """Run the complete observability pipeline and display results."""
    print("\n" + "=" * 70)
    print(f"  {label}")
    print("=" * 70)

    # ---- 1. Run Agent with TraceCapture ----
    capture = TraceCapture()
    result = agent_fn(*args, capture)
    print(f"\n  Result: {result[:80]}")

    # ---- 2. Compile Trace → ExecutionGraph ----
    compiler = TraceCompiler()
    graph = compiler.compile(capture.get_trace())
    print(f"  Graph: {len(graph.nodes)} nodes, {len(compiler.branches)} branches")

    # ---- 3. Causal Analysis ----
    if compiler.branches:
        exog = ExogenousModel()
        ir = AgentIR(graph, exogenous=exog)
        for bid, branch in compiler.branches.items():
            why = ir.why(bid)
            if "error" not in why:
                print(f"  Causal: {bid} → selected={why.get('selected_tool')}, cond={why.get('condition_var')}={why.get('condition_value')}")

    # ---- 4. Export Trace JSON ----
    exporter = TraceExporter(
        graph=graph,
        branches=compiler.branches,
        step_to_node=compiler.step_to_node,
        steps=capture.steps,
    )
    trace_export = exporter.export()
    print(f"  Export: {len(trace_export.runs)} runs, {trace_export.total_latency_ms:.1f}ms total")

    # ---- 5. ASCII Tree View ----
    print(f"\n  Trace Tree:")
    viewer = TraceViewer(trace_export)
    viewer.print("tree")

    # ---- 6. JSON Summary (first 500 chars) ----
    json_str = trace_export.to_json()
    print(f"\n  JSON (first 500 chars):")
    print(f"  {json_str[:500]}...")

    return trace_export


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    print("=" * 70)
    print("  Agent Observability Pipeline")
    print("  Agent -> Trace -> Compiler -> Export -> Viewer")
    print("=" * 70)

    # Demo 1: Simple calculator agent
    run_pipeline("Demo 1: Calculator Agent (Single Branch)",
                 run_simple_agent, "calculate: 2+2")

    # Demo 2: Weather agent
    run_pipeline("Demo 2: Weather Agent (Single Branch)",
                 run_simple_agent, "what is the weather in paris")

    # Demo 3: Multi-step agent with explicit branch paths
    run_pipeline("Demo 3: Multi-Step Agent (Two Branches)",
                 run_multistep_agent)

    print("\n" + "=" * 70)
    print("  All demos complete.")
    print("=" * 70)
