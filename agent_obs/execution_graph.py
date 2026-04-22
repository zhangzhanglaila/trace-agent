"""
AgentTrace ExecutionGraph v0.2 - Graph-Native Runtime Kernel

Core Principle (INVARIANT):
    All execution is graph traversal + node transition.
    No agent loop exists outside the graph.

This is NOT a tracing system. This IS the execution engine.

Key changes from v0.1:
- Node.next_nodes: execution transitions define control flow
- ExecutionContext.memory: graph-owned runtime state (not external)
- Graph.run(): graph controls execution, not external scheduler
- Fork: rewrites execution path, not copies data
- Replay: re-traverses graph, not recomputes nodes
"""

from typing import Dict, Any, Callable, Optional, List
import copy
import hashlib


class Node:
    """
    Executable transition unit.
    NOT data storage - a STATE TRANSITION that modifies graph state.

    Key attributes:
    - compute_fn: the actual execution logic
    - next_nodes: defines control flow (which node runs next)
    - type: determines node semantics (LLM, TOOL, STATE, BRANCH)
    """

    def __init__(
        self,
        id: str,
        type: str,  # "LLM" | "TOOL" | "STATE" | "BRANCH" | "MERGE"
        compute_fn: Optional[Callable] = None,
        metadata: Dict = None
    ):
        self.id = id
        self.type = type
        self.compute_fn = compute_fn
        self.metadata = metadata or {}

        # Execution state
        self.input = {}
        self.output = None
        self.state = {}  # Node-local execution state

        # Control flow: nodes this one can transition to
        self.next_nodes: List[str] = []
        self.branch_fn: Optional[Callable] = None  # For conditional branching

        self.state_hash: Optional[str] = None
        self._hash()

    def execute(self, ctx: "ExecutionContext") -> Any:
        """
        Execute this node: modifies context, returns output.

        Key invariant: execution modifies graph-owned state,
        not external agent state.
        """
        if self.compute_fn:
            self.output = self.compute_fn(self.input, ctx)
        self.state_hash = self._hash()
        return self.output

    def add_next(self, node_id: str):
        """Add a transition target."""
        if node_id not in self.next_nodes:
            self.next_nodes.append(node_id)

    def set_branch(self, branch_fn: Callable):
        """Set conditional branching function: fn(output) -> node_id"""
        self.branch_fn = branch_fn

    def get_next(self) -> Optional[str]:
        """Get the next node based on branching logic."""
        if self.branch_fn and self.output is not None:
            return self.branch_fn(self.output)
        return self.next_nodes[0] if self.next_nodes else None

    def mutate_output(self, new_output: Any):
        """Mutate node output without recompute."""
        self.output = new_output
        self.state_hash = self._hash()

    def _hash(self) -> str:
        return hashlib.md5(str(self.output).encode()).hexdigest()

    def __repr__(self):
        return f"Node({self.id}, type={self.type}, output={self.output}, next={self.next_nodes})"


class ExecutionContext:
    """
    Graph-owned runtime state.
    All agent state lives here, not in external variables.
    """

    def __init__(self, graph: "ExecutionGraph"):
        self.graph = graph

        # Graph-owned memory (NOT external agent state)
        self.memory: Dict[str, Any] = {}
        self.tool_results: Dict[str, Any] = {}

        # Execution control
        self.current_node_id: Optional[str] = None
        self.done = False
        self.forked = False

        # Traversal history (for replay/debugging)
        self.path: List[str] = []

    def set_memory(self, key: str, value: Any):
        """Set a value in graph memory."""
        self.memory[key] = value

    def get_memory(self, key: str) -> Any:
        """Get a value from graph memory."""
        return self.memory.get(key)

    def emit_event(self, event_type: str, data: Dict):
        """Emit execution event (for UI/logging)."""
        if self.graph.emitter:
            self.graph.emitter.emit(event_type, data)


