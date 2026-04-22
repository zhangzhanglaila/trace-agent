"""
AgentTrace ExecutionGraph - v0.1
Minimal runnable runtime for agent execution graphs.

Core invariant:
    output = f(input, context, compute_fn)  # Always deterministic replay
"""

from typing import Dict, Any, Callable, Optional, List
import copy
import hashlib


class ExecutionContext:
    """Runtime state for graph execution."""

    def __init__(self, graph: "ExecutionGraph"):
        self.graph = graph
        self.global_state: Dict[str, Any] = {}
        self.emitter = None  # For WebSocket events


class Node:
    """Execution unit - a node that can be recomputed given input + context."""

    def __init__(
        self,
        id: str,
        type: str,  # "TOOL" | "LLM" | "STATE" | "DECISION"
        input: Dict = None,
        compute_fn: Optional[Callable] = None,
        metadata: Dict = None
    ):
        self.id = id
        self.type = type
        self.input = input or {}
        self.output = None
        self.compute_fn = compute_fn
        self.dirty = False
        self.state_hash: Optional[str] = None
        self.metadata = metadata or {}
        self._hash()

    def execute(self, ctx: ExecutionContext) -> Any:
        """Execute this node: output = f(input, context)"""
        if self.compute_fn:
            self.output = self.compute_fn(self.input, ctx)
        self.state_hash = self._hash()
        return self.output

    def mutate(self, new_output: Any):
        """Mutate output and mark this node dirty."""
        self.output = new_output
        self.dirty = True
        self.state_hash = self._hash()

    def _hash(self) -> str:
        """Deterministic hash of output for change detection."""
        return hashlib.md5(str(self.output).encode()).hexdigest()

    def __repr__(self):
        return f"Node({self.id}, type={self.type}, output={self.output}, dirty={self.dirty})"


class Edge:
    """Causal dependency between nodes."""

    def __init__(self, from_node: str, to_node: str, trigger: str = "invoke"):
        self.from_node = from_node
        self.to_node = to_node
        self.trigger = trigger  # "invoke" | "tool_result" | "llm_step"

    def __repr__(self):
        return f"Edge({self.from_node} → {self.to_node} [{self.trigger}])"


