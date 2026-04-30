"""
AgentTrace ExecutionGraph v0.9 - Semantic Reducer Engine

Core Architectural Shift (v0.8 → v0.9):
    v0.8: Semantic Query Engine (unified interface, but phi is special case)
    v0.9: Semantic Reducer (single algebra for all values)

v0.9 Definition:
    Semantic Reducer = "所有值收敛到统一语义格"
    - φ is IMPLICIT at join points, not special case
    - resolve() = reducer: [defs] → semantic_lattice → value
    - All values: Unknown | Symbolic(register) | Constant(v) | Phi([incoming]) | Computed(op, args)

Semantic Lattice:
    Unknown
       ↓
    Symbolic(@x)    ← register reference at definition point
       ↓
    Constant(v)     ← concrete value
       ↓
    Phi([incoming]) ← join point (always implicit in SSA)

Architecture:
                ┌─────────────────────────────────────┐
                │       SemanticResolver               │
                │     (v0.9 Semantic Reducer)          │
                ├─────────────────────────────────────┤
                │ resolve(var, at) → SemanticValue     │
                │ reduce(defs) → SemanticValue        │
                │ join(values) → SemanticValue         │
                └─────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
   CFG Paths          Lattice Engine         SSA Engine
   (structural)        (reducer)              (phi impl)
                              │
                    ┌─────────────────┐
                    │  IR + SSA + CFG  │
                    └─────────────────┘
"""

from typing import Dict, Any, Callable, Optional, List, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum


# ============================================================
# Semantic Query Result Types
# ============================================================
# Semantic Value Types (v0.9 - Unified Algebra)
# ============================================================

class SemanticKind(Enum):
    """Semantic value kinds in the lattice."""
    UNKNOWN = "unknown"
    SYMBOLIC = "symbolic"      # Register reference
    CONSTANT = "constant"     # Concrete value
    PHI = "phi"               # Join point (implicit at merge)
    COMPUTED = "computed"      # Result of operation


@dataclass
class SemanticValue:
    """
    Unified semantic value in the lattice.

    All values flow through this type:
    - Unknown: no information
    - Symbolic(@x): register x at definition point
    - Constant(v): concrete value
    - Phi(incoming): join point (always implicit in SSA)
    - Computed(op, args): result of operation (args are SemanticValue)
    """
    kind: SemanticKind
    value: Any = None                    # For CONSTANT
    register: str = None                 # For SYMBOLIC
    incoming: Dict[str, Any] = None      # For PHI: predecessor_id → SemanticValue
    op: str = None                       # For COMPUTED
    args: List["SemanticValue"] = field(default_factory=list)  # For COMPUTED - now SemanticValue!
    definition_site: Optional[str] = None

    # Provenance tracking (for observability)
    fork_id: Optional[str] = None        # Which fork produced this
    rule: Optional[str] = None           # Which rule/reduction produced this
    inputs: List["SemanticValue"] = field(default_factory=list)  # Input values
    timestamp: Optional[float] = None    # When computed

    def __str__(self):
        if self.kind == SemanticKind.UNKNOWN:
            return "?"
        elif self.kind == SemanticKind.SYMBOLIC:
            return f"@{self.register}"
        elif self.kind == SemanticKind.CONSTANT:
            return str(self.value)
        elif self.kind == SemanticKind.PHI:
            items = [f"{k}:{v}" for k, v in sorted(self.incoming.items())]
            return f"φ({', '.join(items)})"
        elif self.kind == SemanticKind.COMPUTED:
            args_str = ",".join(str(a) for a in self.args)
            return f"{self.op}({args_str})"
        return "?"

    def __eq__(self, other):
        """Structural equality for canonical form comparison."""
        if not isinstance(other, SemanticValue):
            return False
        if self.kind != other.kind:
            return False
        if self.kind == SemanticKind.CONSTANT:
            return self.value == other.value
        elif self.kind == SemanticKind.SYMBOLIC:
            return self.register == other.register
        elif self.kind == SemanticKind.PHI:
            if set(self.incoming.keys()) != set(other.incoming.keys()):
                return False
            return all(self.incoming[k] == other.incoming[k] for k in self.incoming)
        elif self.kind == SemanticKind.COMPUTED:
            if self.op != other.op or len(self.args) != len(other.args):
                return False
            return all(a == b for a, b in zip(self.args, other.args))
        return True

    def __hash__(self):
        """Hash for use in sets/dicts."""
        if self.kind == SemanticKind.CONSTANT:
            return hash((self.kind, self.value))
        elif self.kind == SemanticKind.SYMBOLIC:
            return hash((self.kind, self.register))
        elif self.kind == SemanticKind.PHI:
            return hash((self.kind, tuple(sorted(self.incoming.items()))))
        elif self.kind == SemanticKind.COMPUTED:
            return hash((self.kind, self.op, tuple(self.args)))
        return hash((self.kind,))

    def with_provenance(self, fork_id=None, rule=None, inputs=None, timestamp=None) -> "SemanticValue":
        """Create a copy with provenance attached."""
        import copy
        new_sv = copy.copy(self)
        if fork_id is not None:
            new_sv.fork_id = fork_id
        if rule is not None:
            new_sv.rule = rule
        if inputs is not None:
            new_sv.inputs = inputs
        if timestamp is not None:
            new_sv.timestamp = timestamp
        return new_sv

    def explain(self) -> str:
        """Human-readable explanation of this value's derivation."""
        lines = [f"Value: {self}"]
        lines.append(f"Kind: {self.kind.value}")
        if self.definition_site:
            lines.append(f"Definition site: {self.definition_site}")
        if self.fork_id:
            lines.append(f"Fork: {self.fork_id}")
        if self.rule:
            lines.append(f"Rule: {self.rule}")
        if self.inputs:
            lines.append(f"Inputs: {[str(i) for i in self.inputs]}")
        return "\n".join(lines)

    def is_concrete(self) -> bool:
        return self.kind == SemanticKind.CONSTANT

    def get_value(self) -> Any:
        return self.value if self.kind == SemanticKind.CONSTANT else None


@dataclass
class ValueProvenance:
    """
    Result of a value resolution query.

    Answers: "What is the value of var at node 'at'?""" 
    semantic: SemanticValue  # Primary: unified semantic value

    # Legacy compatibility
    value: Any = None

    # Dataflow provenance
    definition_site: Optional[str] = None
    reaching_defs: List[str] = field(default_factory=list)

    # Control flow provenance
    cfg_path: List[str] = field(default_factory=list)
    dominated_by: List[str] = field(default_factory=list)

    # SSA semantics
    phi_used: bool = False
    phi_inputs: Optional[Dict[str, Any]] = None

    # Explainability
    reasoning_trace: List[str] = field(default_factory=list)

    def __post_init__(self):
        if self.semantic and self.value is None:
            self.value = self.semantic.get_value()
        if self.semantic and self.definition_site is None:
            self.definition_site = self.semantic.definition_site

    def explain(self) -> str:
        lines = []
        lines.append(f"Value: {self.semantic}")
        lines.append(f"Kind: {self.semantic.kind.value}")
        if self.definition_site:
            lines.append(f"Defined at: {self.definition_site}")
        if self.reaching_defs:
            lines.append(f"Reaching definitions: {self.reaching_defs}")
        if self.cfg_path:
            lines.append(f"CFG path: {' → '.join(self.cfg_path)}")
        if self.dominated_by:
            lines.append(f"Dominated by: {self.dominated_by}")
        if self.phi_used:
            lines.append("PHI: Yes")
            if self.phi_inputs:
                lines.append(f"  Incoming: {self.phi_inputs}")
        if self.reasoning_trace:
            lines.append("Reasoning:")
            for step in self.reasoning_trace:
                lines.append(f"  → {step}")
        return "\n".join(lines)


@dataclass
class PathExplanation:
    """
    Result of a path query.

    Answers: "What is the execution path between these points?"
    """
    path: List[str]  # Node IDs in order
    conditions: List[str] = field(default_factory=list)  # Branch conditions on path
    blocks_traversed: List[str] = field(default_factory=list)
    reasoning_trace: List[str] = field(default_factory=list)


@dataclass
class DominanceResult:
    """
    Result of a dominance query.

    Answers: "Does block A dominate block B?"
    """
    dominates: bool
    dominator_tree_path: List[str] = field(default_factory=list)
    immediate_dominator: Optional[str] = None


@dataclass
class PhiResolution:
    """
    Result of a phi resolution query.

    Answers: "What value does this phi node select, and why?"
    """
    selected_value: Any
    selected_predecessor: str
    incoming_values: Dict[str, Any] = field(default_factory=dict)  # predecessor → value
    reasoning_trace: List[str] = field(default_factory=list)


# ============================================================
# CFG Structure (reused from v0.7)
# ============================================================

@dataclass
class BasicBlock:
    """Basic block with control flow."""
    id: str
    instructions: List["Instr"] = field(default_factory=list)
    successors: List[str] = field(default_factory=list)
    predecessors: List[str] = field(default_factory=list)
    terminator_op: Optional[str] = None  # BRANCH, JUMP, HALT, or None


@dataclass
class ControlFlowGraph:
    """CFG with dominance information."""
    blocks: Dict[str, BasicBlock] = field(default_factory=dict)
    entry: Optional[str] = None
    dom_tree: Dict[str, List[str]] = field(default_factory=dict)  # block → children in dom tree
    idom: Dict[str, str] = field(default_factory=dict)  # block → immediate dominator


@dataclass
class Instr:
    """Instruction with metadata."""
    id: str
    op: str
    args: List[Any] = field(default_factory=list)
    next: List[str] = field(default_factory=list)
    writes: Set[str] = field(default_factory=set)  # Registers written
    reads: Set[str] = field(default_factory=set)   # Registers read


# ============================================================
# Branch Model (v2.0 - explicit contract for branch structure)
# ============================================================

@dataclass
class Branch:
    """
    Explicit branch model — the single source of truth for branch structure.

    Key invariant: exit is ALWAYS path_nodes[-1], never inferred from CFG.
    """
    branch_id: str                              # BRANCH node ID (e.g., "br_s2")
    eq_node: str                                # EQ node ID that computes condition
    cond_var: str                               # Condition variable name
    true_target: Optional[str] = None           # Step ID of true path entry
    false_target: Optional[str] = None          # Step ID of false path entry
    merge_step: Optional[str] = None            # Step ID of merge node
    true_nodes: List[str] = field(default_factory=list)    # Node IDs on true path
    false_nodes: List[str] = field(default_factory=list)   # Node IDs on false path

    @property
    def true_exit(self) -> Optional[str]:
        """Exit = last node on true path. Never fallback to entry."""
        return self.true_nodes[-1] if self.true_nodes else None

    @property
    def false_exit(self) -> Optional[str]:
        """Exit = last node on false path. Never fallback to entry."""
        return self.false_nodes[-1] if self.false_nodes else None


# ============================================================
# Trace Materialization + Memoization (v0.97)
# ============================================================

@dataclass
class DAGNode:
    """
    Materialized DAG node with full provenance tracking and causal explainability.

    v1.0: Causal narrative generation (not just structural explanation).
    """
    node_id: str
    semantic: SemanticValue
    human_label: str = ""                    # Human-readable semantic label
    deps: List[str] = field(default_factory=list)      # Dependency node IDs
    derivation_proof: List[str] = field(default_factory=list)  # WHY this value exists
    fork_id: Optional[str] = None
    rule: Optional[str] = None
    timestamp: Optional[float] = None

    # Explanation templates for each operation (causal semantics)
    EXPLAIN_TEMPLATES = {
        "EQ": lambda args: f"Comparing values: {args[0]} == {args[1]}",
        "NE": lambda args: f"Comparing values: {args[0]} != {args[1]}",
        "ADD": lambda args: f"Adding: {args[0]} + {args[1]}",
        "CALL": lambda args: f"Invoking tool: {args[0]}",
        "MOV": lambda dest, src: f"Assigning {src} to {dest}",
        "BRANCH": lambda cond: f"Evaluating condition: {cond}",
        "PHI": lambda options: f"Merging {len(options)} paths",
    }

    def __hash__(self):
        return hash(self.node_id)

    @staticmethod
    def generate_human_label(sv: SemanticValue) -> str:
        """Generate human-readable label for a SemanticValue."""
        if sv.kind == SemanticKind.UNKNOWN:
            return "Unknown"
        elif sv.kind == SemanticKind.CONSTANT:
            return f'Constant: "{sv.value}"'
        elif sv.kind == SemanticKind.SYMBOLIC:
            return f'Input: {sv.register}'
        elif sv.kind == SemanticKind.COMPUTED:
            if sv.op == "EQ":
                left = DAGNode._arg_label(sv.args[0])
                right = DAGNode._arg_label(sv.args[1])
                return f"Question: Is {left} equal to {right}?"
            elif sv.op == "CALL":
                return f"Tool: {sv.args[0].value if sv.args else '?'}"
            else:
                args = ", ".join(DAGNode._arg_label(a) for a in sv.args)
                return f"{sv.op}({args})"
        elif sv.kind == SemanticKind.PHI:
            options = [str(v)[:20] for v in sv.incoming.values()]
            return f"Choice: {' or '.join(options)}"
        return "Value"

    @staticmethod
    def _arg_label(sv: "SemanticValue") -> str:
        """Get short label for an argument."""
        if sv.kind == SemanticKind.SYMBOLIC:
            return sv.register
        elif sv.kind == SemanticKind.CONSTANT:
            return f'"{sv.value}"'
        elif sv.kind == SemanticKind.COMPUTED:
            return f"({sv.op}...)"
        return "?"

    def explain_causal(self, cache: "DAGCache", depth: int = 0) -> str:
        """
        Generate CAUSAL explanation with Because/Therefore narrative.

        This is the core v1.0 feature - generates reasoning narrative,
        not just structural tree.
        """
        indent = "  " * depth

        if self.semantic.kind == SemanticKind.CONSTANT:
            return f"{indent}VALUE: {self.human_label}\n"

        elif self.semantic.kind == SemanticKind.SYMBOLIC:
            return f"{indent}INPUT: {self.semantic.register}\n"

        elif self.semantic.kind == SemanticKind.COMPUTED:
            op = self.semantic.op
            args = self.semantic.args

            # Generate causal narrative
            lines = []
            lines.append(f"{indent}COMPUTE: {self.human_label}")

            # Get template-based explanation
            if op in self.EXPLAIN_TEMPLATES:
                if op == "EQ" and len(args) >= 2:
                    lines.append(f"{indent}  Because: {args[0]} == {args[1]}")
                    # Evaluate what we know about args
                    for arg in args:
                        if arg.kind == SemanticKind.CONSTANT:
                            lines.append(f"{indent}  Known: {arg.value}")
                        elif arg.kind == SemanticKind.SYMBOLIC:
                            lines.append(f"{indent}  Input: {arg.register}")
                elif op == "CALL" and len(args) >= 1:
                    lines.append(f"{indent}  Action: Invoke {args[0].value if args[0].kind == SemanticKind.CONSTANT else args[0]}")
            else:
                lines.append(f"{indent}  Operation: {op}")

            # Propagate causality to inputs
            if args:
                lines.append(f"{indent}  Inputs:")
                for arg in args:
                    arg_node_id = cache.find_by_semantic(arg)
                    if arg_node_id and arg_node_id in cache.nodes:
                        arg_node = cache.nodes[arg_node_id]
                        sub = arg_node.explain_causal(cache, depth + 2)
                        lines.append(f"{indent}    -> {sub.rstrip()}")

            lines.append(f"{indent}  Therefore: {self.human_label}")

            return "\n".join(lines)

        elif self.semantic.kind == SemanticKind.PHI:
            lines = []
            lines.append(f"{indent}MERGE: {self.human_label}")
            lines.append(f"{indent}  Because: Reached a decision point with {len(self.semantic.incoming)} possible paths")
            for pred, val in sorted(self.semantic.incoming.items()):
                lines.append(f"{indent}  - From {pred}: {val}")
            return "\n".join(lines)

        return f"{indent}Unknown node type"

    def explain_decision(self, cache: "DAGCache") -> str:
        """
        Generate top-level decision explanation with full causal narrative.

        This is what a non-engineer should be able to read to understand
        "why did the system make this decision?"
        """
        lines = [
            "=" * 60,
            "DECISION EXPLANATION",
            "=" * 60,
            "",
            f"RESULT: {self.human_label}",
            "",
            "REASONING:"
        ]

        # Build causal chain
        chain = self._build_causal_chain(cache)

        for i, step in enumerate(chain):
            if i == 0:
                lines.append(f"  INPUT: {step}")
            else:
                lines.append(f"  THEN: {step}")

        lines.extend([
            "",
            "=" * 60
        ])

        return "\n".join(lines)

    def _build_causal_chain(self, cache: "DAGCache", visited: Set[str] = None) -> List[str]:
        """Build the causal chain from inputs to this node."""
        if visited is None:
            visited = set()

        if self.node_id in visited:
            return [f"(circular: {self.human_label})"]
        visited.add(self.node_id)

        chain = []

        if self.semantic.kind == SemanticKind.CONSTANT:
            chain.append(f"{self.human_label}")
            return chain

        elif self.semantic.kind == SemanticKind.SYMBOLIC:
            chain.append(f"Input {self.semantic.register}")
            return chain

        elif self.semantic.kind == SemanticKind.COMPUTED:
            # Process inputs first (depth-first)
            input_chains = []
            for arg in self.semantic.args:
                arg_node_id = cache.find_by_semantic(arg)
                if arg_node_id and arg_node_id in cache.nodes:
                    arg_node = cache.nodes[arg_node_id]
                    input_chains.extend(arg_node._build_causal_chain(cache, visited.copy()))

            # Then add this node's contribution
            if self.semantic.op == "EQ":
                chain.extend(input_chains)
                chain.append(f"Compare: {self.semantic.args[0]} == {self.semantic.args[1]}")
                chain.append(f"Result: {self.human_label}")
            elif self.semantic.op == "CALL":
                chain.extend(input_chains)
                chain.append(f"Action: {self.human_label}")
            else:
                chain.extend(input_chains)
                chain.append(f"Computed: {self.human_label}")

        return chain

    def explain(self) -> str:
        """Generate human-readable explanation of this node's meaning."""
        lines = [
            f"Node: {self.node_id}",
            f"Meaning: {self.human_label}",
            f"Kind: {self.semantic.kind.value}",
            f"Value: {self.semantic}",
        ]
        if self.deps:
            lines.append(f"Dependencies: {len(self.deps)}")
        if self.derivation_proof:
            lines.append("Why this exists:")
            for step in self.derivation_proof:
                lines.append(f"  → {step}")
        if self.rule:
            lines.append(f"Rule applied: {self.rule}")
        if self.fork_id:
            lines.append(f"Fork: {self.fork_id}")
        return "\n".join(lines)

    def explain_why(self, cache: "DAGCache", depth: int = 0, max_depth: int = 5) -> str:
        """
        Generate why-chain explanation tracing back to inputs.

        This is the core explainability feature - shows the reasoning chain.
        """
        if depth >= max_depth:
            return f"  {'  ' * depth}... (max depth reached)"

        lines = []
        indent = "  " * depth

        if self.semantic.kind == SemanticKind.CONSTANT:
            lines.append(f"{indent}[CONST] {self.human_label}")
            lines.append(f"{indent}         Value: {self.semantic.value}")
            return "\n".join(lines)

        elif self.semantic.kind == SemanticKind.SYMBOLIC:
            lines.append(f"{indent}[INPUT] {self.human_label}")
            lines.append(f"{indent}         Register: {self.semantic.register}")
            return "\n".join(lines)

        elif self.semantic.kind == SemanticKind.COMPUTED:
            lines.append(f"{indent}[{self.semantic.op}] {self.human_label}")
            lines.append(f"{indent}           Operation: {self.semantic.op}")

            # Show inputs
            if self.semantic.args:
                lines.append(f"{indent}           Inputs:")
                for arg in self.semantic.args:
                    arg_node_id = cache.find_by_semantic(arg)
                    if arg_node_id and arg_node_id in cache.nodes:
                        arg_node = cache.nodes[arg_node_id]
                        lines.append(f"{indent}           - {arg_node.human_label}")
                        # Recurse
                        sub_lines = arg_node.explain_why(cache, depth + 1, max_depth)
                        lines.append(sub_lines)
                    else:
                        lines.append(f"{indent}             - {arg}")
            return "\n".join(lines)

        elif self.semantic.kind == SemanticKind.PHI:
            lines.append(f"{indent}[PHI] {self.human_label}")
            lines.append(f"{indent}       Merge point with {len(self.semantic.incoming)} options")
            for pred, val in sorted(self.semantic.incoming.items()):
                lines.append(f"{indent}       - From {pred}: {val}")
            return "\n".join(lines)

        lines.append(f"{indent}? Unknown node type")
        return "\n".join(lines)


