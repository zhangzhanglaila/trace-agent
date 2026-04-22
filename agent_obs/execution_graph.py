"""
AgentTrace ExecutionGraph v0.3 - Graph VM Kernel

Core Architectural Shift (v0.2 → v0.3):
    v0.2: graph executes agent
    v0.3: agent interprets graph as IR (VM semantics)

    NOT a linked-list executor.
    Graph is a CFG (Control Flow Graph), engine is the VM.

Key Principles:
    1. Node = declarative IR instruction (no compute_fn)
    2. ExecutionEngine = semantic runtime (step function)
    3. Control flow = engine + graph joint resolution (NOT node.next)

v0.3 Architecture:
    ┌──────────────┐
    │ ExecutionVM  │  ← engine.step(node, ctx)
    └──────┬───────┘
           │
    semantic execution
           │
           ▼
    ┌──────────────┐
    │   Node IR    │  ← spec is declarative
    └──────┬───────┘
           │
    transition resolution
           │
           ▼
    ┌──────────────┐
    │ Next Node(s) │  ← resolve_next(node, result, graph)
    └──────────────┘
"""

from typing import Dict, Any, Callable, Optional, List, Union
import copy
import hashlib
import json


# ============================================================
# Node IR - Declarative Instruction (not executable)
# ============================================================

class Node:
    """
    Node = IR instruction in the execution graph.

    Key distinction from v0.2:
        - spec is declarative (WHAT to do)
        - edges are possible control flow targets
        - compute_fn is REMOVED (engine provides semantics)

    Node does NOT execute itself. Engine does.
    """

    def __init__(
        self,
        id: str,
        type: str,  # "LLM" | "TOOL" | "BRANCH" | "STATE" | "TERMINAL"
        spec: Dict = None,  # declarative instruction
        metadata: Dict = None
    ):
        self.id = id
        self.type = type
        self.spec = spec or {}  # Declarative spec (not compute_fn)
        self.metadata = metadata or {}

        # Possible next nodes (CFG edges) - ALL possible transitions
        self.edges: List[str] = []

        # Branch function: determines which edge to take
        # Only used for BRANCH type nodes
        self.branch_fn: Optional[Callable] = None

        # Execution state (set by engine during run)
        self.output: Any = None
        self.state_hash: Optional[str] = None

    def add_edge(self, target_id: str):
        """Add a possible control flow target."""
        if target_id not in self.edges:
            self.edges.append(target_id)

    def set_branch(self, branch_fn: Callable):
        """Set branch resolution function: fn(output, ctx) -> target_id"""
        self.branch_fn = branch_fn

    def get_possible_next(self) -> List[str]:
        """Return all possible next node IDs (for CFG analysis)."""
        return self.edges.copy()

    def _hash(self) -> str:
        return hashlib.md5(str(self.output).encode()).hexdigest()

    def __repr__(self):
        return f"Node({self.id}, type={self.type}, edges={self.edges})"


# ============================================================
# ExecutionContext - VM State
# ============================================================

class ExecutionContext:
    """
    VM state during execution.
    All state is graph-owned, not in external agent.
    """

    def __init__(self, graph: "ExecutionGraph"):
        self.graph = graph

        # VM registers
        self.memory: Dict[str, Any] = {}  # Named variables
        self.accumulator: Any = None       # Last operation result
        self.pc: Optional[str] = None      # Program counter (current node ID)
        self.done = False
        self.forked = False

        # Tool registry (injected into VM)
        self.tool_registry: Dict[str, Callable] = {}

        # LLM handler (injected into VM)
        self.llm_handler: Optional[Callable] = None

        # Execution trace (for replay)
        self.trace: List[Dict] = []

        # Event emitter (for UI)
        self.emitter = None

    def set_memory(self, key: str, value: Any):
        self.memory[key] = value

    def get_memory(self, key: str) -> Any:
        return self.memory.get(key)

    def emit(self, event_type: str, data: Dict):
        if self.emitter:
            self.emitter.emit(event_type, data)


# ============================================================
# ExecutionEngine - The VM Runtime
# ============================================================

