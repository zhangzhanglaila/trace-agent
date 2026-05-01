"""
3 Killer Debug Cases for AgentTrace — interview-ready demonstrations.

Each case runs two agent traces and produces a causal verdict showing
WHY the agent behaved differently, not just what happened.

Usage:
    python examples/demo_cases.py           # Run all 3 cases
    python examples/demo_cases.py case1     # Run specific case
    python examples/demo_cases.py case2
    python examples/demo_cases.py case3
"""
import sys, os, json, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent_obs.trace_core import TracedAgent, explain_diff
from agent_obs.trace_export import TraceExport
from agent_obs.trace_diff import TraceDiffer, render_causal_verdict

# Import the buggy agent (we'll configure failure modes per case)
from examples.buggy_agent import BuggyAgent, LLM_MISROUTE_RATE, MEMORY_STALE_RATE, SUMMARIZE_FAIL_RATE


def run_case(title: str, subtitle: str, input_a: str, input_b: str,
             misroute_a: float = None, misroute_b: float = None,
             stale_a: float = None, stale_b: float = None,
             summar_fail_a: float = None, summar_fail_b: float = None,
             misroute_steps_a: set = None, misroute_steps_b: set = None,
             misroute_to_a: str = None, misroute_to_b: str = None,
             seed_a: int = None, seed_b: int = None):
    """Run a debug case with controlled failure rates."""
    H = "=" * 58
    print(f"  {H}")
    print(f"  CASE: {title}")
    print(f"  {subtitle}")
    print(f"  {H}")
    print()

    # ── Run A ──
    _set_rates(misroute_a, stale_a, summar_fail_a)
    agent_a = BuggyAgent(seed=seed_a, misroute_on_steps=misroute_steps_a,
                         misroute_to=misroute_to_a)
    traced_a = TracedAgent(agent_a, out_dir=".")
    result_a = traced_a.run(input_a)
    trace_a = traced_a.last_trace_path

    print(f"  [Run A] {input_a}")
    print(f"    Result: {str(result_a)[:100]}")
    print()

    # ── Run B ──
    _set_rates(misroute_b, stale_b, summar_fail_b)
    agent_b = BuggyAgent(seed=seed_b, misroute_on_steps=misroute_steps_b,
                         misroute_to=misroute_to_b)
    traced_b = TracedAgent(agent_b, out_dir=".")
    result_b = traced_b.run(input_b)
    trace_b = traced_b.last_trace_path

    print(f"  [Run B] {input_b}")
    print(f"    Result: {str(result_b)[:100]}")
    print()

    # ── Diff + Verdict ──
    export_a = TraceExport.from_file(trace_a)
    export_b = TraceExport.from_file(trace_b)
    differ = TraceDiffer(export_a, export_b)
    diff_result = differ.diff()

    if traced_a.last_ctx and traced_b.last_ctx:
        diff_result.causal_narrative = explain_diff(traced_a.last_ctx, traced_b.last_ctx)

    print(render_causal_verdict(diff_result))

    # Cleanup
    for t in [trace_a, trace_b]:
        try:
            os.remove(t)
        except OSError:
            pass

    return diff_result


def _set_rates(misroute, stale, summar_fail):
    """Temporarily override module-level failure rates."""
    import examples.buggy_agent as ba
    if misroute is not None:
        ba.LLM_MISROUTE_RATE = misroute
    if stale is not None:
        ba.MEMORY_STALE_RATE = stale
    if summar_fail is not None:
        ba.SUMMARIZE_FAIL_RATE = summar_fail


# ============================================================
# Case 1: LLM Misroute → Cascade Failure
# ============================================================

def case1():
    """
    Tokyo gets great hiking advice. Paris gets an error.

    Root cause: LLM router picked `summarize` instead of `activity_search`
    in the Paris run. The wrong tool got incompatible arguments, failed,
    and triggered a cascade of error-retry cycles.
    """
    run_case(
        title="LLM Misroute Cascade",
        subtitle='"Why does Tokyo work but Paris fails?"',
        input_a="Trip to Tokyo for hiking",
        input_b="Trip to Paris for hiking",
        # Tokyo: perfect execution
        misroute_a=0.0, summar_fail_a=0.0, seed_a=100,
        # Paris: misroute activity_search → summarize, then retry also misroutes → cascade
        misroute_b=0.0, summar_fail_b=1.0, seed_b=200,
        misroute_steps_b={1, 2}, misroute_to_b="summarize",
    )


# ============================================================
# Case 2: Error-Retry Loop
# ============================================================

def case2():
    """
    Sydney gets perfect surfing advice. Mars triggers an error-retry loop.

    Root cause: Mars has no weather data. The error triggers a retry,
    but the deterministic planner keeps picking weather_current (the default),
    which keeps failing. The agent burns its step budget on a tool that
    can never succeed for this input.
    """
    run_case(
        title="Error-Retry Death Spiral",
        subtitle='"Why does the agent get stuck on unknown cities?"',
        input_a="Trip to Sydney for surfing",
        input_b="Trip to Mars for hiking",
        # Sydney: perfect execution
        misroute_a=0.0, summar_fail_a=0.0, seed_a=300,
        # Mars: weather error triggers natural retry loop (no LLM misroute needed)
        misroute_b=0.0, summar_fail_b=0.0, seed_b=400,
    )


# ============================================================
# Case 3: Tool Ambiguity — forecast vs current
# ============================================================

def case3():
    """
    Same city, same activity — but different tool selection gives different advice.

    Root cause: The query "forecast" triggered `weather_forecast` in Run A
    (predicting "rain likely") but "weather" triggered `weather_current` in Run B
    (showing "rainy" now). Different tools → different conditions → different advice.
    """
    run_case(
        title="Tool Ambiguity",
        subtitle='"Why did forecast and current weather give different advice?"',
        input_a="What's the forecast for London? I want to go cycling",
        input_b="What's the weather in London? I want to go cycling",
        # No LLM misroute — the difference is PURELY which weather tool was selected
        misroute_a=0.0, misroute_b=0.0,
        summar_fail_a=0.0, summar_fail_b=0.0,
        seed_a=500, seed_b=600,
    )


# ============================================================
# Main
# ============================================================

CASES = {
    "case1": case1,
    "case2": case2,
    "case3": case3,
}


def main():
    if len(sys.argv) > 1:
        case_name = sys.argv[1]
        if case_name in CASES:
            CASES[case_name]()
        else:
            print(f"Unknown case: {case_name}. Available: {list(CASES.keys())}")
            return 1
    else:
        for name, fn in CASES.items():
            fn()
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