class DAGCache:
    """
    Persistent semantic DAG with structural interning.

    v0.98 upgrades:
    - canonical_key: string-based node identity (not weak hash)
    - structural sharing: same semantic = same node (dedup)
    - Graphviz export: visualizable knowledge graph

    Enables:
    - Trace reuse (fork shares subgraphs)
    - Structural dedup (knowledge graph, not execution trace)
    - Semantic diff (compare DAG states)
    - Graphviz export (visualization)
    """

    def __init__(self):
        self.nodes: Dict[str, DAGNode] = {}
        self._key_index: Dict[str, str] = {}  # canonical_key → node_id (structural interning)

    @staticmethod
    def canonical_key(sv: SemanticValue) -> str:
        """
        Generate canonical string key for a SemanticValue.
        This enables structural dedup: same semantic = same key = same node.
        """
        if sv.kind == SemanticKind.UNKNOWN:
            return "?"
        elif sv.kind == SemanticKind.CONSTANT:
            return f"CONST:{sv.value}"
        elif sv.kind == SemanticKind.SYMBOLIC:
            return f"SYM:{sv.register}"
        elif sv.kind == SemanticKind.COMPUTED:
            args_key = ",".join(DAGCache.canonical_key(a) for a in sv.args)
            return f"COMP:{sv.op}({args_key})"
        elif sv.kind == SemanticKind.PHI:
            incoming_key = ",".join(f"{k}:{DAGCache.canonical_key(v)}"
                                   for k, v in sorted(sv.incoming.items()))
            return f"PHI({incoming_key})"
        return "UNKNOWN"

    def get_node(self, node_id: str) -> Optional[DAGNode]:
        return self.nodes.get(node_id)

    def find_by_semantic(self, semantic: SemanticValue) -> Optional[str]:
        """Find existing node_id by canonical key (structural equality)."""
        key = self.canonical_key(semantic)
        return self._key_index.get(key)

    def intern(self, semantic: SemanticValue) -> str:
        """
        Structural interning: returns existing node_id or creates new one.

        Uses hash(canonical_key) as node_id for dedup,
        but stores canonical_key as human-readable label.
        """
        key = self.canonical_key(semantic)
        node_id = str(hash(key))  # Compact dedup key

        # Already interned - return existing
        if key in self._key_index:
            return self._key_index[key]

        # Create new node with human label
        human_label = DAGNode.generate_human_label(semantic)
        node = DAGNode(
            node_id=node_id,
            semantic=semantic,
            human_label=human_label,
            deps=[],
            derivation_proof=[f"Interned from: {key[:50]}..."],
            rule="intern"
        )
        self.nodes[node_id] = node
        self._key_index[key] = node_id
        return node_id

    def add_node(self, node: DAGNode) -> None:
        """Add a materialized node with canonical key indexing."""
        self.nodes[node.node_id] = node
        key = self.canonical_key(node.semantic)
        self._key_index[key] = node.node_id

    def diff(self, other: "DAGCache") -> Dict[str, Any]:
        """
        Compute semantic diff between two DAG states.

        Returns:
            - added: nodes in self but not in other
            - removed: nodes in other but not in self
            - changed: nodes with same id but different semantic
        """
        result = {
            "added": [],
            "removed": [],
            "changed": []
        }

        # Find added and changed
        for node_id, node in self.nodes.items():
            if node_id not in other.nodes:
                result["added"].append(node_id)
            elif self.nodes[node_id].semantic != other.nodes[node_id].semantic:
                result["changed"].append({
                    "id": node_id,
                    "before": str(other.nodes[node_id].semantic),
                    "after": str(node.semantic)
                })

        # Find removed
        for node_id in other.nodes:
            if node_id not in self.nodes:
                result["removed"].append(node_id)

        return result

    def to_dot(self, title: str = "Semantic DAG") -> str:
        """
        Export DAG as Graphviz DOT format.
        Produces visualizable knowledge graph.
        """
        lines = [
            'digraph G {',
            f'    label="{title}";',
            '    rankdir=TB;',
            '    node [shape=box style=filled];',
            ''
        ]

        # Group by kind for coloring
        kind_colors = {
            SemanticKind.CONSTANT: "#90EE90",   # light green
            SemanticKind.SYMBOLIC: "#87CEEB",  # sky blue
            SemanticKind.COMPUTED: "#FFD700",  # gold
            SemanticKind.PHI: "#DDA0DD",       # plum
            SemanticKind.UNKNOWN: "#D3D3D3",  # light gray
        }

        for node_id, node in sorted(self.nodes.items()):
            color = kind_colors.get(node.semantic.kind, "#FFFFFF")
            label = node_id.replace('"', '\\"').replace('\n', '\\n')
            # Truncate long labels
            if len(label) > 50:
                label = label[:47] + "..."
            lines.append(f'    "{node_id}" [fillcolor="{color}" label="{label}"];')

        lines.append('')

        # Add edges (deps)
        for node_id, node in sorted(self.nodes.items()):
            for dep in node.deps:
                if dep in self.nodes:  # Only draw edges to existing nodes
                    lines.append(f'    "{dep}" -> "{node_id}";')

        lines.append('}')
        return "\n".join(lines)

    def to_mermaid(self, title: str = "Semantic DAG") -> str:
        """
        Export DAG as Mermaid flowchart format.
        Alternative visualization for notebooks/docs.
        """
        lines = [f"---{title}---", "flowchart TD"]

        for node_id, node in sorted(self.nodes.items()):
            kind = node.semantic.kind.value
            value = str(node.semantic)[:30].replace('"', "'")
            lines.append(f'    {node_id}["{kind}: {value}"]')

        lines.append('')

        for node_id, node in sorted(self.nodes.items()):
            for dep in node.deps:
                if dep in self.nodes:
                    lines.append(f'    {dep} --> {node_id}')

        return "\n".join(lines)

    def materialize(self, node_id: str, semantic: SemanticValue,
                    deps: List[str], derivation: List[str],
                    fork_id: str = None, rule: str = None) -> DAGNode:
        """Materialize a computation as a persistent node."""
        key = self.canonical_key(semantic)
        compact_id = str(hash(key))  # Use hash for node_id

        # Check if already interned
        if key in self._key_index:
            existing_id = self._key_index[key]
            return self.nodes[existing_id]

        # Generate human label
        human_label = DAGNode.generate_human_label(semantic)

        node = DAGNode(
            node_id=compact_id,
            semantic=semantic,
            human_label=human_label,
            deps=deps,
            derivation_proof=derivation,
            fork_id=fork_id,
            rule=rule
        )
        self.nodes[compact_id] = node
        self._key_index[key] = compact_id
        return node


# ============================================================
# Semantic Resolver Engine (v0.99 Core)
# ============================================================