class ExecutionGraph:
    """
    Graph-native execution engine.
    Graph IS the runtime - not a container for execution logs.

    Core invariant:
        Execution = graph traversal. No external scheduler.
    """

    def __init__(self):
        self.nodes: Dict[str, Node] = {}
        self.root: Optional[str] = None
        self.emitter = None  # For WebSocket events

    def add_node(self, node: Node) -> "ExecutionGraph":
        """Add a node to the graph (fluent API)."""
        self.nodes[node.id] = node
        if self.root is None:
            self.root = node.id
        return self

    def set_root(self, node_id: str) -> "ExecutionGraph":
        """Set the entry point node."""
        self.root = node_id
        return self

    def link(self, from_id: str, to_id: str) -> "ExecutionGraph":
        """Link two nodes with default transition."""
        if from_id in self.nodes and to_id in self.nodes:
            self.nodes[from_id].add_next(to_id)
        return self

    def branch(self, node_id: str, branch_fn: Callable) -> "ExecutionGraph":
        """Set branching function on a node."""
        if node_id in self.nodes:
            self.nodes[node_id].set_branch(branch_fn)
        return self

    def run(self, agent, query: str) -> "ExecutionContext":
        """
        Execute the graph with an agent.
        Graph controls execution, not external loop.

        Agent interacts with graph ONLY through nodes.
        """
        ctx = ExecutionContext(self)
        ctx.set_memory("query", query)
        ctx.emit_event("session_start", {"query": query})

        # Graph traversal loop (no external scheduler)
        current_id = self.root

        while current_id and not ctx.done:
            node = self.nodes.get(current_id)

            if node is None:
                ctx.done = True
                break

            ctx.current_node_id = node.id
            ctx.path.append(node.id)

            # Execute node
            result = node.execute(ctx)

            # Agent interaction happens INSIDE LLM nodes
            if node.type == "LLM" and hasattr(agent, "llm_think"):
                ctx.emit_event("reasoning_complete", {
                    "step": len(ctx.path),
                    "thought": result.get("thought", ""),
                    "action": result.get("action"),
                    "action_input": result.get("action_input", {})
                })

                # Store decision in node state
                if isinstance(result, dict):
                    node.state["decision"] = result

            elif node.type == "TOOL":
                ctx.emit_event("tool_result", {
                    "step": len(ctx.path),
                    "tool": node.metadata.get("tool_name", "unknown"),
                    "result": result
                })

                # Store tool result in context memory
                ctx.tool_results[node.id] = result

            # Determine next node (GRAPH CONTROL FLOW)
            next_id = node.get_next()

            if next_id is None:
                ctx.done = True
            else:
                current_id = next_id

            ctx.emit_event("state_snapshot", {
                "step": len(ctx.path) - 1,
                "current_node": node.id,
                "output": str(result)[:100]
            })

        return ctx

    def invalidate_downstream(self, node_id: str):
        """
        Mark all downstream nodes as dirty (needing recompute).
        Uses DFS from node_id through edges.
        """
        stack = [node_id]
        visited = set()

        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)

            for node in self.nodes.values():
                if node.next_nodes and current in node.next_nodes:
                    if node.id not in visited:
                        node.dirty = True
                        stack.append(node.id)

    def fork(self, node_id: str, new_output: Any, new_compute_fn: Callable = None) -> "ExecutionGraph":
        """
        Fork = execution path divergence.
        Creates alternate execution by rewriting node behavior.

        NOT a copy of data - a rewrite of execution path.
        """
        new_graph = copy.deepcopy(self)

        # Get the node to mutate
        target = new_graph.nodes.get(node_id)
        if target is None:
            raise ValueError(f"Node {node_id} not found")

        # Mutate output directly (user intervention)
        # Don't call execute() - preserve the user's edit
        target.mutate_output(new_output)
        target.compute_fn = None  # Skip recompute for mutated node

        # Mark only downstream nodes for recompute
        new_graph.invalidate_downstream(node_id)

        # Optionally replace compute function (deeper fork)
        if new_compute_fn:
            target.compute_fn = new_compute_fn

        return new_graph

    def fork_from_state(self, node_id: str, state_patch: Dict) -> "ExecutionGraph":
        """
        Fork by patching node state (more surgical than full mutation).
        """
        new_graph = copy.deepcopy(self)

        target = new_graph.nodes.get(node_id)
        if target:
            target.state.update(state_patch)

        return new_graph

    def replay(self, agent, query: str, from_node_id: str = None) -> "ExecutionContext":
        """
        Replay = graph re-execution from a point.
        Only recomputes nodes marked dirty (affected by fork).
        """
        if from_node_id:
            # Mark downstream as dirty
            self.invalidate_downstream(from_node_id)

        # Only recompute dirty nodes with compute_fn
        for node_id, node in self.nodes.items():
            if node.dirty and node.compute_fn:
                node.execute(ExecutionContext(self))

        # Run full traversal to update context
        return self.run(agent, query)

    def diff(self, other: "ExecutionGraph") -> Dict[str, Any]:
        """
        Structural diff between two graphs (original vs forked).
        """
        result = {
            "node_diffs": [],
            "path_differences": []
        }

        all_ids = set(self.nodes.keys()) | set(other.nodes.keys())

        for node_id in all_ids:
            original = self.nodes.get(node_id)
            forked = other.nodes.get(node_id)

            if original and forked:
                if original.state_hash != forked.state_hash:
                    result["node_diffs"].append({
                        "id": node_id,
                        "type": original.type,
                        "original_output": original.output,
                        "forked_output": forked.output
                    })

        return result

    def to_trace(self) -> List[Dict]:
        """Export graph as event stream (for UI compatibility)."""
        trace = []
        for node_id in self.nodes:
            node = self.nodes[node_id]
            trace.append({
                "type": node.type,
                "id": node_id,
                "output": node.output,
                "next_nodes": node.next_nodes,
                "metadata": node.metadata
            })
        return trace

    def __repr__(self):
        return f"ExecutionGraph(nodes={len(self.nodes)}, root={self.root})"