class ExecutionEngine:
    """
    The VM that interprets the graph IR.

    This is the ONLY place where execution semantics live.
    Node is just a declarative spec - engine provides meaning.

    Key methods:
        step(node, ctx)     - execute one node
        resolve_next()      - determine next node(s)
    """

    def __init__(self):
        self.name = "AgentTraceVM-v0.3"

    def step(self, node: Node, ctx: ExecutionContext) -> Any:
        """
        Execute a single node according to its type.
        Returns result that will be used for transition resolution.
        """
        ctx.pc = node.id

        if node.type == "LLM":
            return self._step_llm(node, ctx)
        elif node.type == "TOOL":
            return self._step_tool(node, ctx)
        elif node.type == "BRANCH":
            return self._step_branch(node, ctx)
        elif node.type == "STATE":
            return self._step_state(node, ctx)
        elif node.type == "TERMINAL":
            ctx.done = True
            return node.output
        else:
            return None

    def _step_llm(self, node: Node, ctx: ExecutionContext) -> Dict:
        """
        LLM node: call the LLM handler.
        spec = {"prompt": "...", "system": "..."}
        """
        ctx.emit("llm_call", {"node": node.id, "spec": node.spec})

        if ctx.llm_handler:
            result = ctx.llm_handler(node.spec, ctx)
        else:
            # Mock LLM for testing
            result = {
                "thought": f"Thinking about: {node.spec.get('query', '')}",
                "action": node.spec.get("default_action"),
                "action_input": node.spec.get("default_action_input", {})
            }

        node.output = result
        ctx.accumulator = result

        ctx.emit("llm_result", {"node": node.id, "result": result})

        return result

    def _step_tool(self, node: Node, ctx: ExecutionContext) -> Any:
        """
        Tool node: dispatch to tool registry.
        spec = {"tool": "tool_name", "args": {...}}
        """
        tool_name = node.spec.get("tool")
        args = node.spec.get("args", {})

        ctx.emit("tool_call", {"node": node.id, "tool": tool_name, "args": args})

        if tool_name in ctx.tool_registry:
            result = ctx.tool_registry[tool_name](**args)
        else:
            result = f"Tool '{tool_name}' not found in registry"

        node.output = result
        ctx.accumulator = result

        ctx.emit("tool_result", {"node": node.id, "result": result})

        return result

    def _step_branch(self, node: Node, ctx: ExecutionContext) -> str:
        """
        Branch node: evaluate condition and resolve next.
        spec = {"condition": "...", "true_target": "nX", "false_target": "nY"}
        """
        if node.branch_fn:
            target = node.branch_fn(node.output, ctx)
        else:
            # Default: check accumulator truthiness
            target = node.edges[0] if node.edges else None

        ctx.emit("branch", {"node": node.id, "target": target})
        return target

    def _step_state(self, node: Node, ctx: ExecutionContext) -> Any:
        """
        State node: compute derived state from context.
        spec = {"operation": "read|write|transform", ...}
        """
        op = node.spec.get("operation", "read")

        if op == "read":
            result = ctx.get_memory(node.spec.get("key"))
        elif op == "write":
            ctx.set_memory(node.spec.get("key"), node.spec.get("value"))
            result = node.spec.get("value")
        elif op == "transform":
            key = node.spec.get("key")
            fn = node.spec.get("fn")
            val = ctx.get_memory(key)
            result = fn(val) if fn else val
        else:
            result = None

        node.output = result
        ctx.accumulator = result

        return result

    def resolve_next(self, node: Node, result: Any, ctx: ExecutionContext) -> Optional[str]:
        """
        Resolve the next node to execute.

        Key difference from v0.2:
            - NOT simply node.edges[0]
            - Engine evaluates result + context to determine transition
            - This is where control flow semantics live
        """
        # Terminal node: stop execution
        if node.type == "TERMINAL":
            ctx.done = True
            return None

        # Branch nodes: use branch function
        if node.type == "BRANCH":
            return self._resolve_branch(node, result, ctx)

        # Default: single sequential edge
        if node.edges:
            return node.edges[0]

        return None

    def _resolve_branch(self, node: Node, result: Any, ctx: ExecutionContext) -> Optional[str]:
        """Resolve branch target based on result."""
        if node.branch_fn:
            return node.branch_fn(result, ctx)

        # Default: check if result is truthy
        if result and node.edges:
            return node.edges[0]

        return node.edges[1] if len(node.edges) > 1 else None


# ============================================================
# ExecutionGraph - Program IR (CFG)
# ============================================================