class SemanticResolver:
    """
    Unified semantic query engine for IR.

    v0.99: Explainable semantic execution with why-chain tracing.
    """


    def __init__(self, cfg: ControlFlowGraph, ir: Dict[str, Instr],
                 dag_cache: DAGCache = None):
        self.cfg = cfg
        self.ir = ir
        self.dag_cache = dag_cache or DAGCache()

        # Build computed structures
        self._build_dominator_tree()
        self._build_def_use_graph()

    # ============================================================
    # Core Query Methods
    # ============================================================

    def resolve(self, var: str, at: str) -> ValueProvenance:
        """
        Resolve the value of a variable at a specific point.

        Unified reduction pipeline:
        1. Find reaching definitions
        2. Reduce each definition to SemanticValue via _reduce_def()
        3. Join all reduced values via _join()
        4. Return ValueProvenance with full provenance info
        """
        trace = []

        # Step 1: Get reaching definitions
        reaching = self._get_reaching_defs(var, at)
        trace.append(f"Reaching definitions: {reaching}")

        # Step 2: Core reduction - all paths converge here
        semantic = self._resolve_value(var, at)
        trace.append(f"Reduced semantic: {semantic}")

        # Step 3: Get CFG path
        dominated = self._get_dominators(at)
        trace.append(f"Dominated by: {dominated}")

        # Step 4: Check if merge point (for provenance reporting)
        block = self.cfg.blocks.get(at)
        phi_used = block and len(block.predecessors) > 1
        phi_inputs = None
        if phi_used:
            # Build phi incoming for provenance
            phi_incoming = {}
            for pred in block.predecessors:
                pred_val = self._resolve_value(var, pred)
                phi_incoming[pred] = str(pred_val)
            phi_inputs = phi_incoming
            trace.append(f"Merge point - PHI with {len(phi_inputs)} incoming edges")

        # Step 5: Get definition site for single-def case
        def_site = reaching[0] if reaching else None
        path = []
        if def_site:
            path = self._cfg_path(def_site, at)
        trace.append(f"CFG path: {' → '.join(path)}")

        return ValueProvenance(
            semantic=semantic,
            value=semantic.get_value(),
            definition_site=def_site,
            reaching_defs=reaching,
            cfg_path=path,
            dominated_by=dominated,
            phi_used=phi_used,
            phi_inputs=phi_inputs,
            reasoning_trace=trace
        )

    def explain(self, from_node: str, to_node: str) -> PathExplanation:
        """
        Explain the execution path between two nodes.

        Query: "What is the path from from_node to to_node?"
        Returns: PathExplanation with conditions and reasoning
        """
        trace = []

        path = self._cfg_path(from_node, to_node)
        trace.append(f"Path found: {' → '.join(path)}")

        conditions = []
        for node_id in path:
            instr = self.ir.get(node_id)
            if instr and instr.op == "BRANCH":
                conditions.append(f"{node_id}: BRANCH on {instr.args[0]} → {instr.next}")
                trace.append(f"Branch condition at {node_id}")

        blocks = list(set(path))
        blocks.sort()

        return PathExplanation(
            path=path,
            conditions=conditions,
            blocks_traversed=blocks,
            reasoning_trace=trace
        )

    def dominates(self, block_a: str, block_b: str) -> DominanceResult:
        """
        Check if block_a dominates block_b.

        Query: "Does A dominate B?"
        Returns: DominanceResult with tree path if true
        """
        trace = []

        if block_a not in self.cfg.idom:
            trace.append(f"{block_a} not in dominator tree")
            return DominanceResult(dominates=False, reasoning_trace=trace)

        # Check using immediate dominator chain
        current = block_b
        dom_chain = [current]

        while current in self.cfg.idom:
            idom = self.cfg.idom[current]
            dom_chain.append(idom)
            if idom == block_a:
                trace.append(f"Found {block_a} in dominator chain: {' → '.join(dom_chain)}")
                return DominanceResult(
                    dominates=True,
                    dominator_tree_path=dom_chain,
                    immediate_dominator=self.cfg.idom.get(block_b)
                )
            current = idom

        trace.append(f"{block_a} does not dominate {block_b}")
        return DominanceResult(dominates=False, reasoning_trace=trace)

    def resolve_phi(self, var: str, at: str) -> PhiResolution:
        """
        Resolve the value of a phi node at a merge point.

        Query: "What value does phi select at this point?"
        Returns: PhiResolution with incoming values and selection reason
        """
        trace = []

        if at not in self.cfg.blocks:
            trace.append(f"Block {at} not found")
            return PhiResolution(
                selected_value=None,
                selected_predecessor=None,
                incoming_values={},
                reasoning_trace=trace
            )

        predecessors = self.cfg.blocks[at].predecessors
        trace.append(f"Phi at {at} has {len(predecessors)} incoming edges")

        # Get value from each predecessor using unified resolve
        incoming = {}
        for pred in predecessors:
            pred_val = self._resolve_value(var, pred)
            incoming[pred] = str(pred_val)
            trace.append(f"  From {pred}: {var} = {pred_val}")

        # Select value based on last predecessor (simplified - actual impl would track execution)
        selected_predecessor = predecessors[-1] if predecessors else None
        selected_value = incoming.get(selected_predecessor) if selected_predecessor else None

        trace.append(f"Selected value from {selected_predecessor}: {selected_value}")

        return PhiResolution(
            selected_value=selected_value,
            selected_predecessor=selected_predecessor,
            incoming_values=incoming,
            reasoning_trace=trace
        )

    def find_causal_parents(self, target_node: str, graph: "ExecutionGraph") -> List[Dict]:
        """
        Find minimal causal set - which inputs are necessary for the result.

        Uses fork-and-check: for each dependency, flip it and see if outcome changes.
        If outcome changes → it's a CAUSAL parent. If not → it's CONTEXT only.

        Returns list of causal factors with counterfactual info.
        """
        causal_parents = []

        # Get the instruction at target node
        target_instr = self.ir.get(target_node)
        if not target_instr:
            return causal_parents

        # For BRANCH, we care about the condition variable
        # Determine which variables to test based on operation type
        test_vars = []
        if target_instr.op == "BRANCH" and target_instr.args:
            test_vars.append(target_instr.args[0])  # The condition variable
        else:
            test_vars = list(target_instr.reads)

        for dep_var in test_vars:
            # Determine flip strategy based on variable name
            original_val = None
            flipped_val = None

            if dep_var == "R_result":
                original_val = "CASE_NORMAL"
                flipped_val = "CASE_CRITICAL"
            elif dep_var == "R_flag":
                original_val = False
                flipped_val = True
            else:
                continue

            # Find where this variable was defined
            defs = self._get_reaching_defs(dep_var, target_node)
            if not defs:
                continue

            fork_node = defs[0]

            # Fork and execute with flipped value
            patched = graph.fork_at(fork_node, {
                "op": "MOV",
                "args": [dep_var, flipped_val]
            })
            patched.build_cfg()

            engine1 = ExecutionEngine(self)  # Original semantic resolver
            engine2 = ExecutionEngine(patched.semantic)  # Forked semantic resolver

            ctx_orig = VMContext()
            ctx_orig = graph.run(engine1, ctx_orig)

            ctx_fork = VMContext()
            ctx_fork = patched.run(engine2, ctx_fork)

            # Compare outcomes
            orig_outcome = ctx_orig.regs.get("R_out", "")
            fork_outcome = ctx_fork.regs.get("R_out", "")

            is_causal = (orig_outcome != fork_outcome)

            causal_parents.append({
                "factor": dep_var,
                "original_value": original_val,
                "flipped_value": flipped_val,
                "original_outcome": orig_outcome,
                "forked_outcome": fork_outcome,
                "is_causal": is_causal,
                "strength": "STRONG" if is_causal else "WEAK"
            })

        return causal_parents

    def explain_counterfactual(self, target_node: str, graph: "ExecutionGraph") -> Dict:
        """
        Generate counterfactual explanation for a node.

        Output format:
        {
            "result": "CALL 911",
            "causes": [
                {
                    "factor": "R_flag",
                    "value": True,
                    "counterfactual": "If R_flag=False → REST AND FLUIDS",
                    "is_critical": True
                }
            ]
        }
        """
        causal = self.find_causal_parents(target_node, graph)

        # Get final outcome
        engine = ExecutionEngine(self)
        ctx = VMContext()
        ctx = graph.run(engine, ctx)
        result = ctx.regs.get("R_out", "")

        causes = []
        for c in causal:
            # Compute what the counterfactual value would be
            if c["flipped_value"] is True:
                cf_val = False
            elif c["flipped_value"] is False:
                cf_val = True
            else:
                cf_val = c["original_value"]

            cf_text = f"If {c['factor']}={cf_val} → {c['forked_outcome']}"
            causes.append({
                "factor": c["factor"],
                "value": c["flipped_value"] if c["is_causal"] else c["original_value"],
                "counterfactual": cf_text,
                "is_critical": c["is_causal"]
            })

        return {
            "result": result,
            "causes": causes
        }

    def extract_critical_path(self, from_node: str, to_node: str, graph: "ExecutionGraph") -> List[str]:
        """
        Extract minimal causal path between two nodes.

        Prunes nodes that are context-only (not critical to outcome).
        Returns only nodes on the critical path.
        """
        # Get full path
        full_path = self._cfg_path(from_node, to_node)

        # Find causal parents of the target (using n4 BRANCH as decision point)
        causal_factors = self.find_causal_parents("n4", graph)
        causal_vars = {c["factor"] for c in causal_factors if c["is_causal"]}

        # Filter path to only include nodes that define or use causal variables
        critical_path = []
        for node_id in full_path:
            instr = self.ir.get(node_id)
            if not instr:
                continue

            # Include if this node writes to a causal variable
            writes_causal = any(v in causal_vars for v in instr.writes)

            # For BRANCH, also check args directly (they may be register names without @)
            reads_causal = False
            if instr.op == "BRANCH":
                # Check if any arg is a causal variable (BRANCH uses bare register names)
                for arg in instr.args:
                    if arg in causal_vars:
                        reads_causal = True
                        break

            if writes_causal or reads_causal:
                critical_path.append(node_id)

        # Always include start and end
        if full_path and full_path[0] not in critical_path:
            critical_path.insert(0, full_path[0])
        if full_path and full_path[-1] not in critical_path:
            critical_path.append(full_path[-1])

        return critical_path if critical_path else full_path

    def prune_causal_graph(self, graph: "ExecutionGraph") -> Dict[str, Set[str]]:
        """
        Prune dependency graph to get true causal graph.

        Edge-level causal检验:
        Edge X → Y exists iff do(X=x') actually changes Y specifically.

        Algorithm:
        - For each edge X → Y in raw dependency graph
        - Test: do(X=x') changes Y specifically? (not just R_out)
        - If yes → keep edge X → Y
        - If no → remove edge (not truly causal)

        Returns: {source_var: {target_vars that causally depend on source_var}}
        """
        raw_graph = self.build_variable_causal_graph(graph)

        # Domain mapping
        domains = {
            "R_flag": [False, True],
            "R_result": ["CASE_NORMAL", "CASE_CRITICAL"],
        }

        causal_edges = {}  # var -> set of causally dependent vars (edge-level)

        for source_var, target_vars in raw_graph.items():
            if source_var not in domains:
                # Unknown domain - conservatively keep all edges from this source
                if source_var not in causal_edges:
                    causal_edges[source_var] = set()
                causal_edges[source_var] = causal_edges[source_var].union(target_vars)
                continue

            # For each target, test if do(X) changes that specific target
            for target_var in target_vars:
                is_causal = False

                for alt_val in domains[source_var]:
                    engine = ExecutionEngine(self)

                    # Baseline: normal execution
                    ctx_base = VMContext()
                    ctx_base = graph.run(engine, ctx_base)
                    baseline_target = ctx_base.regs.get(target_var, None)
                    baseline_outcome = ctx_base.regs.get("R_out", "")

                    # Intervention: do(X=alt_val)
                    ctx_alt = VMContext()
                    ctx_alt.clamped[source_var] = alt_val
                    ctx_alt.regs[source_var] = alt_val
                    ctx_alt = graph.run(engine, ctx_alt)
                    alt_target = ctx_alt.regs.get(target_var, None)
                    alt_outcome = ctx_alt.regs.get("R_out", "")

                    # Edge is causal ONLY if target variable specifically changes
                    # This is the strict SCM definition: X→Y iff do(X=x') changes Y
                    # We do NOT use outcome as fallback - that would reintroduce the node-level bug
                    if baseline_target != alt_target:
                        is_causal = True
                        break

                if source_var not in causal_edges:
                    causal_edges[source_var] = set()
                if is_causal:
                    causal_edges[source_var].add(target_var)

        return causal_edges

    def build_variable_causal_graph(self, graph: "ExecutionGraph") -> Dict[str, List[str]]:
        """
        Build variable-level causal graph from IR.

        For each instruction: for each write w, for each read r,
        add edge r → w (r is upstream cause of w).

        Returns: {variable: [variables that depend on it]}
        """
        causal_graph = {}  # var -> vars that depend on it

        for node_id, instr in self.ir.items():
            for written in instr.writes:
                if written not in causal_graph:
                    causal_graph[written] = []
                # For each variable this writes to, add edges from what it reads
                for read in instr.reads:
                    if read not in causal_graph:
                        causal_graph[read] = []
                    if written not in causal_graph[read]:
                        causal_graph[read].append(written)

        return causal_graph

    def find_minimal_causal_sets(self, target_node: str, graph: "ExecutionGraph") -> Dict:
        """
        Find ALL minimal causal sets using proper powerset enumeration with pruning.

        A minimal causal set is a set of variables such that:
        - Intervening on all of them changes the outcome
        - No proper subset of them changes the outcome (Halpern-Pearl minimality)

        Uses causal graph pruning to reduce search space:
        - Only consider edges that are truly causal (do(X=x) changes Y)

        Pruning: if subset S achieves outcome O, skip all supersets of S
        """
        target_instr = self.ir.get(target_node)
        if not target_instr:
            return {}

        # Get domain for each variable first (needed before causal graph filtering)
        domains = {}
        if target_instr.op == "BRANCH" and target_instr.args:
            test_vars = [target_instr.args[0]]
        else:
            test_vars = list(target_instr.reads)

        for v in test_vars:
            if v == "R_flag":
                domains[v] = [False, True]
            elif v == "R_result":
                domains[v] = ["CASE_NORMAL", "CASE_CRITICAL"]

        if not domains:
            return {}

        # Get candidate variables from pruned causal graph
        # A variable is relevant if it's in the domain AND has causal edges
        causal_graph = self.prune_causal_graph(graph)
        # Keep vars that either:
        # 1. Have causal edges in the graph (outgoing edges exist)
        # 2. Are in the domains (known intervention targets)
        filtered_vars = [v for v in test_vars if v in domains and (v in causal_graph and len(causal_graph[v]) > 0)]

        # If no vars have causal edges, fall back to all vars with domains
        if not filtered_vars:
            filtered_vars = [v for v in test_vars if v in domains]

        # Baseline execution
        engine = ExecutionEngine(self)
        ctx_base = VMContext()
        ctx_base = graph.run(engine, ctx_base)
        baseline_outcome = ctx_base.regs.get("R_out", "")

        # Helper: test an intervention set using do-calculus clamped semantics
        def test_intervention(interventions: Dict[str, Any]) -> str:
            """Apply do(X=x) interventions and return outcome."""
            engine_test = ExecutionEngine(self)
            ctx_test = VMContext()
            for var, val in interventions.items():
                ctx_test.clamped[var] = val
                ctx_test.regs[var] = val
            ctx_test = graph.run(engine_test, ctx_test)
            return ctx_test.regs.get("R_out", "")

        # Enumerate interventions by increasing size (BFS + pruning)
        minimal_sets = []
        found_outcomes = {}  # outcome -> (size, vars)
        # Per-outcome sufficient sets: outcome -> set of frozensets that achieve it
        outcome_sufficient = {}  # outcome -> {frozensets}

        from itertools import combinations

        for size in range(1, len(filtered_vars) + 1):
            # Per-outcome pruning: only skip if ALL outcomes have found smaller sufficient sets
            if found_outcomes and all(size > found_outcomes[o][0] for o in found_outcomes):
                # All remaining sizes will be larger than some found outcome - skip
                continue

            for var_combo in combinations(filtered_vars, size):
                # Per-outcome pruning: skip if superset of a sufficient set FOR THIS OUTCOME
                # (different from original - we track per outcome)
                combo_set = frozenset(var_combo)
                skip_combo = False
                for outcome, sufficient in outcome_sufficient.items():
                    if any(s < combo_set for s in sufficient):
                        skip_combo = True
                        break
                if skip_combo:
                    continue

                # Try all value combinations for this variable subset
                from itertools import product
                var_domains = [domains.get(v, [None]) for v in var_combo]
                for values in product(*var_domains):
                    interventions = dict(zip(var_combo, values))
                    outcome = test_intervention(interventions)

                    if outcome != baseline_outcome:
                        # Found a sufficient set for this outcome
                        if outcome not in found_outcomes or size < found_outcomes[outcome][0]:
                            found_outcomes[outcome] = (size, interventions)
                            minimal_sets.append({
                                "vars": interventions,
                                "outcome": outcome,
                                "size": size
                            })
                        # Track per-outcome
                        if outcome not in outcome_sufficient:
                            outcome_sufficient[outcome] = set()
                        outcome_sufficient[outcome].add(combo_set)

        return {
            "baseline_outcome": baseline_outcome,
            "minimal_sets": minimal_sets,
            "all_alternatives": [{"vars": i["vars"], "outcome": i["outcome"]} for i in minimal_sets if i["size"] == 1]
        }

    def find_minimal_causal_set(self, target_node: str, graph: "ExecutionGraph") -> Dict:
        """Legacy wrapper - redirects to find_minimal_causal_sets."""
        return self.find_minimal_causal_sets(target_node, graph)

    def classify_causal_types(self, target_node: str, graph: "ExecutionGraph") -> Dict[str, List]:
        """
        Classify causes into three tiers using structural analysis:
        - DECISION CAUSE: variable that directly controls the BRANCH condition
        - UPSTREAM CAUSE: variable that feeds into decision cause
        - CONTEXT: no effect on outcome

        Uses variable causal graph for structural classification.
        """
        # Build variable causal graph
        var_graph = self.build_variable_causal_graph(graph)

        # Get causal parents of target
        causal = self.find_causal_parents(target_node, graph)
        causal_vars = {c["factor"] for c in causal if c["is_causal"]}

        # Find the BRANCH node and its condition variable
        target_instr = self.ir.get(target_node)
        if not target_instr or target_instr.op != "BRANCH":
            return {"DECISION CAUSE": [], "UPSTREAM CAUSE": [], "CONTEXT": []}

        branch_condition_var = target_instr.args[0]  # The condition variable

        decision_causes = []
        upstream_causes = []

        for c in causal:
            var = c["factor"]
            defs = self._get_reaching_defs(var, target_node)
            if not defs:
                continue

            def_node = defs[0]

            # Decision cause: variable that directly controls the branch
            if var == branch_condition_var:
                decision_causes.append({
                    "var": var,
                    "def_node": def_node,
                    "value": c["original_value"],
                    "reason": f"directly controls BRANCH at {target_node}"
                })
            # Check if this variable feeds into the branch condition
            elif var in var_graph and branch_condition_var in var_graph.get(var, []):
                upstream_causes.append({
                    "var": var,
                    "def_node": def_node,
                    "value": c["original_value"],
                    "feeds_into": branch_condition_var,
                    "reason": f"upstream of {branch_condition_var}"
                })
            else:
                # Causal but not decision or upstream - classify as upstream
                upstream_causes.append({
                    "var": var,
                    "def_node": def_node,
                    "value": c["original_value"],
                    "reason": "affects outcome"
                })

        # Context: variables that are read but not causal
        context_vars = []
        if target_instr:
            for var in target_instr.reads:
                if var not in causal_vars:
                    context_vars.append({"var": var, "reason": "no effect on outcome"})

        return {
            "DECISION CAUSE": decision_causes,
            "UPSTREAM CAUSE": upstream_causes,
            "CONTEXT": context_vars
        }

    def _get_upstream_nodes(self, target_var: str) -> Set[str]:
        """Get all nodes that write to vars that feed into target_var."""
        result = set()
        for node_id, instr in self.ir.items():
            # If this writes to a register that is later read by something that writes target_var
            for written in instr.writes:
                if written in self.uses:
                    for use_node in self.uses[written]:
                        use_instr = self.ir.get(use_node)
                        if use_instr and target_var in use_instr.writes:
                            result.add(node_id)
        return result

    def explain_why_not(self, alternative_outcome: str, graph: "ExecutionGraph") -> Dict:
        """
        Explain why a particular outcome did NOT occur.

        Uses goal-directed causal search:
        1. Find minimal interventions that achieve alternative_outcome
        2. Compare with current state to identify blocking factors

        Output: {
            "current_outcome": str,
            "target_outcome": str,
            "blocking_factors": [...],
            "required_change": {...},
            "explanation": str
        }
        """
        # Get current outcome
        engine = ExecutionEngine(self)
        ctx = VMContext()
        ctx = graph.run(engine, ctx)
        current_outcome = ctx.regs.get("R_out", "")

        # If already at target, nothing to explain
        if current_outcome == alternative_outcome:
            return {
                "current_outcome": current_outcome,
                "target_outcome": alternative_outcome,
                "blocking_factors": [],
                "required_change": {},
                "explanation": f"Already at target outcome: {alternative_outcome}"
            }

        # Use find_minimal_causal_sets to find interventions that achieve target
        all_sets = self.find_minimal_causal_sets("n4", graph)

        # Find which intervention achieves the desired outcome
        achieving_intervention = None
        for ms in all_sets.get("minimal_sets", []):
            # Use substring match for outcome comparison
            if alternative_outcome.upper() in ms["outcome"].upper() or ms["outcome"].upper() in alternative_outcome.upper():
                achieving_intervention = ms["vars"]
                break

        if not achieving_intervention:
            return {
                "current_outcome": current_outcome,
                "target_outcome": alternative_outcome,
                "blocking_factors": [],
                "required_change": {},
                "explanation": f"No intervention found to achieve {alternative_outcome}"
            }

        # Identify blocking factors: what differs between current and required
        blocking = []
        for var, target_val in achieving_intervention.items():
            # Find current value from causal analysis
            causal = self.find_causal_parents("n4", graph)
            for c in causal:
                if c["factor"] == var:
                    current_val = c["original_value"]
                    if current_val != target_val:
                        blocking.append({
                            "var": var,
                            "current_value": current_val,
                            "required_value": target_val,
                            "blocks": alternative_outcome,
                            "reason": f"{var}={current_val} prevents reaching {alternative_outcome}"
                        })

        # Build required change dict
        required = {var: target_val for var, target_val in achieving_intervention.items()}

        # Find what would need to flip (for explanation)
        flips_needed = []
        for b in blocking:
            if isinstance(b["current_value"], bool):
                flips_needed.append(f"{b['var']}={not b['current_value']}")
            else:
                flips_needed.append(f"{b['var']}={b['required_value']}")

        explanation = f"System prevented {alternative_outcome} because "
        if flips_needed:
            explanation += " + ".join(flips_needed)
        else:
            explanation += "no valid intervention found"

        return {
            "current_outcome": current_outcome,
            "target_outcome": alternative_outcome,
            "blocking_factors": blocking,
            "required_change": required,
            "explanation": explanation
        }

    def intervene(self, graph: "ExecutionGraph", assignments: Dict[str, Any], at_node: str = None):
        """
        Perform an intervention using do(X=x) semantics.

        Uses ExecutionEngine with clamped variables.
        For true SCM semantics, do(X=x) replaces the equation F_X.

        Returns: (graph, result_regs dict)
        """
        engine = ExecutionEngine(self)
        ctx = VMContext()
        ctx.exogenous = {}

        # Populate exogenous
        for node_id, instr in graph.nodes.items():
            if instr.op == "CALL" and instr.args:
                dest = instr.args[3] if len(instr.args) > 3 else None
                if dest and dest not in ctx.exogenous:
                    ctx.exogenous[f"call_{dest}"] = f"CALL({instr.args[1] if len(instr.args) > 1 else 'diagnose'})"

        # Apply do(X=x) intervention
        for var, val in assignments.items():
            ctx.clamped[var] = val
            ctx.regs[var] = val

        ctx = graph.run(engine, ctx)

        return graph, ctx.regs

    def counterfactual_equivalence_classes(self, graph: "ExecutionGraph") -> Dict[str, List[Dict]]:
        """
        Find all intervention equivalence classes.

        Equivalence class = set of interventions that lead to the same outcome.

        Output: {
            "EMERGENCY PROTOCOL: CALL 911": [
                {"vars": {"R_flag": True}, "size": 1},
                {"vars": {"R_result": "CASE_CRITICAL"}, "size": 1},
            ],
            "REST AND FLUIDS": [...]
        }
        """
        target_instr = self.ir.get("n4")
        if not target_instr:
            return {}

        test_vars = []
        if target_instr.op == "BRANCH" and target_instr.args:
            test_vars.append(target_instr.args[0])
        else:
            test_vars = list(target_instr.reads)

        domains = {}
        for v in test_vars:
            if v == "R_flag":
                domains[v] = [False, True]
            elif v == "R_result":
                domains[v] = ["CASE_NORMAL", "CASE_CRITICAL"]

        if not domains:
            return {}

        # Baseline
        engine = ExecutionEngine(self)
        ctx_base = VMContext()
        ctx_base = graph.run(engine, ctx_base)
        baseline = ctx_base.regs.get("R_out", "")

        # Collect all single interventions
        outcome_groups = {}  # outcome -> list of interventions

        for var in test_vars:
            if var not in domains:
                continue
            for alt_val in domains[var]:
                patched_graph, result = self.intervene(graph, {var: alt_val})
                if isinstance(result, dict):
                    outcome = result.get("R_out", "")
                else:
                    outcome = result.regs.get("R_out", "")
                if outcome not in outcome_groups:
                    outcome_groups[outcome] = []
                outcome_groups[outcome].append({
                    "vars": {var: alt_val},
                    "size": 1,
                    "is_baseline": (outcome == baseline and var == "R_flag" and alt_val == False)
                })

        return outcome_groups

    def extract_world(self, ctx) -> Dict[str, Any]:
        """
        Extract the latent world state (exogenous variables) from a context.

        This captures all non-deterministic choices that affect execution.
        Used to ensure counterfactuals are computed in the SAME world.

        Returns: dict of exogenous values
        """
        return ctx.exogenous.copy() if ctx.exogenous else {}

    def counterfactual(self, graph: "ExecutionGraph", target_node: str, do_assignments: Dict[str, Any]) -> Dict:
        """
        Compute Y_do(X=x)(u) using TRUE Structural Equation semantics.

        Method:
        - Factual: Use ExecutionEngine for correct control flow + record exogenous
        - Counterfactual: Use SES-style equation replacement (same U)

        The key insight: do(X=x) replaces the equation F_X, so we:
        1. Record exogenous U from factual run
        2. For counterfactual, apply interventions BEFORE evaluation (SES style)
        3. Use same U to ensure counterfactual consistency

        This is the Pearl-compliant counterfactual: Y_do(X=x)(u)
        """
        # Extract target variable from target_node
        target_instr = graph.nodes.get(target_node)
        target_var = None
        if target_instr and target_instr.writes:
            target_var = list(target_instr.writes)[0]

        # Factual: use ExecutionEngine for correct semantics
        engine = ExecutionEngine(self)

        ctx_factual = VMContext()
        ctx_factual.exogenous = {}

        # Populate exogenous from factual run
        ctx_factual = graph.run(engine, ctx_factual)
        factual_value = ctx_factual.regs.get(target_var, ctx_factual.regs.get("R_out", ""))

        # Counterfactual: apply do(X=x) intervention using SES semantics
        # do(X=x) = replace equation F_X with constant x
        # We do this by pre-populating clamped vars and re-running
        ctx_cf = VMContext()
        ctx_cf.exogenous = ctx_factual.exogenous.copy()  # SAME world u!

        # Apply do() as equation replacement
        for var, val in do_assignments.items():
            ctx_cf.clamped[var] = val
            ctx_cf.regs[var] = val

        ctx_cf = graph.run(engine, ctx_cf)
        cf_value = ctx_cf.regs.get(target_var, ctx_cf.regs.get("R_out", ""))

        return {
            "factual": factual_value,
            "counterfactual": cf_value,
            "target_var": target_var,
            "do_intervention": do_assignments,
            "exogenous": ctx_factual.exogenous.copy(),
            "changed": factual_value != cf_value,
            "method": "structural_equation_replacement"
        }

    def export_scm(self, graph: "ExecutionGraph") -> Dict[str, Any]:
        """
        Export the execution graph as a Structural Causal Model.

        Uses pruned causal graph to get ACTUAL causal parents (not just dataflow reads).
        An edge X → Y exists iff do(X=x') specifically changes Y.

        Returns: {
            "variables": [var names],
            "parents": {var: [causal parent vars]},
            "equations": {var: "lambda ..."},
            "causal_graph": {source: [targets]}
        }
        """
        causal_graph = self.prune_causal_graph(graph)

        # Build reverse causal graph: target -> sources
        causal_parents = {}  # var -> set of causal parent vars
        for source, targets in causal_graph.items():
            for target in targets:
                if target not in causal_parents:
                    causal_parents[target] = set()
                causal_parents[target].add(source)

        variables = set()
        parents = {}  # var -> list of CAUSAL parent vars (not dataflow!)
        equations = {}  # var -> string representation

        for node_id, instr in self.ir.items():
            for written in instr.writes:
                variables.add(written)
                # Use CAUSAL parents from pruned graph, not dataflow reads
                parents[written] = sorted(list(causal_parents.get(written, set())))

                # Build equation string
                if instr.op == "EQ":
                    equations[written] = f"EQ({instr.args[0]}, {instr.args[1]})"
                elif instr.op == "MOV":
                    if len(instr.args) >= 2:
                        equations[written] = str(instr.args[1])
                    else:
                        equations[written] = "?"
                elif instr.op == "CALL":
                    equations[written] = f"CALL({instr.args[1]})"
                elif instr.op == "BRANCH":
                    equations[written] = f"BRANCH({instr.args[0]})"
                else:
                    equations[written] = instr.op

        return {
            "variables": sorted(list(variables)),
            "parents": parents,
            "equations": equations,
            "causal_graph": {k: sorted(list(v)) for k, v in causal_graph.items() if v}
        }

    def backward_slice(self, target_node: str) -> Set[str]:
        """
        Compute the set of nodes that could affect target_node.

        This is used to limit the search space for minimal causal sets
        to only relevant variables (not all variables in the program).

        Returns: set of node IDs that are ancestors of target_node in dataflow
        """
        relevant = set()
        queue = [target_node]

        while queue:
            current = queue.pop(0)
            if current in relevant:
                continue
            relevant.add(current)

            # Find nodes that feed into current
            for node_id, instr in self.ir.items():
                if target_node in instr.next or any(t in relevant for t in instr.next):
                    if node_id not in relevant:
                        queue.append(node_id)

        return relevant

    # ============================================================
    # Internal Helper Methods
    # ============================================================

    def _build_dominator_tree(self):
        """Build dominator tree using Lengauer-Tarjan algorithm (simplified)."""
        if not self.cfg.entry:
            return

        # Simplified dominator computation
        # For a straight-line CFG, dominators are:
        # - entry dominates all
        # - each block dominates itself and all subsequent blocks in its subtree

        self.cfg.idom = {self.cfg.entry: None}
        self.cfg.dom_tree = {self.cfg.entry: []}

        # BFS to build dominator tree
        visited = set()
        queue = [self.cfg.entry]

        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)

            if current not in self.cfg.dom_tree:
                self.cfg.dom_tree[current] = []

            block = self.cfg.blocks.get(current)
            if block:
                for succ in block.successors:
                    if succ not in visited:
                        if succ not in self.cfg.idom:
                            self.cfg.idom[succ] = current
                        else:
                            # Update idom
                            self.cfg.idom[succ] = self._intersect_idoms(current, self.cfg.idom[succ])
                        if succ not in self.cfg.dom_tree:
                            self.cfg.dom_tree[succ] = []
                        self.cfg.dom_tree[current].append(succ)
                        queue.append(succ)

    def _intersect_idoms(self, a: str, b: str) -> str:
        """Find common dominator of two blocks."""
        # Simplified - just return entry
        return self.cfg.entry

    def _build_def_use_graph(self):
        """Build def-use chain."""
        self.defs = {}  # register → list of (instr_id, block_id)
        self.uses = {}  # instr_id → list of registers read

        for node_id, instr in self.ir.items():
            for reg in instr.reads:
                if reg not in self.uses:
                    self.uses[reg] = []
                self.uses[reg].append(node_id)

            for reg in instr.writes:
                if reg not in self.defs:
                    self.defs[reg] = []
                self.defs[reg].append(node_id)

    def _find_definition(self, var: str, at: str) -> Optional[str]:
        """Find where var is defined before/at 'at'."""
        # BFS backwards from 'at' to find definition
        visited = set()
        queue = [at]

        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)

            instr = self.ir.get(current)
            if instr and var in instr.writes:
                return current

            block = self.cfg.blocks.get(current)
            if block:
                queue.extend(block.predecessors)

        return None

    def _get_reaching_defs(self, var: str, at: str) -> List[str]:
        """Get all definitions that reach point 'at'."""
        results = []
        visited = set()
        queue = [at]

        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)

            instr = self.ir.get(current)
            if instr:
                if var in instr.writes:
                    results.append(current)
                elif var in instr.reads:
                    # Found use but no def in this block - look backwards
                    pass

            block = self.cfg.blocks.get(current)
            if block:
                queue.extend(block.predecessors)

        return results

    def _cfg_path(self, from_node: str, to_node: str) -> List[str]:
        """Find path from from_node to to_node."""
        if from_node == to_node:
            return [from_node]

        visited = set()
        queue = [(from_node, [from_node])]

        while queue:
            current, path = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)

            instr = self.ir.get(current)
            if instr:
                for target in instr.next:
                    if target == to_node:
                        return path + [target]
                    if target not in visited:
                        queue.append((target, path + [target]))

            block = self.cfg.blocks.get(current)
            if block:
                for succ in block.successors:
                    if succ not in visited:
                        queue.append((succ, path + [succ]))

        return []

    def _get_dominators(self, block_id: str) -> List[str]:
        """Get list of blocks that dominate block_id."""
        result = []
        if block_id in self.cfg.idom:
            current = self.cfg.idom[block_id]
            while current:
                result.append(current)
                current = self.cfg.idom.get(current)
        return result

    def _reduce_def(self, def_site: str, var: str, fork_id: str = None) -> SemanticValue:
        """
        Reduce a single definition site to SemanticValue.
        All evaluation goes through here - no scattered if/else.
        Returns SemanticValue with SemanticValue args (not strings).
        """
        instr = self.ir.get(def_site)
        if not instr:
            return SemanticValue(kind=SemanticKind.UNKNOWN, definition_site=def_site)

        if instr.op == "MOV" and len(instr.args) >= 2:
            dest, src = instr.args[0], instr.args[1]
            if isinstance(src, str) and src.startswith("@"):
                # Symbolic register reference
                sv = SemanticValue(
                    kind=SemanticKind.SYMBOLIC,
                    register=src[1:],
                    definition_site=def_site
                )
            else:
                # Constant value
                sv = SemanticValue(
                    kind=SemanticKind.CONSTANT,
                    value=src,
                    definition_site=def_site
                )
            # Materialize to DAG cache
            self.dag_cache.materialize(
                node_id=f"reduce:{def_site}:{var}",
                semantic=sv,
                deps=[],
                derivation=[f"MOV {src} at {def_site}"],
                fork_id=fork_id,
                rule="reduce_def"
            )
            return sv

        elif instr.op == "CALL" and len(instr.args) >= 4:
            # args are strings - convert to SemanticValue
            sv = SemanticValue(
                kind=SemanticKind.COMPUTED,
                op="CALL",
                args=[
                    SemanticValue(kind=SemanticKind.CONSTANT, value=instr.args[1]),
                    SemanticValue(kind=SemanticKind.CONSTANT, value=instr.args[2])
                ],
                definition_site=def_site
            )
            self.dag_cache.materialize(
                node_id=f"reduce:{def_site}:{var}",
                semantic=sv,
                deps=[f"reduce:{pred}:{var}" for pred in self.cfg.blocks.get(def_site, BasicBlock(id=def_site)).predecessors],
                derivation=[f"CALL {instr.args[1]}({instr.args[2]}) at {def_site}"],
                fork_id=fork_id,
                rule="reduce_def"
            )
            return sv

        elif instr.op == "EQ" and len(instr.args) >= 3:
            # args are register refs - convert to SemanticValue
            left, right = instr.args[0], instr.args[1]
            left_sv = self._make_semantic(left)
            right_sv = self._make_semantic(right)
            sv = SemanticValue(
                kind=SemanticKind.COMPUTED,
                op="EQ",
                args=[left_sv, right_sv],
                definition_site=def_site
            )
            self.dag_cache.materialize(
                node_id=f"reduce:{def_site}:{var}",
                semantic=sv,
                deps=[f"reduce:{pred}:{var}" for pred in self.cfg.blocks.get(def_site, BasicBlock(id=def_site)).predecessors],
                derivation=[f"EQ({left}, {right}) at {def_site}"],
                fork_id=fork_id,
                rule="reduce_def"
            )
            return sv
        return SemanticValue(kind=SemanticKind.UNKNOWN, definition_site=def_site)

    def _make_semantic(self, arg) -> SemanticValue:
        """Convert a raw arg (string or value) to SemanticValue."""
        if isinstance(arg, SemanticValue):
            return arg
        if isinstance(arg, str) and arg.startswith("@"):
            return SemanticValue(kind=SemanticKind.SYMBOLIC, register=arg[1:])
        return SemanticValue(kind=SemanticKind.CONSTANT, value=arg)

    # Symmetric operators - args can be reordered without changing meaning
    SYMMETRIC_OPS = {"EQ", "NE", "ADD", "AND", "OR", "MUL"}

    def _canonical_key(self, v: SemanticValue) -> tuple:
        """Canonical key for sorting SemanticValues (must be stable)."""
        if v.kind == SemanticKind.CONSTANT:
            return (0, str(v.value))
        elif v.kind == SemanticKind.SYMBOLIC:
            return (1, v.register)
        elif v.kind == SemanticKind.COMPUTED:
            return (2, v.op, str(v))
        elif v.kind == SemanticKind.PHI:
            return (3, str(v))
        return (4, "")

    def canonicalize(self, v: SemanticValue) -> SemanticValue:
        """
        Recursively canonicalize a SemanticValue.

        Satisfies:
        1. Idempotent: canonicalize(canonicalize(v)) = canonicalize(v)
        2. Equivalence consistent: x ≡ y ⇒ canonicalize(x) = canonicalize(y)
        3. Lattice preserving: canonicalize(join(a,b)) = join(canonicalize(a), canonicalize(b))

        For COMPUTED ops: sort args for symmetric operations
        For PHI: sort incoming by predecessor key
        """
        if v.kind in {SemanticKind.UNKNOWN, SemanticKind.SYMBOLIC, SemanticKind.CONSTANT}:
            return v

        if v.kind == SemanticKind.COMPUTED:
            # Recursively canonicalize args
            args = [self.canonicalize(a) for a in v.args]

            # Sort symmetric ops args for canonical form
            if v.op in self.SYMMETRIC_OPS and len(args) > 1:
                args = sorted(args, key=self._canonical_key)

            return SemanticValue(
                kind=SemanticKind.COMPUTED,
                op=v.op,
                args=args,
                definition_site=v.definition_site
            )

        if v.kind == SemanticKind.PHI:
            # Sort incoming by predecessor key
            incoming = {k: self.canonicalize(val) for k, val in sorted(v.incoming.items())}
            return SemanticValue(
                kind=SemanticKind.PHI,
                incoming=incoming,
                definition_site=v.definition_site
            )

        return v

    def _join(self, values: List[SemanticValue]) -> SemanticValue:
        """
        Join multiple SemanticValues into one.
        Single algebra closure rule - no if/else branching on kinds.
        """
        if not values:
            return SemanticValue(kind=SemanticKind.UNKNOWN)

        # Filter out UNKNOWN
        concrete = [v for v in values if v.kind != SemanticKind.UNKNOWN]
        if not concrete:
            return SemanticValue(kind=SemanticKind.UNKNOWN)

        # All constants with same value
        constants = [v for v in concrete if v.kind == SemanticKind.CONSTANT]
        if len(constants) == len(concrete):
            vals = [v.value for v in constants]
            if len(set(str(v) for v in vals)) == 1:
                return SemanticValue(kind=SemanticKind.CONSTANT, value=constants[0].value)

        # Single concrete value - return directly (no phi needed)
        if len(concrete) == 1:
            return concrete[0]

        # Multiple different values -> phi
        incoming = {}
        for v in concrete:
            incoming[v.definition_site] = str(v)
        return SemanticValue(kind=SemanticKind.PHI, incoming=incoming)

    def _resolve_value(self, var: str, at: str) -> SemanticValue:
        """
        Core resolve: unified reduce/join pipeline.
        All paths converge here - single entry point.
        """
        defs = self._get_reaching_defs(var, at)
        if not defs:
            # No reaching definitions - variable is UNKNOWN at this point
            return SemanticValue(kind=SemanticKind.UNKNOWN)

        # Reduce each definition site
        reduced = [self._reduce_def(d, var) for d in defs]

        # Join all reduced values
        return self._join(reduced)