class ExecutionGraph:
    """
    Computable execution graph for agent runtime.

    Key operations:
    - build: add nodes and edges from agent execution
    - fork: copy graph, mutate node, invalidate downstream
    - replay: recompute dirty subgraph
    - diff: compare original vs forked graph
    """

    def __init__(self):
        self.nodes: Dict[str, Node] = {}
        self.edges: List[Edge] = []
        self.root: Optional[str] = None

    def add_node(self, node: Node):
        """Add a node to the graph."""
        self.nodes[node.id] = node
        if self.root is None:
            self.root = node.id

    def add_edge(self, from_node: str, to_node: str, trigger: str = "invoke"):
        """Add a causal edge between nodes."""
        if from_node in self.nodes and to_node in self.nodes:
            self.edges.append(Edge(from_node, to_node, trigger))

    def fork(self, node_id: str, new_output: Any) -> "ExecutionGraph":
        """
        Fork the graph at node_id with new_output.

        Creates a deep copy, mutates the node (NOT recompute),
        and marks ONLY downstream as dirty (not the mutated node itself).
        Returns the new forked graph (original unchanged).
        """
        new_graph = copy.deepcopy(self)

        # Clear all dirty flags first (fresh start for forked graph)
        for node in new_graph.nodes.values():
            node.dirty = False

        node = new_graph.nodes.get(node_id)
        if node is None:
            raise ValueError(f"Node {node_id} not found in graph")

        # Mutate output directly (NOT via execute, to preserve the new value)
        node.output = new_output
        node.state_hash = node._hash()  # Update hash after mutation
        node.dirty = False  # Don't recompute the mutated node itself

        # Only downstream nodes should be dirty (they need to react to the change)
        new_graph.invalidate_downstream(node_id)

        return new_graph

    def invalidate_downstream(self, node_id: str):
        """
        Recursively mark all downstream nodes as dirty.
        Uses stack-based DFS traversal.
        """
        stack = [node_id]
        visited = set()

        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)

            for edge in self.edges:
                if edge.from_node == current:
                    target = self.nodes.get(edge.to_node)
                    if target:
                        target.dirty = True
                        stack.append(edge.to_node)

    def replay(self, ctx: ExecutionContext):
        """
        Re-execute all dirty nodes in topological order.
        Only recomputes nodes that were affected by a mutation.
        """
        # Simple approach: replay all dirty nodes with compute_fn
        for node_id, node in self.nodes.items():
            if node.dirty and node.compute_fn:
                node.execute(ctx)
                node.dirty = False

    def execute_full(self, ctx: ExecutionContext):
        """Execute the entire graph from root."""
        for node_id, node in self.nodes.items():
            if node.compute_fn:
                node.execute(ctx)

    def diff(self, other: "ExecutionGraph") -> Dict[str, Any]:
        """
        Compare this graph with another (e.g., a fork).
        Returns nodes that differ between the two graphs.
        """
        diff_result = {
            "added_nodes": [],
            "removed_nodes": [],
            "changed_nodes": [],
            "same_nodes": []
        }

        all_ids = set(self.nodes.keys()) | set(other.nodes.keys())

        for node_id in all_ids:
            self_node = self.nodes.get(node_id)
            other_node = other.nodes.get(node_id)

            if self_node and not other_node:
                diff_result["added_nodes"].append(node_id)
            elif not self_node and other_node:
                diff_result["removed_nodes"].append(node_id)
            elif self_node and other_node:
                if self_node.state_hash != other_node.state_hash:
                    diff_result["changed_nodes"].append({
                        "id": node_id,
                        "original": self_node.output,
                        "forked": other_node.output
                    })
                else:
                    diff_result["same_nodes"].append(node_id)

        return diff_result

    def __repr__(self):
        edges_str = ", ".join([str(e) for e in self.edges])
        nodes_str = ", ".join([str(n) for n in self.nodes.values()])
        return f"ExecutionGraph(nodes=[{nodes_str}], edges=[{edges_str}])"


# ============================================================
# MINIMAL FORK DEMO (10 lines)
# ============================================================

def add_numbers(input: Dict, ctx) -> int:
    """Simple compute function: add two numbers."""
    return input["a"] + input["b"]


def demo():
    """Run the minimal fork demonstration."""
    print("=" * 50)
    print("ExecutionGraph Fork Demo")
    print("=" * 50)

    # Build graph
    g = ExecutionGraph()
    g.add_node(Node("n1", "LLM", {"a": 1, "b": 2}, add_numbers))

    # Execute original
    ctx = ExecutionContext(g)
    original_output = g.nodes["n1"].execute(ctx)

    print(f"\n[1] Original graph")
    print(f"    n1.output = {original_output}")  # Should be 3

    # Fork at n1 with new output
    forked = g.fork("n1", 999)

    print(f"\n[2] Forked graph (n1 mutated to 999)")
    print(f"    forked.n1.output = {forked.nodes['n1'].output}")  # Should be 999

    # Replay forked graph (dirty nodes)
    ctx_forked = ExecutionContext(forked)
    forked.replay(ctx_forked)

    print(f"\n[3] After replay on forked graph")
    print(f"    forked.n1.output = {forked.nodes['n1'].output}")

    # Diff
    diff = g.diff(forked)
    print(f"\n[4] Diff result")
    print(f"    changed_nodes: {diff['changed_nodes']}")

    print("\n" + "=" * 50)
    if diff['changed_nodes'] and diff['changed_nodes'][0]['original'] == 3 and diff['changed_nodes'][0]['forked'] == 999:
        print("Fork verified: original=3, forked=999")
    else:
        print(f"Fork FAILED: original={diff['changed_nodes']}")
    print("=" * 50)


if __name__ == "__main__":
    demo()