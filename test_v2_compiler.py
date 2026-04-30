"""
Test suite for v2.0 TraceCompiler - production-grade verification.
Tests: flat branch, nested branch, long chain.
"""
from agent_obs.execution_graph import TraceCompiler, ExecutionGraph

# ============================================================
# TEST 1: Flat Branch
# ============================================================
print("=" * 60)
print("TEST 1: Flat Branch")
print("=" * 60)
trace1 = {
    "steps": [
        {"id": "s1", "type": "llm", "prompt": "test", "output": "thinking..."},
        {"id": "s2", "type": "branch", "condition": "is_critical", "value": True,
         "true_branch": "s3", "false_branch": "s4", "merge": "s5"},
        {"id": "s3", "type": "tool", "name": "emergency", "result": "CALL 911"},
        {"id": "s4", "type": "tool", "name": "rest", "result": "REST"},
        {"id": "s5", "type": "merge"},
        {"id": "s6", "type": "output", "var": "final", "value": "DONE"},
    ]
}
tc1 = TraceCompiler()
g1 = tc1.compile(trace1)
for nid, instr in g1.nodes.items():
    print(f"  {nid}: {instr.op} -> {instr.next}")
b = tc1.branches["br_s2"]
assert b.true_exit == "s3", f"Expected s3, got {b.true_exit}"
assert b.false_exit == "s4", f"Expected s4, got {b.false_exit}"
assert len(g1.cfg.blocks["s5"].predecessors) == 2, f"Expected 2 preds for merge, got {len(g1.cfg.blocks['s5'].predecessors)}"
print("PASS: Flat branch - exits correct, merge has 2 predecessors")

# ============================================================
# TEST 2: Nested Branch
# ============================================================
print()
print("=" * 60)
print("TEST 2: Nested Branch")
print("=" * 60)
trace2 = {
    "steps": [
        {"id": "s1", "type": "llm", "prompt": "test"},
        {"id": "s2", "type": "branch", "condition": "outer_cond", "value": True,
         "true_branch": "s3", "false_branch": "s9", "merge": "s8"},
        {"id": "s3", "type": "llm", "prompt": "inner thinking"},
        {"id": "s4", "type": "branch", "condition": "inner_cond", "value": True,
         "true_branch": "s5", "false_branch": "s6", "merge": "s7"},
        {"id": "s5", "type": "tool", "name": "tool_a", "result": "A"},
        {"id": "s6", "type": "tool", "name": "tool_b", "result": "B"},
        {"id": "s7", "type": "merge"},
        {"id": "s9", "type": "tool", "name": "tool_c", "result": "C"},
        {"id": "s8", "type": "merge"},
        {"id": "s10", "type": "output", "var": "final", "value": "DONE"},
    ]
}
tc2 = TraceCompiler()
g2 = tc2.compile(trace2)
print("Nodes:")
for nid, instr in g2.nodes.items():
    print(f"  {nid}: {instr.op} -> {instr.next}")

print()
print("Branches:")
for bid, branch in tc2.branches.items():
    print(f"  {bid}:")
    print(f"    true_nodes: {branch.true_nodes}")
    print(f"    false_nodes: {branch.false_nodes}")
    print(f"    true_exit: {branch.true_exit}")
    print(f"    false_exit: {branch.false_exit}")

b_outer = tc2.branches["br_s2"]
b_inner = tc2.branches["br_s4"]
assert len(b_outer.true_nodes) >= 5, f"Expected >=5 nodes on outer true path, got {len(b_outer.true_nodes)}"
assert b_outer.true_exit is not None, "Outer true_exit should not be None"
assert b_outer.false_exit == "s9", f"Expected s9, got {b_outer.false_exit}"
assert b_inner.true_exit == "s5", f"Expected s5, got {b_inner.true_exit}"
assert b_inner.false_exit == "s6", f"Expected s6, got {b_inner.false_exit}"

outer_merge = g2.cfg.blocks.get("s8")
assert outer_merge and len(outer_merge.predecessors) == 2, f"Outer merge should have 2 preds"
inner_merge = g2.cfg.blocks.get("s7")
assert inner_merge and len(inner_merge.predecessors) == 2, f"Inner merge should have 2 preds"
print("PASS: Nested branch - both layers correct, both merges have 2 predecessors")

# ============================================================
# TEST 3: Long Chain
# ============================================================
print()
print("=" * 60)
print("TEST 3: Long Chain (exit = last node, not first)")
print("=" * 60)
trace3 = {
    "steps": [
        {"id": "s1", "type": "llm", "prompt": "test"},
        {"id": "s2", "type": "branch", "condition": "cond", "value": True,
         "true_branch": "s3", "false_branch": "s7", "merge": "s8"},
        {"id": "s3", "type": "tool", "name": "A", "result": "A"},
        {"id": "s4", "type": "tool", "name": "B", "result": "B"},
        {"id": "s5", "type": "tool", "name": "C", "result": "C"},
        {"id": "s6", "type": "tool", "name": "D", "result": "D"},
        {"id": "s7", "type": "tool", "name": "alt", "result": "alt"},
        {"id": "s8", "type": "merge"},
        {"id": "s9", "type": "output", "var": "final", "value": "DONE"},
    ]
}
tc3 = TraceCompiler()
g3 = tc3.compile(trace3)
for nid, instr in g3.nodes.items():
    print(f"  {nid}: {instr.op} -> {instr.next}")

b3 = tc3.branches["br_s2"]
print(f"\ntrue_nodes: {b3.true_nodes}")
print(f"true_exit: {b3.true_exit}")
print(f"false_nodes: {b3.false_nodes}")
print(f"false_exit: {b3.false_exit}")

assert b3.true_exit == "s6", f"Expected s6 (D), got {b3.true_exit}"
assert b3.false_exit == "s7", f"Expected s7, got {b3.false_exit}"
assert len(b3.true_nodes) == 4, f"Expected 4 nodes on true path, got {len(b3.true_nodes)}"
assert b3.true_nodes[0] == "s3", f"First true node should be s3 (A)"
assert b3.true_nodes[-1] == "s6", f"Last true node should be s6 (D)"

merge = g3.cfg.blocks.get("s8")
assert merge and len(merge.predecessors) == 2, f"Merge should have 2 preds"
assert "s8" in g3.nodes["s6"].next, "s6 should point to s8"
print("PASS: Long chain - exit is D (not A), all 4 nodes on path")

# ============================================================
print()
print("=" * 60)
print("ALL 3 TESTS PASSED")
print("=" * 60)