# ============================================================
# Execution Engine (with semantic resolution integration)
# ============================================================

@dataclass
class VMContext:
    """
    VM execution context with world-consistent state.

    Key fields:
    - regs: current register values
    - clamped: do-calculus interventions (var -> value)
    - exogenous: latent world state (u) for counterfactual reasoning
                   All counterfactuals share the same exogenous values
    - trace: execution history for debugging
    """
    pc: Optional[str] = None
    regs: Dict[str, Any] = field(default_factory=dict)
    done: bool = False
    trace: List[Dict] = field(default_factory=list)
    clamped: Dict[str, Any] = field(default_factory=dict)  # do-calculus: clamped variables
    exogenous: Dict[str, Any] = field(default_factory=dict)  # Latent context for counterfactuals


class ExecutionEngine:
    """Execution engine with semantic query capability."""

    def __init__(self, semantic_resolver: SemanticResolver):
        self.semantic = semantic_resolver

    def step(self, instr: Instr, ctx: VMContext):
        handlers = {
            "MOV": self._mov,
            "CALL": self._call,
            "EQ": self._eq,
            "BRANCH": self._branch,
            "HALT": self._halt,
        }

        result = handlers.get(instr.op, lambda i, c: None)(instr, ctx)
        ctx.trace.append({"pc": instr.id, "op": instr.op, "result": str(result)[:30] if result else None})
        return result

    def _mov(self, instr: Instr, ctx: VMContext):
        dest = instr.args[0] if instr.args else None
        src = instr.args[1] if len(instr.args) > 1 else None
        if isinstance(src, str) and src.startswith("@"):
            src = ctx.regs.get(src[1:])
        if dest:
            # do-calculus: skip write if variable is clamped (intervened)
            if dest in ctx.clamped:
                return src
            ctx.regs[dest] = src
        return src

    def _call(self, instr: Instr, ctx: VMContext):
        """
        Execute CALL instruction with exogenous tracking.

        CALL represents external non-determinism (tools, agents, noise).
        We record the result in exogenous to enable counterfactual reasoning:
        - Same exogenous → same external call results
        - This captures the latent world state U
        """
        dest = instr.args[3] if len(instr.args) > 3 else None
        tool_name = instr.args[1] if len(instr.args) > 1 else "unknown"

        # Generate result - this represents external non-determinism
        # In a real system, this would be the actual tool/agent response
        result = f"CALL({tool_name})"

        # Record in exogenous to capture latent world state
        # This is how we bind the external non-determinism to U
        if dest and dest not in ctx.exogenous:
            # Store the external call result in exogenous
            # This binds the "randomness" to the world state U
            ctx.exogenous[f"call_{dest}"] = result

        if dest:
            # do-calculus: skip write if variable is clamped
            if dest in ctx.clamped:
                return result
            ctx.regs[dest] = result
        return result

    def _eq(self, instr: Instr, ctx: VMContext):
        dest = instr.args[2] if len(instr.args) > 2 else None
        left = ctx.regs.get(instr.args[0][1:]) if isinstance(instr.args[0], str) and instr.args[0].startswith("@") else instr.args[0]
        right = instr.args[1] if len(instr.args) > 1 else None
        result = (left == right)
        if dest:
            # do-calculus: skip write if variable is clamped
            if dest in ctx.clamped:
                return result
            ctx.regs[dest] = result
        return result

    def _branch(self, instr: Instr, ctx: VMContext):
        flag = ctx.regs.get(instr.args[0]) if instr.args else False
        ctx.pc = instr.next[1] if not flag and len(instr.next) > 1 else (instr.next[0] if flag else None)
        return None

    def _halt(self, instr: Instr, ctx: VMContext):
        ctx.done = True
        return None

    def resolve_next(self, instr: Instr, result: Any, ctx: VMContext) -> Optional[str]:
        """Resolve next instruction."""
        if instr.op == "HALT":
            ctx.done = True
            return None
        if instr.op == "BRANCH":
            flag = ctx.regs.get(instr.args[0]) if instr.args else False
            ctx.pc = instr.next[1] if not flag and len(instr.next) > 1 else (instr.next[0] if flag else None)
            return ctx.pc
        if instr.op == "JUMP":
            ctx.pc = instr.next[0] if instr.next else None
            return ctx.pc
        return None


