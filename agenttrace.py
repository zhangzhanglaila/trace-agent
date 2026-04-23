#!/usr/bin/env python3
"""
AgentTrace CLI - Causal Semantic IR Engine

Usage:
    agenttrace explain <case.json>    Explain a medical triage case
    agenttrace run <case.json>        Run agent with tracing
    agenttrace fork <case.json>       Fork and replay with modifications
"""
import sys
import json
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from agent_obs.execution_graph import ExecutionGraph, ExecutionEngine, VMContext


def load_case(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def explain_case(case: dict) -> str:
    """Generate causal explanation for a medical triage case."""
    query = case.get("query", case.get("patient", "unknown"))
    expected = case.get("expected", {})
    interventions = case.get("interventions", [])

    lines = []
    lines.append("=" * 60)
    lines.append("AGENTTRACE CAUSAL EXPLANATION")
    lines.append("=" * 60)
    lines.append(f"\nQuery: {query}")
    lines.append(f"\nExpected: {expected.get('severity', 'NORMAL')}")

    if interventions:
        lines.append("\n--- INTERVENTIONS ---")
        for i, iv in enumerate(interventions):
            lines.append(f"  {i+1}. [{iv.get('type', 'modify')}] {iv.get('field', 'unknown')}: {iv.get('from', '?')} → {iv.get('to', '?')}")

    return "\n".join(lines)


def run_medical_triage(query: str) -> ExecutionGraph:
    """Build and execute medical triage graph."""
    g = ExecutionGraph()
    g.instr("n1", "MOV", ["R_query", query], ["n2"])
    g.instr("n2", "CALL", ["tool", "diagnose", "@R_query", "R_result"], ["n3"])
    g.instr("n3", "EQ", ["@R_result", "CASE_CRITICAL", "R_flag"], ["n4"])
    g.instr("n4", "BRANCH", ["R_flag"], ["n5b", "n5a"])
    g.instr("n5a", "MOV", ["R_out", "REST AND FLUIDS"], ["n6"])
    g.instr("n5b", "MOV", ["R_out", "EMERGENCY PROTOCOL: CALL 911"], ["n6"])
    g.instr("n6", "HALT", [], [])
    g.set_root("n1")
    g.build_cfg()

    return g


def cmd_explain(args):
    """Explain a case file."""
    case = load_case(args.case)

    print(explain_case(case))

    # Build and execute graph
    query = case.get("query", case.get("patient", ""))
    g = run_medical_triage(query)

    engine = ExecutionEngine(g.semantic)
    ctx = VMContext()
    ctx = g.run(engine, ctx)

    print(f"\n--- EXECUTION RESULT ---")
    print(f"R_result = {ctx.regs.get('R_result')}")
    print(f"R_flag   = {ctx.regs.get('R_flag')}")
    print(f"R_out    = {ctx.regs.get('R_out')}")

    # Semantic query
    print(f"\n--- SEMANTIC ANALYSIS ---")
    prov = g.semantic.resolve("R_out", "n6")
    print(f"R_out @ n6: {prov.semantic.kind.value} = {prov.semantic}")
    print(f"  Definition site: {prov.definition_site}")
    print(f"  Reasoning: {prov.reasoning_trace[:2] if prov.reasoning_trace else 'N/A'}")

    # Causal explanation
    print(f"\n--- CAUSAL NARRATIVE ---")
    caus = g.semantic.explain("n1", "n6")
    print(f"Path: {' → '.join(caus.path)}")
    for i, (node, cond) in enumerate(zip(caus.path[::2], caus.conditions[:3])):
        print(f"  Because: {node} → {cond}")


def cmd_causal(args):
    """Generate counterfactual causal explanation."""
    case = load_case(args.case)

    query = case.get("query", "")
    g = run_medical_triage(query)

    print("=" * 60)
    print("CAUSAL SEMANTIC ANALYSIS")
    print("=" * 60)
    print(f"\nQuery: {query}")

    # Original execution
    engine = ExecutionEngine(g.semantic)
    ctx = VMContext()
    ctx = g.run(engine, ctx)
    print(f"\n[RESULT] {ctx.regs.get('R_out')}")

    # Causal parents (flip each variable and check outcome)
    print("\n--- CAUSAL PARENTS ---")
    causal = g.semantic.find_causal_parents("n4", g)
    for c in causal:
        status = "CRITICAL" if c["is_causal"] else "CONTEXT"
        print(f"  {c['factor']} = {c['flipped_value']}")
        print(f"    If flipped: {c['original_outcome']} → {c['forked_outcome']}")
        print(f"    [{status}]")

    # Counterfactual explanation
    print("\n--- COUNTERFACTUAL EXPLANATION ---")
    cf = g.semantic.explain_counterfactual("n4", g)
    print(f"Result: {cf['result']}")
    print("Causes:")
    for cause in cf["causes"]:
        critical = "CRITICAL" if cause["is_critical"] else "context"
        print(f"  - {cause['factor']} = {cause['value']} [{critical}]")
        print(f"    {cause['counterfactual']}")

    # Critical path
    print("\n--- CRITICAL PATH ---")
    path = g.semantic.extract_critical_path("n1", "n6", g)
    print(f"  {' → '.join(path)}")
    print(f"\nMinimal causal chain (pruned):")
    for node in path:
        instr = g.nodes.get(node)
        if instr:
            print(f"  {node}: {instr.op} {instr.args}")


def cmd_minimal(args):
    """Find minimal causal set."""
    case = load_case(args.case)
    query = case.get("query", "")
    g = run_medical_triage(query)

    print("=" * 60)
    print("MINIMAL CAUSAL SET ANALYSIS")
    print("=" * 60)

    result = g.semantic.find_minimal_causal_set("n4", g)

    print(f"\nBaseline outcome: {result['baseline_outcome']}")
    print(f"Minimal intervention set: {result['minimal_set']}")
    print(f"\nAlternative outcomes:")
    for alt in result["alternatives"]:
        print(f"  Flip {list(alt['vars'].keys())[0]}={list(alt['vars'].values())[0]} → {alt['outcome']}")


def cmd_why_not(args):
    """Explain why a particular outcome did NOT occur."""
    case = load_case(args.case)
    query = case.get("query", "")
    g = run_medical_triage(query)

    print("=" * 60)
    print("WHY NOT ANALYSIS")
    print("=" * 60)

    if args.outcome:
        result = g.semantic.explain_why_not(args.outcome, g)
        print(f"\nCurrent outcome: {result['current_outcome']}")
        print(f"Desired outcome: {result['target_outcome']}")
        print(f"\nBlocking factors:")
        for bf in result["blocking_factors"]:
            print(f"  - {bf['var']} = {bf['current_value']} blocks because: {bf['reason']}")
        print(f"\nRequired change: {result['required_change']}")
        print(f"\nExplanation: {result['explanation']}")


def cmd_classify(args):
    """Classify causal variables into tiers."""
    case = load_case(args.case)
    query = case.get("query", "")
    g = run_medical_triage(query)

    print("=" * 60)
    print("CAUSAL TYPE CLASSIFICATION")
    print("=" * 60)

    classification = g.semantic.classify_causal_types("n4", g)

    print("\n[DECISION CAUSE]")
    for c in classification["DECISION CAUSE"]:
        print(f"  {c['var']} = {c['value']} (defined at {c['def_node']})")

    print("\n[UPSTREAM CAUSE]")
    for c in classification["UPSTREAM CAUSE"]:
        print(f"  {c['var']} = {c['value']} (feeds: {c.get('feeds_into', 'N/A')})")

    print("\n[CONTEXT]")
    for c in classification["CONTEXT"]:
        print(f"  {c['var']} - no effect on outcome")


def cmd_fork(args):
    """Fork and replay with modifications."""
    case = load_case(args.case)

    query = case.get("query", "")
    g = run_medical_triage(query)

    # Original execution
    engine = ExecutionEngine(g.semantic)
    ctx1 = VMContext()
    ctx1 = g.run(engine, ctx1)

    print(f"[ORIGINAL] R_out = {ctx1.regs.get('R_out')}")

    # Fork at n3 - inject CASE_CRITICAL
    if "fork_at" in case:
        fork_node = case["fork_at"]
    else:
        fork_node = "n3"

    patch = case.get("patch", {"op": "MOV", "args": ["R_result", "CASE_CRITICAL"]})
    forked = g.fork_at(fork_node, patch)
    forked.build_cfg()

    ctx2 = VMContext()
    ctx2 = forked.run(engine, ctx2)

    print(f"[FORKED]  R_out = {ctx2.regs.get('R_out')}")

    # Show the divergence
    orig = ctx1.regs.get("R_out", "")
    fork = ctx2.regs.get("R_out", "")

    print(f"\n{'='*60}")
    print(f"FORK DIVERGENCE:")
    print(f"  Original: {orig}")
    print(f"  Forked:   {fork}")
    print(f"{'='*60}")

    if "911" in fork and "REST" in orig:
        print("VERIFIED: Fork correctly changed outcome from REST to EMERGENCY")


def cmd_run(args):
    """Run agent with tracing."""
    case = load_case(args.case)
    query = case.get("query", "")
    print(f"Running medical triage for: {query}")

    g = run_medical_triage(query)
    engine = ExecutionEngine(g.semantic)
    ctx = g.run(engine, VMContext())

    print(f"Result: {ctx.regs.get('R_out')}")

    # Export DAG
    dot = g.dag_cache.to_dot("Medical Triage DAG")
    if args.dot:
        with open(args.dot, "w") as f:
            f.write(dot)
        print(f"DAG exported to {args.dot}")


def main():
    parser = argparse.ArgumentParser(description="AgentTrace CLI - Causal Semantic IR Engine")
    sub = parser.add_subparsers(dest="cmd")

    exp = sub.add_parser("explain", help="Explain a case file")
    exp.add_argument("case", help="Case JSON file")
    exp.set_defaults(func=cmd_explain)

    fork = sub.add_parser("fork", help="Fork and replay a case")
    fork.add_argument("case", help="Case JSON file")
    fork.set_defaults(func=cmd_fork)

    causal = sub.add_parser("causal", help="Counterfactual causal explanation")
    causal.add_argument("case", help="Case JSON file")
    causal.set_defaults(func=cmd_causal)

    minimal = sub.add_parser("minimal", help="Find minimal causal set")
    minimal.add_argument("case", help="Case JSON file")
    minimal.set_defaults(func=cmd_minimal)

    why_not = sub.add_parser("why-not", help="Explain why outcome did not occur")
    why_not.add_argument("case", help="Case JSON file")
    why_not.add_argument("--outcome", help="Target outcome to explain")
    why_not.set_defaults(func=cmd_why_not)

    classify = sub.add_parser("classify", help="Classify causal variables into tiers")
    classify.add_argument("case", help="Case JSON file")
    classify.set_defaults(func=cmd_classify)

    run = sub.add_parser("run", help="Run agent with tracing")
    run.add_argument("case", help="Case JSON file")
    run.add_argument("--dot", help="Export DAG to DOT file")
    run.set_defaults(func=cmd_run)

    args = parser.parse_args()

    if not args.cmd:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()