class ExecutionGraph:
    """
    ExecutionGraph = Program IR (Control Flow Graph)

    This is the PROGRAM being executed, not the executor.
    Engine interprets this graph.

    Key operations:
        run(engine, ctx)    - execute graph with engine
        fork(node_id, patch) - create alternate execution path
        replay(from_node)  - re-execute from checkpoint
    """

    def __init__(self):
        self.nodes: Dict[str, Node] = {}
        self.root: Optional[str] = None
        self.terminals: List[str] = []

    def add_node(self, node: Node) -> "ExecutionGraph":
        """Add a node to the graph (fluent API)."""
        self.nodes[node.id] = node
        if node.type == "TERMINAL":
            self.terminals.append(node.id)
        return self

    def set_root(self, node_id: str) -> "ExecutionGraph":
        self.root = node_id
        return self

    def link(self, from_id: str, to_id: str) -> "ExecutionGraph":
        """Add CFG edge from node to target."""
        if from_id in self.nodes and to_id in self.nodes:
            self.nodes[from_id].add_edge(to_id)
        return self

    def link_branch(self, node_id: str, true_target: str, false_target: str) -> "ExecutionGraph":
        """Link a branch node with true/false targets."""
        if node_id in self.nodes:
            self.nodes[node_id].edges = [true_target, false_target]
            self.nodes[node_id].type = "BRANCH"
        return self

    def set_branch_fn(self, node_id: str, fn: Callable) -> "ExecutionGraph":
        """Set branch resolution function on a node."""
        if node_id in self.nodes:
            self.nodes[node_id].set_branch(fn)
        return self

    def run(self, engine: ExecutionEngine, ctx: ExecutionContext) -> ExecutionContext:
        """
        Execute graph using engine as VM interpreter.

        Execution loop:
            1. Engine.step(node, ctx) - semantic execution
            2. Engine.resolve_next() - control flow resolution
            3. Repeat until terminal or ctx.done
        """
        if not self.root:
            ctx.done = True
            return ctx

        current_id = self.root

        while not ctx.done and current_id:
            node = self.nodes.get(current_id)
            if not node:
                ctx.done = True
                break

            # Semantic execution (engine provides meaning)
            result = engine.step(node, ctx)

            # Control flow resolution (engine + graph together)
            next_id = engine.resolve_next(node, result, ctx)

            # Record trace
            ctx.trace.append({
                "node": node.id,
                "type": node.type,
                "output": str(node.output)[:100] if node.output else None,
                "next": next_id
            })

            # Transition
            current_id = next_id

        return ctx

    def fork(self, node_id: str, patch: Dict) -> "ExecutionGraph":
        """
        Fork = create alternate execution path.

        Creates a deep copy and applies a patch to a node.
        The patched graph can be re-executed.
        """
        new_graph = copy.deepcopy(self)

        target = new_graph.nodes.get(node_id)
        if not target:
            raise ValueError(f"Node {node_id} not found")

        # Apply patch: patch = {"output": new_value, "spec": {...}}
        if "output" in patch:
            target.output = patch["output"]
            target.state_hash = target._hash()

        if "spec" in patch:
            target.spec.update(patch["spec"])

        if "branch_fn" in patch:
            target.set_branch(patch["branch_fn"])

        return new_graph

    def diff(self, other: "ExecutionGraph") -> Dict[str, Any]:
        """Structural diff between two graphs."""
        result = {
            "changed_nodes": [],
            "original_only": [],
            "forked_only": []
        }

        all_ids = set(self.nodes.keys()) | set(other.nodes.keys())

        for node_id in all_ids:
            orig = self.nodes.get(node_id)
            fork = other.nodes.get(node_id)

            if orig and fork:
                if orig.state_hash != fork.state_hash:
                    result["changed_nodes"].append({
                        "id": node_id,
                        "original_output": orig.output,
                        "forked_output": fork.output
                    })
            elif orig and not fork:
                result["original_only"].append(node_id)
            elif fork and not orig:
                result["forked_only"].append(node_id)

        return result


# ============================================================
# v0.3 DEMO - Medical Triage as Graph VM
# ============================================================