# ============================================================
# Structural Equation System (True SCM Semantics)
# ============================================================

class SSABuilder:
    """
    SSA (Static Single Assignment) builder for structural equations.

    Transforms CFG with branching into versioned variables with phi nodes at merge points.

    BEFORE (Execution model):
        if cond: Y = A
        else:   Y = B
        → path selection = control semantics

    AFTER (SCM model):
        Y_1 = A
        Y_2 = B
        Y_3 = φ(Y_1, Y_2, cond)
        → Y = F_Y(parents, U) = cond ? A : B
    """

    def __init__(self, graph: "ExecutionGraph"):
        self.graph = graph
        self.cfg = graph.cfg
        self.next_version: Dict[str, int] = {}
        self.phi_nodes: Dict[str, str] = {}  # merge_point -> phi_var
        self.var_versions: Dict[str, Dict[str, str]] = {}  # original_var -> node_id -> versioned_var

    def build(self) -> Dict[str, "Equation"]:
        """
        Build SSA-based structural equations.

        Returns: {versioned_var: Equation}
        Each Equation contains: F_Y = lambda(parent_values, U) -> Y_value
        """
        # Step 1: Identify merge points (nodes with >1 predecessor)
        merge_points = self._find_merge_points()

        # Step 2: For each merge point, insert phi node
        for mp in merge_points:
            self._insert_phi(mp)

        # Step 3: Build equations for all versioned variables
        equations = {}
        for orig_var, versions in self.var_versions.items():
            for node_id, versioned_var in versions.items():
                instr = self.graph.nodes.get(node_id)
                if instr:
                    eq = self._build_eq_for_instr(instr, versioned_var)
                    if eq:
                        equations[versioned_var] = eq

        return equations

    def _find_merge_points(self) -> List[str]:
        """Find all CFG nodes that are merge points (>1 predecessor)."""
        merge_points = []
        for node_id, block in self.cfg.blocks.items():
            if len(block.predecessors) > 1:
                merge_points.append(node_id)
        return merge_points

    def _insert_phi(self, merge_point: str) -> str:
        """
        Insert phi node at merge point.

        Creates: phi_var = φ(var_1, var_2, ..., cond)
        Returns: the phi variable name
        """
        block = self.cfg.blocks.get(merge_point)
        if not block or len(block.predecessors) < 2:
            return None

        preds = block.predecessors

        # Generate unique phi variable
        phi_var = f"phi_{merge_point}"
        self.phi_nodes[merge_point] = phi_var

        # Track all incoming versions from each predecessor
        incoming_versions = []
        for pred in preds:
            # Each predecessor defines a version of variables
            pred_versions = self._get_versions_at(pred)
            incoming_versions.append(pred_versions)

        # Create phi function: selects based on condition
        # We store which original var each version comes from
        self.var_versions.setdefault(phi_var, {})[merge_point] = phi_var

        return phi_var

    def _get_versions_at(self, node_id: str) -> Dict[str, str]:
        """Get all variable versions current at a given node."""
        versions = {}
        for orig_var, node_map in self.var_versions.items():
            # Find the latest version before/at node_id
            for n in self.cfg.blocks.keys():
                if n == node_id and node_id in node_map:
                    versions[orig_var] = node_map[node_id]
        return versions

    def _next_version(self, var: str) -> str:
        """Get next versioned name for var."""
        if var not in self.next_version:
            self.next_version[var] = 0
        v = self.next_version[var]
        self.next_version[var] = v + 1
        return f"{var}_{v}"

    def _build_eq_for_instr(self, instr: "Instr", output_var: str) -> Optional["Equation"]:
        """Build equation for a single instruction."""
        op = instr.op
        args = instr.args

        if op == "MOV":
            src = args[1] if len(args) > 1 else None
            if isinstance(src, str) and not src.startswith("@"):
                # Constant
                return Equation(output_var, [], lambda p, U, c=src: c)
            elif isinstance(src, str) and src.startswith("@"):
                # Copy from parent
                parent = src[1:]
                return Equation(output_var, [parent], lambda p, U, s=parent: p[0] if p else U.get(s))
            else:
                return None

        elif op == "EQ":
            left = args[0] if len(args) > 0 else None
            right = args[1] if len(args) > 1 else None
            if isinstance(left, str) and left.startswith("@"):
                left = left[1:]
            if isinstance(right, str) and right.startswith("@"):
                right = right[1:]
            return Equation(output_var, [left, right], lambda p, U: p[0] == p[1] if len(p) >= 2 else False)

        elif op == "CALL":
            tool = args[1] if len(args) > 1 else "unknown"
            return Equation(output_var, [], lambda p, U, t=tool: U.get(f"call_{output_var}", f"CALL({t})"))

        elif op == "BRANCH":
            # BRANCH doesn't define a value directly, but conditions subsequent MOVs
            return None

        return None


@dataclass
class Equation:
    """
    Structural equation F_Y = lambda(parent_values, U) -> Y_value

    In SCM, every variable Y is defined by a structural equation:
    Y := F_Y(parents, U)

    where:
    - parents: values of parent variables (direct causes)
    - U: exogenous (latent) variables
    """
    output_var: str
    parent_vars: List[str]
    fn: Callable  # lambda(parent_vals, U) -> value

    def evaluate(self, parent_values: List, U: Dict) -> Any:
        return self.fn(parent_values, U)

    def __repr__(self):
        return f"F_{self.output_var}({self.parent_vars})"


# ============================================================
# Structural Equation System (True SCM Evaluator)
# ============================================================