# ============================================================
# MINIMAL DEMO: Graph-native execution
# ============================================================

def llm_node_fn(input: Dict, ctx: ExecutionContext) -> Dict:
    """LLM node: think and decide."""
    query = ctx.get_memory("query")
    return {
        "thought": f"Analyzing: {query}",
        "action": "diagnose",
        "action_input": {"symptoms": query}
    }


def tool_node_fn(input: Dict, ctx: ExecutionContext) -> str:
    """Tool node: execute tool call."""
    tool_name = input.get("tool", "unknown")
    args = input.get("args", {})

    if hasattr(ctx.graph, "_tool_registry"):
        tool_fn = ctx.graph._tool_registry.get(tool_name)
        if tool_fn:
            return tool_fn(**args)

    return f"Result of {tool_name}"


def demo():
    """Run graph-native execution demo."""
    print("=" * 60)
    print("ExecutionGraph v0.2 - Graph-Native Runtime Demo")
    print("=" * 60)

    # Build the graph (NOT run the agent)
    g = ExecutionGraph()

    # Node 1: LLM reasoning
    g.add_node(Node("n1", "LLM", llm_node_fn))
    g.nodes["n1"].input = {}

    # Node 2: Tool execution
    g.add_node(Node("n2", "TOOL", tool_node_fn))
    g.nodes["n2"].input = {}
    g.nodes["n2"].metadata["tool_name"] = "diagnose"

    # Node 3: Final decision
    def decision_fn(input: Dict, ctx: ExecutionContext) -> str:
        tool_result = ctx.tool_results.get("n2", "")
        if "CRITICAL" in str(tool_result):
            return "EMERGENCY PROTOCOL: CALL 911"
        return "REST AND FLUIDS"

    g.add_node(Node("n3", "STATE", decision_fn))

    # Link nodes: n1 → n2 → n3
    g.set_root("n1").link("n1", "n2").link("n2", "n3")

    # Set branching on n3
    g.branch("n3", lambda output: None)  # No next node = terminal

    print(f"\n[1] Graph built: {g}")

    # Simulated agent (for LLM calls)
    class MockAgent:
        async def llm_think(self, messages):
            return {"thought": "thinking", "action": None, "content": "done"}

    agent = MockAgent()

    # Execute graph
    ctx = g.run(agent, "Patient has mild discomfort")

    print(f"\n[2] Execution completed")
    print(f"    Path: {' → '.join(ctx.path)}")
    print(f"    n3.output: {g.nodes['n3'].output}")

    # Fork at n2 with critical result
    print(f"\n[3] Fork at n2: CASE_NORMAL → CASE_CRITICAL")

    forked = g.fork("n2", "CASE_CRITICAL")

    print(f"    Original n2.output: {g.nodes['n2'].output}")
    print(f"    Forked n2.output: {forked.nodes['n2'].output}")

    # Replay on forked graph
    ctx2 = forked.run(agent, "Patient has mild discomfort")

    print(f"\n[4] Replay on forked graph")
    print(f"    Path: {' → '.join(ctx2.path)}")
    print(f"    n3.output: {forked.nodes['n3'].output}")

    # Diff
    diff = g.diff(forked)
    print(f"\n[5] Diff: {len(diff['node_diffs'])} node(s) changed")

    print("\n" + "=" * 60)
    print("RESULT:")
    print(f"  Original:  {g.nodes['n3'].output}")
    print(f"  Forked:    {forked.nodes['n3'].output}")
    print("=" * 60)


if __name__ == "__main__":
    demo()