def demo():
    """Run medical triage through the Graph VM."""
    print("=" * 70)
    print("ExecutionGraph v0.3 - Graph VM Kernel Demo")
    print("=" * 70)

    # Build the medical triage graph (as IR)
    g = ExecutionGraph()

    # Node 1: Receive patient input
    g.add_node(Node("n1_receive", "STATE", {
        "operation": "write",
        "key": "query",
        "value": "Patient has mild discomfort"
    }))

    # Node 2: LLM reasoning
    g.add_node(Node("n2_reason", "LLM", {
        "query": "${query}",
        "default_action": "diagnose",
        "default_action_input": {"symptoms": "${query}"}
    }))

    # Node 3: Tool call (diagnose)
    g.add_node(Node("n3_diagnose", "TOOL", {
        "tool": "diagnose",
        "args": {"symptoms": "mild discomfort"}
    }))

    # Node 4: Branch on result
    g.add_node(Node("n4_branch", "BRANCH", {
        "condition": "diagnose_result"
    }))

    # Node 5a: Normal outcome
    g.add_node(Node("n5a_normal", "STATE", {
        "operation": "write",
        "key": "outcome",
        "value": "REST AND FLUIDS"
    }))

    # Node 5b: Critical outcome
    g.add_node(Node("n5b_critical", "STATE", {
        "operation": "write",
        "key": "outcome",
        "value": "EMERGENCY PROTOCOL: CALL 911"
    }))

    # Terminal
    g.add_node(Node("n6_terminal", "TERMINAL", {
        "operation": "read",
        "key": "outcome"
    }))

    # Link the CFG
    g.set_root("n1_receive")
    g.link("n1_receive", "n2_reason")
    g.link("n2_reason", "n3_diagnose")
    g.link("n3_diagnose", "n4_branch")

    # Branch: n4 → n5a (normal) or n5b (critical)
    g.link_branch("n4_branch", "n5a_normal", "n5b_critical")

    # Both branches lead to terminal
    g.link("n5a_normal", "n6_terminal")
    g.link("n5b_critical", "n6_terminal")

    # Set branch resolution function
    def resolve_diagnosis(result, ctx):
        # Check tool result from n3_diagnose
        tool_result = ctx.get_memory("diagnose_result")
        if tool_result == "CASE_CRITICAL":
            return "n5b_critical"
        return "n5a_normal"

    g.set_branch_fn("n4_branch", resolve_diagnosis)

    # Add tool
    def diagnose(symptoms):
        if "mild" in symptoms.lower():
            return "CASE_NORMAL"
        return "CASE_CRITICAL"

    # Override n3 tool spec to capture symptoms
    g.nodes["n3_diagnose"].spec = {
        "tool": "diagnose",
        "args": {"symptoms": "${query}"}
    }

    print(f"\n[1] Graph built: {len(g.nodes)} nodes, {g.root} as root")

    # Create engine and context
    engine = ExecutionEngine()
    ctx = ExecutionContext(g)
    ctx.tool_registry = {"diagnose": diagnose}
    ctx.llm_handler = lambda spec, c: {
        "action": "diagnose",
        "action_input": {"symptoms": c.get_memory("query")}
    }

    # For LLM nodes, also set memory with tool call result
    def wrapped_tool_dispatch(spec, c):
        tool_name = spec.get("tool")
        args = {k: c.get_memory(v.lstrip("${").rstrip("}")) if isinstance(v, str) and v.startswith("${") else v
                for k, v in spec.get("args", {}).items()}
        result = c.tool_registry[tool_name](**args)
        c.set_memory("diagnose_result", result)
        return result

    # Override tool dispatch for demo
    original_step_tool = engine._step_tool
    def demo_tool_step(node, c):
        if node.spec.get("tool") == "diagnose":
            return demo_tool_step_impl(node, c)
        return original_step_tool(node, c)

    def demo_tool_step_impl(node, c):
        query = c.get_memory("query")
        result = diagnose(query)
        c.set_memory("diagnose_result", result)
        node.output = result
        c.accumulator = result
        return result

    engine._step_tool = demo_tool_step_impl

    # Execute original path
    print(f"\n[2] Executing original path...")
    ctx1 = g.run(engine, ExecutionContext(g))

    # Fix context for second run
    ctx1.tool_registry = {"diagnose": diagnose}
    ctx1.llm_handler = ctx.llm_handler
    ctx1.graph = g

    print(f"    Trace: {' → '.join([t['node'] for t in ctx1.trace])}")
    print(f"    Outcome: {g.nodes['n6_terminal'].output or ctx1.get_memory('outcome')}")

    # Fork at n4 with critical result
    print(f"\n[3] Forking at n4_diagnose: CASE_NORMAL → CASE_CRITICAL")

    # The fork happens at n4_branch - we patch the memory
    forked_g = g.fork("n4_branch", {
        "branch_fn": lambda result, ctx: "n5b_critical"  # Force critical path
    })

    # Execute forked path
    ctx2 = ExecutionContext(forked_g)
    ctx2.tool_registry = {"diagnose": diagnose}
    ctx2.llm_handler = ctx.llm_handler
    ctx2.graph = forked_g

    ctx2 = forked_g.run(engine, ctx2)

    print(f"    Trace: {' → '.join([t['node'] for t in ctx2.trace])}")
    outcome_forked = forked_g.nodes['n5b_critical'].output or ctx2.get_memory('outcome')
    print(f"    Outcome: {outcome_forked}")

    # Diff
    diff = g.diff(forked_g)
    print(f"\n[4] Diff: {len(diff['changed_nodes'])} node(s) changed")

    print("\n" + "=" * 70)
    print("RESULT:")
    print(f"  Original:  REST AND FLUIDS")
    print(f"  Forked:   {outcome_forked}")
    print("=" * 70)


if __name__ == "__main__":
    demo()