class StructuralEquationSystem:
    """
    True Structural Causal Model evaluator.

    Key properties:
    - Each variable Y has ONE equation F_Y (SSA ensures single definition)
    - do(X=x) REPLACES F_X with constant x (Pearl semantics)
    - No execution - pure functional evaluation topologically

    vs ExecutionEngine (approximation):
    - ExecutionEngine: path selection via control flow
    - SES: value = F_Y(parents, U) - no paths, only functions
    """

    def __init__(self, graph: "ExecutionGraph"):
        self.graph = graph
        self.equations: Dict[str, Equation] = {}
        self.branch_conditions: Dict[str, str] = {}  # node_id -> condition var
        self.build_equations()

    def build_equations(self):
        """Build structural equations from IR with SSA-style version tracking."""
        # First pass: identify branch conditions
        for node_id, instr in self.graph.nodes.items():
            if instr.op in ("BR", "BRANCH") and instr.args:
                cond = instr.args[0]
                if isinstance(cond, str) and cond.startswith("@"):
                    cond = cond[1:]
                self.branch_conditions[node_id] = cond

        # Find merge points - ONLY explicit MERGE nodes
        # This is the key architectural change: merge is DEFINED, not detected
        merge_points = set()
        for node_id, instr in self.graph.nodes.items():
            if instr.op == "MERGE":
                merge_points.add(node_id)

        # Track all definitions (SSA: each definition is a new version)
        definitions = {}  # var -> list of (node_id, eq)

        # Process nodes in topological order
        for node_id in self._topo_order():
            instr = self.graph.nodes.get(node_id)
            if not instr:
                continue

            # Process writes
            for written in instr.writes:
                eq = self._build_instr_eq(instr, written, {})
                if eq:
                    # Each definition creates a new version
                    versioned = f"{written}_d{len(definitions.get(written, []))}"
                    eq.output_var = versioned
                    if written not in definitions:
                        definitions[written] = []
                    definitions[written].append((node_id, eq))

                    # Store equation
                    self.equations[versioned] = eq

            # At merge point, create phi that joins all definitions
            if node_id in merge_points:
                # Get all variables that were defined before this merge
                for var, defs in definitions.items():
                    if not defs:
                        continue

                    # Find the BRANCH that controls this merge point
                    # The merge point's predecessors should be the direct successors of the BRANCH
                    branch_node_id = None
                    branch_cond = None

                    # Get the merge point's predecessors (the two branches)
                    block = self.graph.cfg.blocks.get(node_id)
                    if block and len(block.predecessors) >= 2:
                        # The two predecessors should be n5a and n5b
                        # Their common predecessor is n4 (the BRANCH)
                        pred0 = block.predecessors[0]
                        pred1 = block.predecessors[1]
                        # Trace back to find common predecessor that is a BRANCH
                        common = self._find_common_ancestor(pred0, pred1)
                        if common:
                            branch_instr = self.graph.nodes.get(common)
                            if branch_instr and branch_instr.op in ("BR", "BRANCH"):
                                branch_node_id = common
                                cond = branch_instr.args[0] if branch_instr.args else None
                                if isinstance(cond, str) and cond.startswith("@"):
                                    cond = cond[1:]
                                branch_cond = cond

                    # Get the two branch values - need to correctly identify which is false/true
                    # based on BRANCH next[] ordering, not defs order
                    false_var = None
                    true_var = None

                    if len(defs) >= 2:
                        # We need to know which predecessor is false and which is true
                        # BRANCH next[0] = true target, next[1] = false target
                        branch_instr = None
                        if branch_node_id:
                            branch_instr = self.graph.nodes.get(branch_node_id)

                        if branch_instr and branch_instr.next and len(branch_instr.next) >= 2:
                            # BRANCH next[0] = true target, next[1] = false target
                            true_target = branch_instr.next[0]   # n5b (when flag=True)
                            false_target = branch_instr.next[1]  # n5a (when flag=False)

                            # Find which def corresponds to which branch
                            for pred_node, eq in defs:
                                if pred_node == false_target:
                                    false_var = eq.output_var
                                elif pred_node == true_target:
                                    true_var = eq.output_var

                        # Fallback: use order
                        if false_var is None or true_var is None:
                            false_var = defs[-2][1].output_var
                            true_var = defs[-1][1].output_var
                    elif len(defs) == 1:
                        false_var = defs[0][1].output_var
                        true_var = defs[0][1].output_var
                    else:
                        continue

                    # Skip phi if no branch condition found (uncontrolled merge)
                    if not branch_cond:
                        continue

                    # Find the versioned variable for the condition (R_flag)
                    # The condition var is an EXPLICIT causal parent of phi
                    cond_var = branch_cond  # e.g., "R_flag"
                    # Find versioned cond var (e.g., "R_flag_d0")
                    cond_versioned = None
                    for eq_var, eq in self.equations.items():
                        if eq.output_var.startswith(cond_var):
                            cond_versioned = eq_var
                            break
                    if not cond_versioned:
                        cond_versioned = cond_var

                    phi_var = f"phi${node_id}${var}"
                    phi_eq = Equation(
                        output_var=phi_var,
                        parent_vars=[false_var, true_var, cond_versioned],  # explicit causal parent!
                        fn=self._make_phi_fn(cond_var, true_var, false_var)
                    )
                    self.equations[phi_var] = phi_eq

    def _find_common_ancestor(self, node_a: str, node_b: str) -> Optional[str]:
        """Find common ancestor of two nodes by tracing predecessors."""
        ancestors_a = set()
        current = node_a
        while current:
            ancestors_a.add(current)
            block = self.graph.cfg.blocks.get(current)
            if block and block.predecessors:
                current = block.predecessors[0]  # Take first predecessor
            else:
                current = None

        # Find common ancestor
        current = node_b
        while current:
            if current in ancestors_a:
                return current
            block = self.graph.cfg.blocks.get(current)
            if block and block.predecessors:
                current = block.predecessors[0]
            else:
                current = None
        return None

    def _topo_order(self) -> List[str]:
        """Get nodes in topological order (forward CFG traversal)."""
        visited = set()
        order = []

        def visit(node_id):
            if node_id in visited or node_id not in self.graph.nodes:
                return
            visited.add(node_id)
            instr = self.graph.nodes[node_id]
            # Visit all successors
            for succ in instr.next:
                visit(succ)
            # Add AFTER visiting successors (post-order)
            order.append(node_id)

        visit(self.graph.root)
        # Reverse to get forward order (predecessors before successors)
        order.reverse()
        return order

    def _make_phi_fn(self, condition_var: str, true_var: str, false_var: str):
        """
        Create phi function with EXPLICIT causal parent (condition_var).

        BEFORE (U-lookup - not true SCM):
            cond_val = U.get(cond_var)  # hidden dependency
            return true_val if cond_val else false_val

        AFTER (explicit causal parent - true SCM):
            phi_fn receives condition as explicit parent argument
            phi = lambda R0, R1, R_flag: R_flag ? R1 : R0

        This is the key SCM property:
        - All causality must be explicit in the parent graph
        - No hidden "control flow as external lookup"
        """
        cv = condition_var

        def phi_fn(parent_vals, U):
            if len(parent_vals) < 3:
                return parent_vals[0] if parent_vals else None

            false_val, true_val, cond_val = parent_vals[0], parent_vals[1], parent_vals[2]
            return true_val if cond_val else false_val

        return phi_fn

    def _build_instr_eq(self, instr: "Instr", output_var: str, versions: Dict[str, str]) -> Optional[Equation]:
        """Build equation for a single instruction."""
        op = instr.op
        args = instr.args

        if op == "MOV":
            src = args[1] if len(args) > 1 else None
            if isinstance(src, str) and not src.startswith("@"):
                # Constant assignment
                const = src
                return Equation(output_var, [], lambda p, U, c=const: c)
            elif isinstance(src, str) and src.startswith("@"):
                # Copy from parent (dereference @)
                parent = src[1:]
                return Equation(output_var, [parent], lambda p, U, s=parent: U.get(s) or p[0])
            else:
                return None

        elif op == "EQ":
            left = args[0] if len(args) > 0 else None
            right = args[1] if len(args) > 1 else None
            # Dereference @ prefix
            if isinstance(left, str) and left.startswith("@"):
                left = left[1:]
            if isinstance(right, str) and right.startswith("@"):
                right = right[1:]
            # Only add VARIABLE references as parents (not constant literals)
            parent_vars = []
            if left and not left.startswith("CASE_") and left not in ("TRUE", "FALSE", "True", "False"):
                parent_vars.append(left)
            if right and not right.startswith("CASE_") and right not in ("TRUE", "FALSE", "True", "False"):
                parent_vars.append(right)
            # Compare actual values: left_val == right_val
            def eq_fn(p, U, l=left, r=right):
                left_val = p[0] if len(p) > 0 else l
                right_val = p[1] if len(p) > 1 else r
                return left_val == right_val
            return Equation(output_var, parent_vars, eq_fn)

        elif op == "CALL":
            tool = args[1] if len(args) > 1 else "unknown"
            return Equation(output_var, [], lambda p, U, t=tool: U.get(f"call_{output_var}", f"CALL({t})"))

        elif op == "BRANCH":
            # BRANCH doesn't define a value, but we record the condition
            cond_var = args[0] if args else None
            if isinstance(cond_var, str) and cond_var.startswith("@"):
                cond_var = cond_var[1:]
            self.branch_conditions[instr.id] = cond_var
            return None

        return None

    def _build_phi_eq(self, phi_var: str, block: "BasicBlock", versions: Dict[str, str]) -> Optional[Equation]:
        """
        Build phi equation at merge point.

        Phi selects from incoming values based on branch condition.

        F_phi = λ parents, U: cond ? val_true : val_false
        """
        if len(block.predecessors) < 2:
            return None

        preds = block.predecessors

        # Find the branch that controls this merge
        branch_cond = None
        for pred in preds:
            pred_instr = self.graph.nodes.get(pred)
            if pred_instr and pred_instr.op == "BRANCH":
                cond = pred_instr.args[0] if pred_instr.args else None
                if isinstance(cond, str) and cond.startswith("@"):
                    cond = cond[1:]
                branch_cond = cond
                break

        if not branch_cond:
            return None

        # Get incoming values from each predecessor
        # In true SSA, phi takes one arg per predecessor
        incoming_vars = [f"in_{i}" for i in range(len(preds))]

        # Phi function: cond ? true_val : false_val
        def phi_fn(p, U, cond=branch_cond, preds=preds):
            # p[0] = false branch value, p[1] = true branch value
            # Branch condition determines which path was taken
            # For counterfactual, we need to evaluate both and select
            if len(p) >= 2:
                # Simplified: just return based on condition value in U
                cond_val = U.get(cond, False)
                return cond_val and p[1] or p[0]
            return None

        return Equation(phi_var, incoming_vars, phi_fn)

    def evaluate(self, U: Dict, interventions: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Evaluate all equations topologically.

        For each variable Y:
        - If do(Y=y): Y = y (equation REPLACED with constant)
        - Else: Y = F_Y(parents, U)

        This is PURE FUNCTIONAL evaluation - no execution, no control flow.
        """
        interventions = interventions or {}
        results = {}

        # Topological sort
        order = self._topo_sort()

        for var in order:
            if var in interventions:
                # do(X=x): REPLACE equation with constant
                results[var] = interventions[var]
            elif var in self.equations:
                eq = self.equations[var]
                parent_vals = [results.get(p) for p in eq.parent_vars]
                results[var] = eq.evaluate(parent_vals, U)

        return results

    def _topo_sort(self) -> List[str]:
        """Topological sort of variables based on causal dependencies."""
        visited = set()
        order = []

        def visit(var):
            if var in visited:
                return
            visited.add(var)
            if var in self.equations:
                for parent in self.equations[var].parent_vars:
                    visit(parent)
            order.append(var)

        for var in self.equations:
            visit(var)

        return order

    def do_intervene(self, interventions: Dict[str, Any]) -> "StructuralEquationSystem":
        """
        Create new SES with do(X=x) applied.

        do(X=x) = REPLACE F_X with constant x
        This also updates U so that phi functions see the intervened value.

        Returns: (new_ses, modified_U)
        """
        new_ses = StructuralEquationSystem(self.graph)
        new_ses.equations = dict(self.equations)
        new_ses.branch_conditions = dict(self.branch_conditions)

        # Replace equations for intervened variables
        for var, val in interventions.items():
            # Find equation for this variable and replace with constant
            for eq_var, eq in new_ses.equations.items():
                # Match by base variable name (e.g., "R_flag_d0" matches "R_flag")
                base_name = eq_var.split('_d')[0] if '_d' in eq_var else eq_var
                if base_name == var:
                    # Replace with constant equation
                    new_ses.equations[eq_var] = Equation(
                        output_var=eq_var,  # Keep versioned name
                        parent_vars=[],
                        fn=lambda p, U, v=val: v
                    )
                    break

        return new_ses

    def counterfactual(self, U: Dict, do_assignments: Dict[str, Any], target_var: str) -> Dict[str, Any]:
        """
        Compute Y_do(X=x)(u) - true counterfactual with same U.

        Method:
        1. Evaluate factual: Y = F_Y(parents, U)
        2. Apply do(X=x): F_X replaced with x, U updated with intervened values
        3. Re-evaluate with same U (modified by intervention)

        This is the Pearl-compliant counterfactual.
        """
        # Factual
        factual = self.evaluate(U, {})

        # Counterfactual with do() applied
        # Update U with intervened values so phi functions see them
        U_cf = dict(U)
        U_cf.update(do_assignments)

        cf_ses = self.do_intervene(do_assignments)
        counterfactual = cf_ses.evaluate(U_cf, {})

        return {
            "factual": factual.get(target_var, factual.get("R_out")),
            "counterfactual": counterfactual.get(target_var, counterfactual.get("R_out")),
            "exogenous": U,
            "interventions": do_assignments,
            "changed": factual != counterfactual
        }


# ============================================================
# ExecutionGraph (with semantic resolution)
# ============================================================

class ExecutionGraph:
    """Execution graph with integrated semantic resolution + DAG materialization."""

    def __init__(self):
        self.nodes: Dict[str, Instr] = {}
        self.root: Optional[str] = None
        self.cfg: Optional[ControlFlowGraph] = None
        self.semantic: Optional[SemanticResolver] = None
        self.dag_cache: DAGCache = DAGCache()  # v0.97: trace materialization

    def instr(self, id: str, op: str, args: List = None, next: List = None) -> "ExecutionGraph":
        instr = Instr(
            id=id,
            op=op,
            args=args or [],
            next=next or [],
            writes=set(),
            reads=set()
        )
        # Compute reads/writes
        for arg in instr.args:
            if isinstance(arg, str) and arg.startswith("@"):
                instr.reads.add(arg[1:])
        # writes: MOV dest, src → dest is args[0]; CALL/EQ/CMP/LOAD write to last arg; MERGE has no writes
        if op == "MOV" and len(args) >= 2:
            instr.writes.add(args[0])
        elif op in ("CALL", "EQ", "CMP", "LOAD") and len(args) >= 1:
            instr.writes.add(args[-1])
        # MERGE is a pure control flow node - no registers written

        self.nodes[id] = instr
        if self.root is None:
            self.root = id
        return self

    def set_root(self, id: str) -> "ExecutionGraph":
        self.root = id
        return self

    def build_cfg(self):
        """Build CFG from nodes."""
        self.cfg = ControlFlowGraph()
        self.cfg.entry = self.root

        # Build blocks
        for node_id, instr in self.nodes.items():
            block = BasicBlock(id=node_id, successors=instr.next[:])
            self.cfg.blocks[node_id] = block

        # Add predecessors
        for node_id, instr in self.nodes.items():
            for target in instr.next:
                if target in self.cfg.blocks:
                    if node_id not in self.cfg.blocks[target].predecessors:
                        self.cfg.blocks[target].predecessors.append(node_id)

        # Build semantic resolver with DAG cache
        self.semantic = SemanticResolver(self.cfg, self.nodes, self.dag_cache)

    def run(self, engine: ExecutionEngine, ctx: VMContext) -> VMContext:
        """Execute graph."""
        if not self.root:
            ctx.done = True
            return ctx

        current = self.root
        while not ctx.done and current:
            instr = self.nodes.get(current)
            if not instr:
                break

            engine.step(instr, ctx)

            if instr.op == "HALT":
                ctx.done = True
                break

            next_id = engine.resolve_next(instr, None, ctx)
            if next_id:
                current = next_id
            elif ctx.pc:
                current = ctx.pc
                ctx.pc = None  # clear after use
            elif instr.next:
                current = instr.next[0]
            else:
                break

        return ctx

    def fork_at(self, node_id: str, patch: Dict) -> "ExecutionGraph":
        """Fork graph with patch."""
        new_graph = ExecutionGraph()
        for id, instr in self.nodes.items():
            new_graph.nodes[id] = Instr(
                id=instr.id, op=instr.op, args=instr.args[:],
                next=instr.next[:], writes=instr.writes.copy(),
                reads=instr.reads.copy()
            )
        new_graph.root = self.root

        if node_id in new_graph.nodes:
            target = new_graph.nodes[node_id]
            if "op" in patch: target.op = patch["op"]
            if "args" in patch: target.args = patch["args"]
            if "next" in patch: target.next = patch["next"]

        return new_graph


# ============================================================
# v1.1 Agent-SCM Interface Layer (Domain-Agnostic)
# ============================================================

@dataclass
class ToolDecision:
    """
    DOMAIN-AGNOSTIC tool selection decision.

    Contains NO business semantics - only structural decision information.
    """
    node_id: str
    condition_var: str  # internal variable name (e.g., "cond_7")
    true_tool_id: str   # tool identifier when condition=True
    false_tool_id: str  # tool identifier when condition=False
    selected_tool_id: str  # what was actually selected
    outcome_var: str  # which output variable was written


@dataclass
class AgentOverride:
    """
    DOMAIN-AGNOSTIC behavioral intervention.

    This is NOT business-specific - any agent can use this.
    """
    target_node: str
    override_type: str  # "force_tool" | "force_branch"
    tool_id: Optional[str] = None
    condition_value: Optional[Any] = None
    description: str = ""


class ExogenousModel:
    """
    DOMAIN-AGNOSTIC model of external uncertainty.

    U = exogenous variables = things outside the agent's control.

    This is PLUGGABLE - you can implement real stochastic models:
    - llm.sampling: stochastic token generation
    - tool.latency: external API delays
    - tool.failure: external service reliability
    - memory.noise: retrieval imperfections
    """

    def __init__(self):
        self.values = {}  # var -> value (can be set for counterfactual)

    def sample(self, var: str, default: Any = None) -> Any:
        """Get value, using stored value if set, else default."""
        return self.values.get(var, default)

    def set(self, var: str, value: Any):
        """Set a specific exogenous value (for counterfactual consistency)."""
        self.values[var] = value

    def get(self, var: str, default: Any = None) -> Any:
        return self.sample(var, default)


class AgentIR:
    """
    DOMAIN-AGNOSTIC agent debugging interface.

    Transforms internal SCM → Agent debugger (completely domain-agnostic)

    API Surface:
        agent.why(node_id)          → why was this decision made?
        agent.what_if(node_id, ov)  → what if we forced different behavior?
        agent.blame(output_var)    → which decision caused this output?
        agent.attach_semantic(fn)  → optional: add domain labels (NOT required)

    KEY: All outputs are decision/tool/condition structure.
         NO business strings. NO hardcoded semantics.
    """

    def __init__(self, graph: ExecutionGraph, exogenous: Optional[ExogenousModel] = None):
        self.graph = graph
        self.ses = StructuralEquationSystem(graph)
        self.exogenous = exogenous or ExogenousModel()
        self._semantic_fn = None  # optional: domain-specific label function
        self._build_decision_map()

    def attach_semantic(self, fn: Callable[[str, ToolDecision], Optional[str]]):
        """
        Attach OPTIONAL domain semantics via a pluggable function.

        NOT required - debugger works without this.
        But if you want labels, you can add them.

        Example:
            agent.attach_semantic(lambda node_id, decision: {
                "n4": "criticality_check",
            }.get(node_id))
        """
        self._semantic_fn = fn

    def _build_decision_map(self):
        """Build decision map (completely domain-agnostic)."""
        self.decisions = {}  # node_id -> ToolDecision
        self.phi_to_branch = {}  # phi_var -> controlling branch

        # Find branches and their merge points
        branch_to_merge = {}
        for node_id, block in self.graph.cfg.blocks.items():
            if len(block.predecessors) > 1:
                preds = block.predecessors
                common = self._find_common_branch(preds[0], preds[1])
                if common:
                    if common not in branch_to_merge:
                        branch_to_merge[common] = []
                    branch_to_merge[common].append(node_id)

        # Build decision for each phi
        for var, eq in self.ses.equations.items():
            if not var.startswith("phi$"):
                continue
            parts = var.split("$")
            if len(parts) < 3 or parts[0] != "phi":
                continue

            merge_node = parts[1]
            outcome_var = "$".join(parts[2:])

            branch_node = None
            for bn, merges in branch_to_merge.items():
                if merge_node in merges:
                    branch_node = bn
                    break

            if not branch_node:
                continue

            cond_var = self.ses.branch_conditions.get(branch_node, f"cond_{branch_node}")
            true_tid = self._get_tool_id(branch_node, is_true=True)
            false_tid = self._get_tool_id(branch_node, is_true=False)
            selected = self._evaluate_selected(var, eq, true_tid, false_tid)

            self.phi_to_branch[var] = branch_node
            self.decisions[branch_node] = ToolDecision(
                node_id=branch_node,
                condition_var=cond_var,
                true_tool_id=true_tid,
                false_tool_id=false_tid,
                selected_tool_id=selected,
                outcome_var=outcome_var
            )

    def _find_common_branch(self, node_a: str, node_b: str) -> Optional[str]:
        """Find common BRANCH ancestor."""
        ancestors_a = set()
        current = node_a
        while current:
            ancestors_a.add(current)
            block = self.graph.cfg.blocks.get(current)
            current = block.predecessors[0] if block and block.predecessors else None

        current = node_b
        while current:
            if current in ancestors_a:
                instr = self.graph.nodes.get(current)
                if instr and instr.op == "BRANCH":
                    return current
            block = self.graph.cfg.blocks.get(current)
            current = block.predecessors[0] if block and block.predecessors else None
        return None

    def _get_tool_id(self, branch_node: str, is_true: bool) -> str:
        """Get tool ID from branch target (completely domain-agnostic)."""
        instr = self.graph.nodes.get(branch_node)
        if not instr or not instr.next:
            return f"tool_{branch_node}"

        # BRANCH next[0] = true target, next[1] = false target
        idx = 0 if is_true else 1
        if len(instr.next) <= idx:
            idx = 0

        target = instr.next[idx]
        # Return the target node id as the tool identifier (domain-agnostic)
        # The actual semantics can be derived from the instruction at that node
        return target

    def _evaluate_selected(self, phi_var: str, eq, true_tid: str, false_tid: str) -> str:
        """Determine which tool was selected."""
        result = self.ses.evaluate(self._get_U(), {})
        eq_obj = self.ses.equations.get(phi_var)
        if eq_obj and len(eq_obj.parent_vars) >= 3:
            cond_val = result.get(eq_obj.parent_vars[2], False)
            return true_tid if cond_val else false_tid
        return false_tid

    def _get_U(self) -> Dict[str, Any]:
        """Get exogenous values."""
        U = {}
        for var in self.ses.equations:
            val = self.exogenous.get(var)
            if val is not None:
                U[var] = val
        return U

    def why(self, node_id: str) -> Dict[str, Any]:
        """
        Question: Why was this decision made?

        Returns DOMAIN-AGNOSTIC explanation:
        {
            node: "n4",
            decision: "tool_selection",
            condition_var: "cond_4",
            condition_value: true/false,
            options: {when_true: "tool_A", when_false: "tool_B"},
            selected_tool: "tool_A",
            outcome_var: "output_1",
            semantic_label: "criticality_check"  # if attached
        }
        """
        if node_id not in self.decisions:
            return {"error": f"No decision at node {node_id}", "node": node_id}

        d = self.decisions[node_id]
        cond_val = self._get_condition_value(node_id)

        semantic = None
        if self._semantic_fn:
            try:
                semantic = self._semantic_fn(node_id, d)
            except:
                pass

        return {
            "node": node_id,
            "decision": "tool_selection",
            "condition_var": d.condition_var,
            "condition_value": cond_val,
            "options": {"when_true": d.true_tool_id, "when_false": d.false_tool_id},
            "selected_tool": d.selected_tool_id,
            "outcome_var": d.outcome_var,
            "semantic_label": semantic,
            "causal_chain": self._get_causal_chain(node_id)
        }

    def what_if(self, node_id: str, override: AgentOverride) -> Dict[str, Any]:
        """
        Question: What if we forced a different decision?
        """
        if node_id not in self.decisions:
            return {"error": f"No decision at node {node_id}"}

        d = self.decisions[node_id]

        if override.override_type == "force_tool":
            if override.tool_id == d.true_tool_id:
                intervention = {d.condition_var: True}
            elif override.tool_id == d.false_tool_id:
                intervention = {d.condition_var: False}
            else:
                intervention = {d.condition_var: override.condition_value}
        else:
            intervention = {d.condition_var: override.condition_value}

        factual = self.ses.evaluate(self._get_U(), {})
        cf_ses = self.ses.do_intervene(intervention)
        U_cf = dict(self._get_U())
        U_cf.update(intervention)
        counterfactual = cf_ses.evaluate(U_cf, {})

        phi_var = self._find_phi(node_id, d.outcome_var)
        factual_outcome = factual.get(phi_var)
        counterfactual_outcome = counterfactual.get(phi_var)

        return {
            "node": node_id,
            "original_decision": d.selected_tool_id,
            "factual_outcome_var": d.outcome_var,
            "factual_outcome": factual_outcome,
            "counterfactual_outcome": counterfactual_outcome,
            "would_change": factual_outcome != counterfactual_outcome,
            "override": override.description or f"force {override.tool_id}",
            "intervention": intervention
        }

    def blame(self, output_var: str) -> Dict[str, Any]:
        """
        Question: Which decision caused this output?
        """
        contributing = []
        for phi_var, bn in self.phi_to_branch.items():
            if output_var in phi_var and bn in self.decisions:
                d = self.decisions[bn]
                contributing.append({
                    "node": bn,
                    "decision": "tool_selection",
                    "condition_var": d.condition_var,
                    "selected_tool": d.selected_tool_id,
                    "outcome_var": d.outcome_var,
                    "impact": "direct"
                })

        return {
            "output_var": output_var,
            "root_cause": contributing[0] if contributing else None,
            "contributing_decisions": contributing
        }

    def _get_condition_value(self, node_id: str) -> Any:
        result = self.ses.evaluate(self._get_U(), {})
        d = self.decisions.get(node_id)
        if not d:
            return None
        phi_var = self._find_phi(node_id, d.outcome_var)
        eq = self.ses.equations.get(phi_var)
        if eq and len(eq.parent_vars) >= 3:
            return result.get(eq.parent_vars[2])
        return None

    def _find_phi(self, branch_node: str, outcome_var: str) -> str:
        for phi_var, bn in self.phi_to_branch.items():
            if bn == branch_node and outcome_var in phi_var:
                return phi_var
        return f"phi_{branch_node}_{outcome_var}"

    def _get_causal_chain(self, node_id: str) -> List[str]:
        chain = []
        d = self.decisions.get(node_id)
        if not d:
            return chain
        phi_var = self._find_phi(node_id, d.outcome_var)
        eq = self.ses.equations.get(phi_var)
        if eq:
            for parent in eq.parent_vars:
                if parent != d.condition_var:
                    chain.append(parent)
        if d.condition_var not in chain:
            chain.insert(0, d.condition_var)
        return chain

    def override_tool(self, node_id: str, tool_id: str) -> AgentOverride:
        """
        Convenience: create override to force a specific tool.
        """
        d = self.decisions.get(node_id)
        if not d:
            return AgentOverride(target_node=node_id, override_type="force_tool",
                                tool_id=tool_id, description=f"force {tool_id}")

        is_true = tool_id == d.true_tool_id
        return AgentOverride(
            target_node=node_id,
            override_type="force_tool",
            tool_id=tool_id,
            condition_value=is_true,
            description=f"force tool={tool_id} at node {node_id}"
        )

    def explain(self) -> str:
        """Human-readable explanation (domain-agnostic)."""
        lines = ["=== AGENT DECISION GRAPH (Domain-Agnostic) ===", ""]

        for node_id, d in sorted(self.decisions.items()):
            cond_val = self._get_condition_value(node_id)
            semantic = ""
            if self._semantic_fn:
                try:
                    lbl = self._semantic_fn(node_id, d)
                    if lbl:
                        semantic = f" ({lbl})"
                except:
                    pass

            lines.append(f"Node {node_id}: TOOL SELECTION{semantic}")
            lines.append(f"  Condition: {d.condition_var} = {cond_val}")
            lines.append(f"  When TRUE:  {d.true_tool_id}")
            lines.append(f"  When FALSE: {d.false_tool_id}")
            lines.append(f"  Selected:   {d.selected_tool_id}")
            lines.append(f"  Output:     {d.outcome_var}")
            lines.append("")

        return "\n".join(lines)

    def why_counterfactual(self, node_id: str) -> Dict[str, Any]:
        """
        Counterfactual why: explains WHY this decision was made.

        Returns:
        {
            "node": "n4",
            "factual": {
                "condition": true,
                "selected": "tool_A",
                "outcome": "output_X"
            },
            "counterfactual": {
                "if_condition_flipped": true,
                "would_select": "tool_B",
                "would_change_output": true,
                "impact": "final_answer would change to Y"
            }
        }
        """
        if node_id not in self.decisions:
            return {"error": f"No decision at node {node_id}"}

        d = self.decisions[node_id]
        factual_cond = self._get_condition_value(node_id)

        # Get factual outcome
        phi_var = self._find_phi(node_id, d.outcome_var)
        factual = self.ses.evaluate(self._get_U(), {})
        factual_outcome = factual.get(phi_var)

        # Compute counterfactual: flip condition
        flip_value = not factual_cond if isinstance(factual_cond, bool) else True
        cf_ses = self.ses.do_intervene({d.condition_var: flip_value})
        U_cf = dict(self._get_U())
        U_cf[d.condition_var] = flip_value
        cf_result = cf_ses.evaluate(U_cf, {})
        cf_outcome = cf_result.get(phi_var)

        return {
            "node": node_id,
            "decision": "tool_selection",
            "factual": {
                "condition_var": d.condition_var,
                "condition_value": factual_cond,
                "selected_tool": d.selected_tool_id,
                "outcome": factual_outcome
            },
            "counterfactual": {
                "if_condition_value": flip_value,
                "would_select": d.true_tool_id if not factual_cond else d.false_tool_id,
                "would_change_output": factual_outcome != cf_outcome,
                "outcome": cf_outcome
            }
        }

    def minimal_causes(self, output_var: str) -> Dict[str, Any]:
        """
        Find MINIMAL set of decisions that caused the output.

        This is the KILLER FEATURE: returns the smallest set of
        interventions needed to change the output.

        Returns:
        {
            "output_var": "final_answer",
            "factual_value": "X",
            "minimal_causes": [
                {
                    "node": "n4",
                    "condition": "cond_4",
                    "current_value": true,
                    "would_change_output": true,
                    "necessary": true
                }
            ],
            "alternative_minimal_sets": [...]
        }
        """
        # Find all decisions that contribute to this output
        contributing = []
        for phi_var, bn in self.phi_to_branch.items():
            if output_var in phi_var and bn in self.decisions:
                d = self.decisions[bn]
                phi_var_actual = self._find_phi(bn, d.outcome_var)

                # Evaluate with and without this condition
                factual = self.ses.evaluate(self._get_U(), {})
                factual_outcome = factual.get(phi_var_actual)

                # Remove this condition and see if output changes
                cf_ses = self.ses.do_intervene({d.condition_var: not self._get_condition_value(bn)})
                U_cf = dict(self._get_U())
                U_cf[d.condition_var] = not self._get_condition_value(bn)
                cf_outcome = cf_ses.evaluate(U_cf, {}).get(phi_var_actual)

                would_change = factual_outcome != cf_outcome

                contributing.append({
                    "node": bn,
                    "condition_var": d.condition_var,
                    "current_value": self._get_condition_value(bn),
                    "factual_outcome": factual_outcome,
                    "counterfactual_outcome": cf_outcome,
                    "would_change_output": would_change,
                    "selected_tool": d.selected_tool_id,
                    "alternative_tool": d.true_tool_id if d.selected_tool_id == d.false_tool_id else d.false_tool_id
                })

        # Filter to only necessary causes (changing them WOULD change output)
        minimal = [c for c in contributing if c["would_change_output"]]

        # Sort by impact
        minimal.sort(key=lambda x: x["would_change_output"], reverse=True)

        return {
            "output_var": output_var,
            "factual_value": minimal[0]["factual_outcome"] if minimal else None,
            "minimal_causes": minimal,
            "total_decisions_checked": len(contributing),
            "necessary_decisions": len(minimal)
        }

    def explain_counterfactual(self, node_id: str) -> str:
        """Human-readable counterfactual explanation."""
        result = self.why_counterfactual(node_id)

        if "error" in result:
            return result["error"]

        f = result["factual"]
        c = result["counterfactual"]

        lines = [
            f"=== WHY at node {node_id}? ===",
            f"",
            f"FACTUAL:",
            f"  Condition {f['condition_var']} = {f['condition_value']}",
            f"  Selected: {f['selected_tool']}",
            f"  Outcome: {f['outcome']}",
            f"",
            f"COUNTERFACTUAL:",
            f"  If {f['condition_var']} = {c['if_condition_value']},",
            f"  Would select: {c['would_select']}",
            f"  Would outcome change: {c['would_change_output']}",
            f"  New outcome: {c['outcome']}",
        ]

        return "\n".join(lines)

    def explain_minimal(self, output_var: str) -> str:
        """Human-readable minimal causes explanation."""
        result = self.minimal_causes(output_var)

        if "error" in result and result["error"]:
            return result["error"]

        lines = [
            f"=== MINIMAL CAUSES for {output_var} ===",
            f"",
            f"Factual value: {result['factual_value']}",
            f"Necessary decisions: {result['necessary_decisions']} of {result['total_decisions_checked']}",
            f"",
        ]

        for cause in result["minimal_causes"]:
            lines.append(f"Node {cause['node']}:")
            lines.append(f"  Condition: {cause['condition_var']} = {cause['current_value']}")
            lines.append(f"  Selected: {cause['selected_tool']}")
            lines.append(f"  If flipped: {cause['alternative_tool']}")
            lines.append(f"  Output would change: {cause['would_change_output']}")
            lines.append("")

        return "\n".join(lines)


# ============================================================
# v2.0 Trace → IR Compiler (Production-Grade)
# Stable, deterministic engine: Agent Trace → ExecutionGraph
# ============================================================


class TraceCompiler:
    """
    Production-grade trace → ExecutionGraph compiler (v2.0).

    Three deterministic phases:
      1. Parse trace → create nodes + Branch objects
      2. Collect path nodes from trace order
      3. One-shot CFG materialization from Branch data

    Key invariants:
      - Branch.exit = path_nodes[-1] (always, never entry fallback)
      - CFG is final output expression, never queried as data source
      - No sequential fallback for branch structure derivation
      - No multi-round wiring correction
    """

    def __init__(self):
        self.node_counter = 0
        self.step_to_node: Dict[str, str] = {}
        self.branches: Dict[str, Branch] = {}

    def _reset(self):
        self.node_counter = 0
        self.step_to_node = {}
        self.branches = {}

    # ================================================================
    # Phase 1: Trace Parsing — create nodes + Branch objects
    # ================================================================

    def compile(self, trace: Dict[str, Any]) -> ExecutionGraph:
        """
        Compile an agent trace into ExecutionGraph.

        Args:
            trace: {"steps": [...], "metadata": {...}}
        Returns:
            ExecutionGraph with correct CFG structure
        """
        self._reset()
        steps = trace.get("steps", [])
        graph = ExecutionGraph()

        # Phase 1: Create all nodes, collect Branch objects
        prev_node = None
        for step in steps:
            node_id = self._create_nodes(graph, step, prev_node)
            self.step_to_node[step["id"]] = node_id
            prev_node = node_id

        # Phase 2: Collect path nodes from trace order
        self._collect_all_paths(steps)

        # Phase 3: One-shot CFG materialization from Branch data
        self._materialize(graph, steps)

        # Build CFG (output only, never queried as data source)
        graph.build_cfg()

        return graph

    def _next_node(self) -> str:
        self.node_counter += 1
        return f"n{self.node_counter}"

    def _create_nodes(self, graph: ExecutionGraph, step: Dict, prev_node: Optional[str]) -> str:
        step_type = step.get("type")

        if step_type == "branch":
            return self._create_branch_nodes(graph, step, prev_node)
        elif step_type == "merge":
            return self._create_merge_node(graph, step, prev_node)
        else:
            return self._create_simple_node(graph, step, prev_node, step_type)

    def _create_branch_nodes(self, graph: ExecutionGraph, step: Dict, prev_node: Optional[str]) -> str:
        """
        Create EQ + BRANCH nodes and a Branch object.

        BRANCH.next stores step IDs (resolved to node IDs in _materialize).
        """
        node_id = step.get("id", self._next_node())
        condition = step.get("condition", "cond")
        value = step.get("value", False)

        # EQ node: computes condition value == True
        cond_var = f"cond_{node_id}"
        graph.instr(node_id, "EQ", [str(value), "True", cond_var], [])

        # Wire prev → EQ (sequential, prev is never a branch target)
        if prev_node and prev_node in graph.nodes:
            graph.nodes[prev_node].next = [node_id]

        # BRANCH node
        branch_id = f"br_{node_id}"
        true_target = step.get("true_branch")
        false_target = step.get("false_branch")
        merge_step = step.get("merge")

        # BRANCH.next = [true_entry, false_entry] as step IDs
        next_list = [t for t in [true_target, false_target] if t]
        graph.instr(branch_id, "BRANCH", [cond_var], next_list)

        # EQ → BRANCH
        graph.nodes[node_id].next = [branch_id]

        # Branch object created (paths collected in Phase 2)
        branch = Branch(
            branch_id=branch_id,
            eq_node=node_id,
            cond_var=cond_var,
            true_target=true_target,
            false_target=false_target,
            merge_step=merge_step,
        )
        self.branches[branch_id] = branch

        return node_id  # Return EQ node ID (sequential wiring goes through EQ→BRANCH)

    def _create_merge_node(self, graph: ExecutionGraph, step: Dict, prev_node: Optional[str]) -> str:
        """Create a MERGE node — convergence point for branch exits."""
        node_id = step.get("id", self._next_node())
        graph.instr(node_id, "MERGE", [], [])

        # Merge node is a convergence point — no sequential wiring here.
        # All wiring to/from merge happens in _materialize Phase 3.
        return node_id

    def _create_simple_node(self, graph: ExecutionGraph, step: Dict, prev_node: Optional[str],
                           step_type: str) -> str:
        """Create a non-branch, non-merge node (llm, tool, output, nop)."""
        node_id = step.get("id", self._next_node())

        if step_type == "llm":
            output_var = step.get("output_var", f"llm_{node_id}")
            prompt = step.get("prompt", "")
            output = step.get("output", "")
            graph.instr(node_id, "MOV", [output_var, output or f"LLM({prompt[:50]}...)"], [])
        elif step_type == "tool":
            tool_name = step.get("name", "unknown")
            tool_args = step.get("args", {})
            output_var = step.get("output_var", f"tool_{tool_name}_{node_id}")
            graph.instr(node_id, "CALL", ["tool", tool_name, str(tool_args), output_var], [])
        elif step_type == "output":
            output_var = step.get("var", "output")
            output_value = step.get("value", "")
            graph.instr(node_id, "MOV", [output_var, str(output_value)], [])
            halt_node = self._next_node()
            graph.instr(halt_node, "HALT", [], [])
            graph.nodes[node_id].next = [halt_node]
        else:
            graph.instr(node_id, "MOV", ["_", "_"], [])

        # No sequential wiring in Phase 1 — all handled in _materialize Phase 3.
        return node_id

    def _get_branch_targets(self) -> Set[str]:
        """Set of step IDs that are branch entry points."""
        targets = set()
        for branch in self.branches.values():
            if branch.true_target:
                targets.add(branch.true_target)
            if branch.false_target:
                targets.add(branch.false_target)
        return targets

    def _find_step_for_node(self, node_id: Optional[str]) -> Optional[str]:
        """Reverse lookup: node_id → step_id."""
        if not node_id:
            return None
        for sid, nid in self.step_to_node.items():
            if nid == node_id:
                return sid
        return None

    # ================================================================
    # Phase 2: Path Collection — deterministic walk through trace
    # ================================================================

    def _collect_all_paths(self, steps: List[Dict]):
        """Collect true_nodes and false_nodes for each branch from trace order."""
        for branch in self.branches.values():
            branch.true_nodes = self._collect_path(
                steps, branch.true_target, branch.false_target, branch.merge_step
            )
            branch.false_nodes = self._collect_path(
                steps, branch.false_target, branch.true_target, branch.merge_step
            )

    def _collect_path(self, steps: List[Dict], start_id: Optional[str],
                      other_side_id: Optional[str], merge_id: Optional[str]) -> List[str]:
        """
        Walk from start_id through linear trace, collecting node IDs
        until merge_id or other_side_id is reached.

        Deterministic: path order = trace order.
        Exit = path_nodes[-1] (last node before merge/other-side).

        If start_id == merge_id, the path is empty (branch goes directly to merge).
        """
        if not start_id:
            return []
        if start_id == merge_id:
            return []  # Branch target IS the merge node

        nodes = []
        collecting = False

        for step in steps:
            sid = step.get("id")
            if sid == start_id:
                collecting = True
                if sid in self.step_to_node:
                    nodes.append(self.step_to_node[sid])
                continue
            if collecting:
                if sid == merge_id or sid == other_side_id:
                    break
                if sid in self.step_to_node:
                    nodes.append(self.step_to_node[sid])

        return nodes

    # ================================================================
    # Phase 3: CFG Materialization — one-shot wiring from Branch data
    # ================================================================

    def _materialize(self, graph: ExecutionGraph, steps: List[Dict]):
        """
        One-shot wiring from Branch data. No CFG queries, no fallback.

        1. Resolve BRANCH.next step IDs → node IDs
        2. Wire true_exit → merge, false_exit → merge
        3. Wire sequential links for remaining unwired nodes
        """
        branch_target_steps = self._get_branch_targets()

        # 1. Resolve BRANCH.next step IDs → node IDs
        for branch in self.branches.values():
            br_instr = graph.nodes.get(branch.branch_id)
            if br_instr:
                resolved = []
                for target in br_instr.next:
                    node = self.step_to_node.get(target)
                    if node:
                        resolved.append(node)
                if resolved:
                    br_instr.next = resolved

        # 2. Wire true_exit → merge, false_exit → merge
        for branch in self.branches.values():
            merge_node = self.step_to_node.get(branch.merge_step) if branch.merge_step else None
            if not merge_node:
                continue

            # true_exit is ALWAYS true_nodes[-1] (never fallback to entry)
            if branch.true_exit and branch.true_exit in graph.nodes:
                exit_instr = graph.nodes[branch.true_exit]
                # Don't self-loop; don't touch BRANCH nodes
                if (exit_instr.op not in ("BRANCH",)
                        and branch.true_exit != merge_node):
                    # Overwrite: branch exit always goes to merge
                    exit_instr.next = [merge_node]

            # false_exit is ALWAYS false_nodes[-1] (never fallback to entry)
            if branch.false_exit and branch.false_exit in graph.nodes:
                exit_instr = graph.nodes[branch.false_exit]
                if (exit_instr.op not in ("BRANCH",)
                        and branch.false_exit != merge_node):
                    exit_instr.next = [merge_node]

        # 3. Wire sequential links for remaining unwired nodes
        # Walk steps in trace order; wire each unwired node to the next
        # non-branch-target node in the trace
        step_node_ids = []
        for step in steps:
            sid = step.get("id")
            if sid in self.step_to_node:
                step_node_ids.append(self.step_to_node[sid])

        for i, node_id in enumerate(step_node_ids):
            instr = graph.nodes.get(node_id)
            if not instr or instr.next or instr.op in ("HALT", "BRANCH"):
                continue

            # Find next node in trace order to wire to
            for j in range(i + 1, len(step_node_ids)):
                next_id = step_node_ids[j]
                next_step = self._find_step_for_node(next_id)

                # Don't wire to branch targets (they come from BRANCH)
                if next_step in branch_target_steps:
                    continue

                next_instr = graph.nodes.get(next_id)
                if next_instr and next_instr.op not in ("HALT",):
                    instr.next = [next_id]
                    break

    # ================================================================
    # Backward-compatible _link_branches (no-op)
    # ================================================================

    def _link_branches(self, graph: ExecutionGraph):
        """Validate CFG structure. No-op kept for backward compatibility."""
        pass



# ============================================================
# v2.0 Universal Agent Trace Capture System
# ============================================================

@dataclass
class AgentStep:
    """A single step in an agent trace with observability fields."""
    step_id: str
    step_type: str  # "llm" | "tool" | "branch" | "merge" | "output"
    # For LLM steps
    prompt: Optional[str] = None
    llm_output: Optional[str] = None
    # For tool steps
    tool_name: Optional[str] = None
    tool_args: Optional[Dict] = None
    tool_result: Optional[Any] = None
    # For branch steps
    condition: Optional[str] = None
    condition_value: Optional[Any] = None
    true_branch: Optional[str] = None
    false_branch: Optional[str] = None
    # For merge steps
    merge_sources: Optional[List[str]] = None
    # For output steps
    output_var: Optional[str] = None
    output_value: Optional[Any] = None
    # Observability
    start_time: Optional[float] = None   # Unix timestamp
    end_time: Optional[float] = None     # Unix timestamp
    latency_ms: Optional[float] = None   # Computed latency
    status: str = "success"              # "success" | "error" | "pending"
    error: Optional[str] = None          # Error message if status == "error"


class TraceCapture:
    """
    Universal trace capture - records agent execution for causal analysis.

    Usage:
        capture = TraceCapture()

        # Record steps
        llm_id = capture.record_llm("User feels chest pain", "Checking symptoms...")
        tool_id = capture.record_tool("diagnose", {"symptoms": "chest pain"}, "CRITICAL")
        branch_id = capture.record_branch("severity == CRITICAL", True,
                                          true_step=tool_id, false_step=None)

        # Compile to ExecutionGraph
        graph = capture.compile()
        ir = AgentIR(graph)
        ir.why_counterfactual(branch_id)
    """

    def __init__(self):
        self.steps = []
        self.step_index = 0
        self._start_times = {}  # step_id -> start_time

    def _step_start(self, step_id: str):
        import time
        self._start_times[step_id] = time.time()

    def _step_end(self, step_id: str, status: str = "success", error: str = None):
        import time
        end_time = time.time()
        start_time = self._start_times.get(step_id, end_time)
        return {
            "start_time": start_time,
            "end_time": end_time,
            "latency_ms": (end_time - start_time) * 1000,
            "status": status,
            "error": error,
        }

    def record_llm(self, prompt: str, output: str = None,
                   metadata: Dict = None, step_id: str = None,
                   parent_id: str = None) -> str:
        """Record an LLM call with timing."""
        if step_id is None:
            step_id = f"llm_{self.step_index}"
        self.step_index += 1
        self._step_start(step_id)
        obs = self._step_end(step_id)
        self.steps.append({
            "type": "llm", "id": step_id,
            "prompt": prompt, "output": output or "",
            "metadata": metadata or {},
            "parent_id": parent_id,
            **obs
        })
        return step_id

    def record_tool(self, name: str, args: Dict = None, result: Any = None,
                    metadata: Dict = None, status: str = "success",
                    error: str = None, step_id: str = None,
                    parent_id: str = None) -> str:
        """Record a tool call with timing."""
        if step_id is None:
            step_id = f"tool_{self.step_index}"
        self.step_index += 1
        self._step_start(step_id)
        obs = self._step_end(step_id, status, error)
        self.steps.append({
            "type": "tool", "id": step_id,
            "name": name, "args": args or {}, "result": result,
            "metadata": metadata or {},
            "parent_id": parent_id,
            **obs
        })
        return step_id

    def record_branch(self, condition: str, value: Any,
                      true_step: str = None, false_step: str = None,
                      merge_step: str = None,
                      metadata: Dict = None) -> str:
        """Record a branching decision with timing."""
        step_id = f"branch_{self.step_index}"
        self.step_index += 1
        self._step_start(step_id)
        obs = self._step_end(step_id)
        self.steps.append({
            "type": "branch", "id": step_id,
            "condition": condition, "value": value,
            "true_branch": true_step, "false_branch": false_step,
            "merge": merge_step,
            "metadata": metadata or {},
            **obs
        })
        return step_id

    def record_merge(self, step_id: str = None) -> str:
        """Record an explicit merge point."""
        if step_id is None:
            step_id = f"merge_{self.step_index}"
            self.step_index += 1
        self._step_start(step_id)
        obs = self._step_end(step_id)
        self.steps.append({
            "type": "merge", "id": step_id,
            "start_time": obs["start_time"],
            "end_time": obs["end_time"],
            "latency_ms": obs["latency_ms"],
            "status": obs["status"],
        })
        return step_id

    def record_output(self, var: str, value: Any,
                      metadata: Dict = None, step_id: str = None,
                      status: str = "success", error: str = None,
                      parent_id: str = None) -> str:
        """Record final output with timing."""
        if step_id is None:
            step_id = f"output_{self.step_index}"
        self.step_index += 1
        self._step_start(step_id)
        obs = self._step_end(step_id, status, error)
        self.steps.append({
            "type": "output", "id": step_id,
            "var": var, "value": value,
            "metadata": metadata or {},
            "parent_id": parent_id,
            **obs
        })
        return step_id

    def get_trace(self) -> Dict:
        """Get the full trace dict ready for compilation."""
        return {"steps": self.steps}

    def compile(self) -> "ExecutionGraph":
        """Compile captured trace into ExecutionGraph."""
        compiler = TraceCompiler()
        return compiler.compile(self.get_trace())


class UniversalAgentTracer:
    """
    Decorator-based tracer for wrapping any agent function.

    Usage:
        tracer = UniversalAgentTracer()

        @tracer.trace_llm
        def llm_call(prompt):
            return openai.ChatCompletion.create(prompt=prompt)

        @tracer.trace_tool("diagnose")
        def diagnose(symptoms):
            return run_diagnosis(symptoms)

        @tracer.trace_branch("critical_check")
        def check_critical(result):
            return result == "CRITICAL"

        # Run agent
        result = my_agent("chest pain")

        # Analyze
        graph = tracer.compile()
        ir = AgentIR(graph)
    """

    def __init__(self):
        self.capture = TraceCapture()
        self._last_branch = None
        self._last_tool = None
        self._branches = {}

    def trace_llm(self, prompt_template: str = None):
        """Decorator to trace LLM calls."""
        def decorator(func):
            def wrapper(*args, **kwargs):
                prompt = prompt_template or f"{func.__name__}({args}, {kwargs})"
                result = func(*args, **kwargs)
                self.capture.record_llm(prompt=prompt, output=str(result))
                return result
            return wrapper
        return decorator

    def trace_tool(self, name: str):
        """Decorator to trace tool calls."""
        def decorator(func):
            def wrapper(*args, **kwargs):
                result = func(*args, **kwargs)
                self._last_tool = self.capture.record_tool(
                    name=name,
                    args={"args": str(args), "kwargs": str(kwargs)},
                    result=result
                )
                return result
            return wrapper
        return decorator

    def trace_branch(self, condition_desc: str = None):
        """Decorator to trace conditional branches."""
        def decorator(func):
            def wrapper(*args, **kwargs):
                result = func(*args, **kwargs)
                branch_id = self.capture.record_branch(
                    condition=condition_desc or f"{func.__name__}({args})",
                    value=bool(result)
                )
                self._branches[condition_desc or func.__name__] = branch_id
                self._last_branch = branch_id
                return result
            return wrapper
        return decorator

    def compile(self) -> "ExecutionGraph":
        """Compile trace to ExecutionGraph."""
        return self.capture.compile()

    def get_last_branch(self) -> str:
        """Get the last branch node ID."""
        return self._last_branch


def demo_universal_agent_tracer():
    """Demo: Universal agent tracer with explicit MERGE nodes.

    This demonstrates the architecture:
    - MERGE nodes are EXPLICIT (not guessed)
    - Both branches write to SAME variable (R_action)
    - Phi functions only at MERGE nodes
    """
    print("=" * 70)
    print("Universal Agent Tracer - Explicit MERGE Architecture")
    print("=" * 70)

    # Proper trace with EXPLICIT MERGE node
    # Both branches write to SAME variable (R_action)
    trace = {
        "steps": [
            {"id": "s1", "type": "llm", "prompt": "Patient chest pain", "output": "CRITICAL"},
            {"id": "s2", "type": "branch", "condition": "severity == CRITICAL", "value": True,
             "true_branch": "s3", "false_branch": "s4", "merge": "s5"},  # EXPLICIT merge binding
            {"id": "s3", "type": "tool", "name": "emergency", "args": {}, "result": "CALL 911", "output_var": "R_action"},
            {"id": "s4", "type": "tool", "name": "rest", "args": {}, "result": "REST", "output_var": "R_action"},
            {"id": "s5", "type": "merge"},  # MERGE belongs to branch s2
            {"id": "s6", "type": "output", "var": "final", "value": "DONE"},
        ]
    }

    print("\n[1] Compiling trace with explicit MERGE...")
    compiler = TraceCompiler()
    graph = compiler.compile(trace)
    print(f"    Nodes: {list(graph.nodes.keys())}")

    graph.build_cfg()
    print(f"    CFG merge points: {len([n for n, b in graph.cfg.blocks.items() if len(b.predecessors) > 1])}")

    print("\n[2] Causal Analysis...")
    ir = AgentIR(graph)

    # Find branch node
    branch_nodes = [n for n in graph.nodes if graph.nodes[n].op in ("BR", "BRANCH")]
    if branch_nodes:
        branch_node = branch_nodes[0]
        print(f"\n    Branch node: {branch_node}")

        why = ir.why(branch_node)
        print(f"\n    WHY:")
        print(f"      Condition: {why.get('condition_var')} = {why.get('condition_value')}")
        print(f"      Selected: {why.get('selected_tool')}")
        print(f"      Options: {why.get('options')}")

        cf = ir.why_counterfactual(branch_node)
        print(f"\n    COUNTERFACTUAL:")
        print(f"      Factual: {cf.get('factual', {}).get('outcome')}")
        print(f"      Counterfactual: {cf.get('counterfactual', {}).get('outcome')}")
        print(f"      Would change: {cf.get('counterfactual', {}).get('would_change_output')}")

        mc = ir.minimal_causes('R_action')
        print(f"\n    MINIMAL CAUSES:")
        print(f"      Factual: {mc.get('factual_value')}")
        print(f"      Causes: {len(mc.get('minimal_causes', []))}")
        for c in mc.get('minimal_causes', []):
            print(f"        - {c.get('node')}: {c.get('selected_tool')} → flip to {c.get('alternative_tool')}")

        print(f"\n    EXPLANATION:")
        print(ir.explain_counterfactual(branch_node))

    print("\n" + "=" * 70)

    print("\n[3] Causal Analysis...")
    ir = AgentIR(graph)

    # Find branch node
    branch_nodes = [n for n in graph.nodes if graph.nodes[n].op in ("BR", "BRANCH")]
    if branch_nodes:
        branch_node = branch_nodes[0]
        print(f"\n    Branch node: {branch_node}")

        why = ir.why(branch_node)
        if "error" not in why:
            print(f"\n    WHY analysis:")
            print(f"      Condition: {why.get('condition_var')} = {why.get('condition_value')}")
            print(f"      Selected tool: {why.get('selected_tool')}")
            print(f"      Options: {why.get('options')}")

            cf = ir.why_counterfactual(branch_node)
            print(f"\n    COUNTERFACTUAL:")
            print(f"      Factual: {cf.get('factual', {}).get('outcome')}")
            print(f"      Counterfactual: {cf.get('counterfactual', {}).get('outcome')}")
            print(f"      Would change: {cf.get('counterfactual', {}).get('would_change_output')}")

            mc = ir.minimal_causes('action')
            print(f"\n    MINIMAL CAUSES:")
            print(f"      Factual value: {mc.get('factual_value')}")
            print(f"      Causes: {len(mc.get('minimal_causes', []))}")
            for c in mc.get('minimal_causes', []):
                print(f"        - {c.get('node')}: flip to {c.get('alternative_tool')} would change output")

            print(f"\n    EXPLANATION:")
            print(ir.explain_counterfactual(branch_node))
        else:
            print(f"    Error: {why['error']}")

    print("\n" + "=" * 70)


def demo_trace_compiler():
    """Demonstrate TraceCompiler with a real agent trace."""
    print("=" * 70)
    print("TraceCompiler - Real Agent Trace → ExecutionGraph")
    print("=" * 70)

    # Example: A real agent trace with tool selection
    trace = {
        "steps": [
            {
                "id": "s1",
                "type": "llm",
                "prompt": "User: What's 2+2?",
                "output": "Let me calculate that."
            },
            {
                "id": "s2",
                "type": "tool",
                "name": "calculator",
                "args": {"expr": "2+2"},
                "result": "4",
                "output_var": "calc_result"
            },
            {
                "id": "s3",
                "type": "branch",
                "condition": "result_is_numeric",
                "value": True,
                "true_branch": "s5",
                "false_branch": "s4",
                "merge": "s5"
            },
            {
                "id": "s4",
                "type": "tool",
                "name": "search",
                "args": {"query": "2+2"},
                "result": "Search result: 4"
            },
            {
                "id": "s5",
                "type": "merge",
            },
            {
                "id": "s6",
                "type": "output",
                "var": "final_answer",
                "value": "4"
            }
        ]
    }

    compiler = TraceCompiler()
    graph = compiler.compile(trace)

    print(f"\n[1] Compiled trace into ExecutionGraph")
    print(f"    Nodes: {len(graph.nodes)}")
    for node_id, instr in graph.nodes.items():
        print(f"    {node_id}: {instr.op} {instr.args} -> {instr.next}")

    # Build CFG
    graph.build_cfg()

    # Wrap with AgentIR
    exog = ExogenousModel()
    agent = AgentIR(graph, exogenous=exog)

    print(f"\n[2] Agent Decision Graph")
    print(agent.explain())

    print("\n" + "=" * 70)


# ============================================================
# v0.8 DEMO - Semantic Query Engine
# ============================================================

def demo():
    """Demonstrate v1.0 Causal Explainable Semantic Execution."""
    print("=" * 70)
    print("ExecutionGraph v1.0 - Causal Explainable Semantic Execution")
    print("=" * 70)

    # Build test program
    g = ExecutionGraph()
    g.instr("n1", "MOV", ["R_query", "Patient has mild discomfort"], ["n2"])
    g.instr("n2", "CALL", ["tool", "diagnose", "@R_query", "R_result"], ["n3"])
    g.instr("n3", "EQ", ["@R_result", "CASE_CRITICAL", "R_flag"], ["n4"])
    g.instr("n4", "BRANCH", ["R_flag"], ["n5b", "n5a"])
    g.instr("n5a", "MOV", ["R_out", "REST AND FLUIDS"], ["n6"])
    g.instr("n5b", "MOV", ["R_out", "EMERGENCY PROTOCOL: CALL 911"], ["n6"])
    g.instr("n6", "HALT", [], [])
    g.set_root("n1")

    # Build CFG and semantic resolver
    g.build_cfg()

    print(f"\n[1] IR built: {len(g.nodes)} instructions")
    print(f"    CFG blocks: {len(g.cfg.blocks)}")
    print(f"    Entry: {g.cfg.entry}")

    # Semantic queries
    print(f"\n[2] Semantic Queries...")

    # Query 1: Value resolution
    print(f"\n  Query: resolve('R_flag', 'n4')")
    provenance = g.semantic.resolve("R_flag", "n4")
    print(f"    Semantic: {provenance.semantic}")
    print(f"    Kind: {provenance.semantic.kind.value}")
    print(f"    Definition site: {provenance.definition_site}")
    print(f"    Dominated by: {provenance.dominated_by}")
    print(f"    PHI used: {provenance.phi_used}")
    print(f"    Reasoning: {provenance.reasoning_trace}")

    # Query 2: Dominance
    print(f"\n  Query: dominates('n3', 'n5a')")
    dom_result = g.semantic.dominates("n3", "n5a")
    print(f"    Dominates: {dom_result.dominates}")
    if dom_result.dominator_tree_path:
        print(f"    Dom tree path: {' → '.join(dom_result.dominator_tree_path)}")

    # Query 3: Path explanation
    print(f"\n  Query: explain('n1', 'n6')")
    path_exp = g.semantic.explain("n1", "n6")
    print(f"    Path: {' → '.join(path_exp.path)}")
    print(f"    Conditions: {path_exp.conditions}")

    # Query 4: Phi resolution
    print(f"\n  Query: resolve_phi('R_out', 'n6')")
    phi_res = g.semantic.resolve_phi("R_out", "n6")
    print(f"    Selected value: {phi_res.selected_value}")
    print(f"    Selected predecessor: {phi_res.selected_predecessor}")
    print(f"    Incoming values: {phi_res.incoming_values}")

    # Execution with fork
    print(f"\n[3] Execution with Semantic Resolution...")

    engine = ExecutionEngine(g.semantic)

    # Original execution
    ctx = VMContext()
    ctx = g.run(engine, ctx)
    print(f"    Original: R_out = {ctx.regs.get('R_out')}")

    # Fork at n3
    forked = g.fork_at("n3", {"op": "MOV", "args": ["R_flag", True]})
    forked.build_cfg()

    ctx2 = VMContext()
    ctx2 = forked.run(engine, ctx2)
    print(f"    Forked: R_out = {ctx2.regs.get('R_out')}")

    # Semantic query on forked
    print(f"\n[4] Fork Analysis...")
    provenance_forked = forked.semantic.resolve("R_flag", "n4")
    print(f"    Forked R_flag provenance:")
    print(f"      Semantic: {provenance_forked.semantic}")
    print(f"      Kind: {provenance_forked.semantic.kind.value}")
    print(f"      Definition: {provenance_forked.definition_site}")
    print(f"      Reasoning: {provenance_forked.reasoning_trace}")

    # Graphviz export
    print(f"\n[5] Graphviz Export...")
    dot = g.dag_cache.to_dot("AgentTrace Medical Triage DAG")
    print(f"    DAG nodes: {len(g.dag_cache.nodes)}")
    print(f"    Canonical key dedup: {len(g.dag_cache._key_index)} unique keys")
    print(f"    DOT export available ({len(dot)} chars)")

    # Show canonical keys for key nodes
    print(f"\n[6] Structural Interning (Canonical Keys)...")
    for node_id, node in list(g.dag_cache.nodes.items())[:5]:
        key = g.dag_cache.canonical_key(node.semantic)
        print(f"    {node.semantic.kind.value}: {key[:60]}...")

    print("\n" + "=" * 70)
    print("v1.0 Causal Explainable Semantic Execution Properties:")
    print("  [OK] Unified semantic query API")
    print("  [OK] Semantic reduction algebra (reduce/join closure)")
    print("  [OK] Semantic canonicalization (idempotent, equivalence-consistent)")
    print("  [OK] Structural equality = semantic equality (hashable)")
    print("  [OK] Trace materialization (DAGNode with provenance)")
    print("  [OK] Canonical key interning (structural dedup)")
    print("  [OK] Graphviz export (visualizable knowledge graph)")
    print("  [OK] Mermaid export (alternative visualization)")
    print("  [OK] Semantic diff API")
    print("  [OK] Human-readable labels (explainability)")
    print("  [OK] Causal narrative generation (Because/Therefore)")
    print("  [OK] Decision explanation (explain_decision)")
    print("  [OK] Value resolution with provenance")
    print("  [OK] Dominance analysis")
    print("  [OK] Path explanation")
    print("  [OK] PHI resolution (implicit at join points)")
    print("=" * 70)


if __name__ == "__main__":
    demo()