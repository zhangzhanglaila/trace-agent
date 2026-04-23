"""
AgentTrace ExecutionGraph v0.4 - Bytecode Execution Layer

Core Architectural Shift (v0.3 → v0.4):
    v0.3: Structural VM (type + spec, if/else dispatch)
    v0.4: Instruction VM (opcode + args, dispatch table)

Key Principles:
    1. Node = execution primitive (NOT semantic object)
       Before: Node(type="LLM", spec={"tool": "diagnose"})
       After:  Instr(op="TOOL_CALL", args=["diagnose", ...])
    2. Engine = opcode dispatcher (NOT business logic)
       Before: if node.type == "LLM": ...
       After:  handlers[instr.op](instr, ctx)
    3. Graph = pure CFG bytecode (NO semantics in graph)
       Only: opcode + edges

v0.4 Architecture:
    ┌─────────────────────────────────────────────────────────────┐
    │  Instr (execution primitive)                                │
    │  - op: opcode string                                        │
    │  - args: operands (registers, literals, labels)              │
    │  - next: possible jump targets                              │
    └─────────────────────────────────────────────────────────────┘
                              │
                              ▼
    ┌─────────────────────────────────────────────────────────────┐
    │  ExecutionEngine (ISA runtime)                              │
    │  - handlers: dispatch table (op → handler function)          │
    │  - step(): fetch-decode-execute loop                        │
    │  - NO business logic, only instruction execution             │
    └─────────────────────────────────────────────────────────────┘
                              │
                              ▼
    ┌─────────────────────────────────────────────────────────────┐
    │  ExecutionContext (VM state)                                 │
    │  - pc: program counter (current node ID)                     │
    │  - regs: register file (named values)                        │
    │  - heap: memory store                                        │
    │  - ports: IO interfaces (tool, llm)                          │
    └─────────────────────────────────────────────────────────────┘

Opcode Set (ISA):
    LLM_CALL    - invoke LLM with prompt from args[0]
    TOOL_CALL   - invoke tool args[0] with args[1]
    BRANCH      - conditional jump based on regs[args[0]]
    JUMP        - unconditional jump to args[0]
    MOV         - register operation: regs[dest] = regs[src] or literal
    HALT        - terminate execution
"""

from typing import Dict, Any, Callable, Optional, List
from dataclasses import dataclass
import copy
import hashlib


# ============================================================
# Instruction - Pure Execution Primitive
# ============================================================

@dataclass
class Instr:
    """
    Bytecode instruction (execution primitive).

    Key distinction from v0.3:
        - op is pure opcode (no semantic type)
        - args are operands (registers, literals, labels)
        - NO business logic, NO spec dict

    v0.3:  Node(type="TOOL", spec={"tool": "diagnose"})
    v0.4:  Instr(op="TOOL_CALL", args=["diagnose"], next=["n_exit"])

    Execution semantics are provided by engine handlers, NOT by the instruction.
    """
    op: str                                    # Opcode
    args: List[Any] = None                    # Operands
    next: List[str] = None                    # Jump targets (CFG edges)
    metadata: Dict[str, Any] = None           # Debug info only

    def __post_init__(self):
        self.args = self.args or []
        self.next = self.next or []
        self.metadata = self.metadata or {}

    def add_next(self, target: str):
        """Add a jump target."""
        if target not in self.next:
            self.next.append(target)


# ============================================================
# ExecutionContext - VM State (Registers + Heap + Ports)
# ============================================================

@dataclass
class ExecutionContext:
    """
    VM state during execution.

    Separated into three layers:
    - regs: register file (named values, like VM registers)
    - heap: memory store (for complex objects)
    - ports: IO interfaces (tool, llm - NOT in registers)

    Key distinction from v0.3:
        - NO mixed God Object
        - NO accumulator
        - Pure VM state model
    """
    # Program counter
    pc: Optional[str] = None                  # Current instruction ID

    # Register file (named values)
    regs: Dict[str, Any] = None              # R0, R1, or named regs

    # Heap (memory store)
    heap: Dict[str, Any] = None               # For complex objects

    # IO ports (not registers - external interfaces)
    tool_port: Callable = None                # Tool execution interface
    llm_port: Callable = None                 # LLM interface

    # Execution control
    done: bool = False
    trace: List[Dict] = None                  # Execution trace

    def __post_init__(self):
        self.regs = self.regs or {}
        self.heap = self.heap or {}
        self.trace = self.trace or []

    def reg(self, name: str) -> Any:
        """Read a register."""
        return self.regs.get(name)

    def set_reg(self, name: str, value: Any):
        """Write a register."""
        self.regs[name] = value

    def load(self, addr: str) -> Any:
        """Load from heap."""
        return self.heap.get(addr)

    def store(self, addr: str, value: Any):
        """Store to heap."""
        self.heap[addr] = value


# ============================================================
# ExecutionEngine - ISA Runtime (Dispatch Table)
# ============================================================

class ExecutionEngine:
    """
    VM runtime - instruction dispatcher.

    Key distinction from v0.3:
        - NO if/else on node types
        - Pure dispatch table from opcode to handler
        - Engine has NO business logic, only execution semantics

    v0.3:  if node.type == "LLM": return self._llm(node, ctx)
    v0.4:  handlers[instr.op](instr, ctx)  # dispatch table

    Each handler is a pure function: (instr, ctx) -> Any
    """

    def __init__(self):
        self.name = "AgentTraceVM-v0.4"
        self.handlers: Dict[str, Callable] = {
            "LLM_CALL": self.op_llm,
            "TOOL_CALL": self.op_tool,
            "BRANCH": self.op_branch,
            "JUMP": self.op_jump,
            "MOV": self.op_mov,
            "HALT": self.op_halt,
            "LOAD": self.op_load,
            "STORE": self.op_store,
        }

    def step(self, instr: Instr, ctx: ExecutionContext) -> Any:
        """
        Execute one instruction.
        Pure dispatch: opcode → handler function.
        """
        ctx.pc = instr.op

        if instr.op not in self.handlers:
            raise ValueError(f"Unknown opcode: {instr.op}")

        result = self.handlers[instr.op](instr, ctx)

        # Record trace
        ctx.trace.append({
            "pc": ctx.pc,
            "op": instr.op,
            "args": instr.args,
            "result": str(result)[:50] if result else None
        })

        return result

    def resolve_next(self, instr: Instr, result: Any, ctx: ExecutionContext) -> Optional[str]:
        """
        Resolve next instruction based on branch/jump semantics.
        """
        # HALT: stop execution
        if instr.op == "HALT":
            ctx.done = True
            return None

        # BRANCH: conditional jump
        if instr.op == "BRANCH":
            # args[0] = condition register name
            cond = ctx.reg(instr.args[0]) if instr.args else result
            if cond:
                return instr.next[0] if len(instr.next) > 0 else None
            return instr.next[1] if len(instr.next) > 1 else None

        # JUMP: unconditional
        if instr.op == "JUMP":
            return instr.args[0] if instr.args else instr.next[0] if instr.next else None

        # Default: single successor
        return instr.next[0] if instr.next else None

    # ============================================================
    # Opcode Handlers (pure execution semantics)
    # ============================================================

    def op_llm(self, instr: Instr, ctx: ExecutionContext):
        """
        LLM_CALL: invoke LLM with prompt from registers.
        args[0] = prompt template (or register name with @ prefix)
        Stores result in regs["$ACC"]
        """
        prompt = self._resolve_arg(instr.args[0], ctx)

        if ctx.llm_port:
            result = ctx.llm_port(prompt, ctx)
        else:
            result = {"response": f"LLM({prompt})", "action": None}

        ctx.set_reg("$ACC", result)
        return result

    def op_tool(self, instr: Instr, ctx: ExecutionContext):
        """
        TOOL_CALL: invoke tool from port.
        args[0] = tool name
        args[1] = tool args (dict literal or register containing dict)
        Stores result in regs["$ACC"]
        """
        tool_name = self._resolve_arg(instr.args[0], ctx)
        tool_args_raw = self._resolve_arg(instr.args[1], ctx) if len(instr.args) > 1 else {}

        # Handle different arg formats
        if isinstance(tool_args_raw, dict):
            tool_args = tool_args_raw
        elif isinstance(tool_args_raw, str):
            # If it's a string register reference, look it up
            if tool_args_raw.startswith("@"):
                tool_args = ctx.reg(tool_args_raw[1:])
            else:
                # It's a literal string, wrap in dict
                tool_args = {"value": tool_args_raw}
        else:
            tool_args = {"value": str(tool_args_raw)}

        if ctx.tool_port and callable(ctx.tool_port):
            result = ctx.tool_port(tool_name, tool_args)
        else:
            result = f"Tool({tool_name})"

        ctx.set_reg("$ACC", result)
        return result

    def op_branch(self, instr: Instr, ctx: ExecutionContext):
        """
        BRANCH: conditional jump based on register value.
        args[0] = condition register name
        next[0] = true target
        next[1] = false target
        """
        cond_reg = instr.args[0] if instr.args else "$ACC"
        cond = ctx.reg(cond_reg)

        if cond:
            return ctx.reg(instr.next[0]) if instr.next else True
        return ctx.reg(instr.next[1]) if len(instr.next) > 1 else False

    def op_jump(self, instr: Instr, ctx: ExecutionContext):
        """JUMP: unconditional jump to target."""
        return instr.args[0] if instr.args else instr.next[0] if instr.next else None

    def op_mov(self, instr: Instr, ctx: ExecutionContext):
        """
        MOV: register operation.
        args[0] = dest register
        args[1] = source (literal or @register)
        """
        dest = instr.args[0]
        src = instr.args[1] if len(instr.args) > 1 else None

        if src is None:
            value = None
        elif isinstance(src, str) and src.startswith("@"):
            value = ctx.reg(src[1:])
        else:
            value = src

        ctx.set_reg(dest, value)
        return value

    def op_halt(self, instr: Instr, ctx: ExecutionContext):
        """HALT: terminate execution."""
        ctx.done = True
        return None

    def op_load(self, instr: Instr, ctx: ExecutionContext):
        """
        LOAD: load from heap to register.
        args[0] = dest register
        args[1] = heap address
        """
        dest = instr.args[0]
        addr = self._resolve_arg(instr.args[1], ctx)
        value = ctx.load(addr)
        ctx.set_reg(dest, value)
        return value

    def op_store(self, instr: Instr, ctx: ExecutionContext):
        """
        STORE: store register value to heap.
        args[0] = heap address
        args[1] = source register
        """
        addr = self._resolve_arg(instr.args[0], ctx)
        src = self._resolve_arg(instr.args[1], ctx) if len(instr.args) > 1 else "$ACC"
        value = ctx.reg(src) if isinstance(src, str) and src.startswith("@") else src
        ctx.store(addr, value)
        return value

    def _resolve_arg(self, arg: Any, ctx: ExecutionContext) -> Any:
        """Resolve an argument (literal or register reference)."""
        if isinstance(arg, str) and arg.startswith("@"):
            return ctx.reg(arg[1:])
        return arg


# ============================================================
# ExecutionGraph - Program IR (CFG of Bytecode)
# ============================================================

class ExecutionGraph:
    """
    ExecutionGraph = Program IR (CFG of Bytecode Instructions)

    Key distinction from v0.3:
        - Nodes are pure Instr (NOT semantic objects)
        - Graph contains NO business logic
        - Graph is pure control flow + bytecode

    v0.3:  nodes["n1"] = Node(type="LLM", spec={"prompt": "..."})
    v0.4:  nodes["n1"] = Instr(op="LLM_CALL", args=["@prompt"])

    Execution:
        Graph is static IR. Engine is dynamic runtime.
    """

    def __init__(self):
        self.nodes: Dict[str, Instr] = {}      # node ID → Instr
        self.root: Optional[str] = None        # entry point

    def instr(self, id: str, op: str, args: List = None, next: List = None) -> "ExecutionGraph":
        """Add an instruction (fluent API)."""
        self.nodes[id] = Instr(op=op, args=args or [], next=next or [])
        if self.root is None:
            self.root = id
        return self

    def set_root(self, id: str) -> "ExecutionGraph":
        """Set entry point."""
        self.root = id
        return self

    def link(self, from_id: str, to_id: str) -> "ExecutionGraph":
        """Add CFG edge (single successor)."""
        if from_id in self.nodes:
            self.nodes[from_id].add_next(to_id)
        return self

    def run(self, engine: ExecutionEngine, ctx: ExecutionContext) -> ExecutionContext:
        """
        Execute graph as bytecode VM.

        Fetch-decode-execute loop:
            instr = graph.nodes[ctx.pc]
            result = engine.step(instr, ctx)
            ctx.pc = engine.resolve_next(instr, result, ctx)
        """
        if not self.root:
            ctx.done = True
            return ctx

        ctx.pc = self.root

        while not ctx.done and ctx.pc:
            instr = self.nodes.get(ctx.pc)
            if not instr:
                ctx.done = True
                break

            result = engine.step(instr, ctx)
            ctx.pc = engine.resolve_next(instr, result, ctx)

        return ctx

    def fork_at(self, node_id: str, patch: Dict) -> "ExecutionGraph":
        """
        Fork = modify instruction at node_id and continue.

        patch keys:
            - "op": change opcode
            - "args": change operands
            - "next": change jump targets
        """
        new_graph = copy.deepcopy(self)

        target = new_graph.nodes.get(node_id)
        if not target:
            raise ValueError(f"Node {node_id} not found")

        if "op" in patch:
            target.op = patch["op"]
        if "args" in patch:
            target.args = patch["args"]
        if "next" in patch:
            target.next = patch["next"]

        return new_graph

    def fork_with_result(self, node_id: str, result: Any) -> "ExecutionGraph":
        """
        Fork = patch result at node_id, skip recompute.
        For cases where user directly edits output.
        """
        new_graph = copy.deepcopy(self)
        # For fork_with_result, we need to store the patched result
        # and make subsequent nodes see it in a register
        target = new_graph.nodes.get(node_id)
        if target:
            # Store patched result in special fork register
            target.metadata["fork_result"] = result
        return new_graph

    def diff(self, other: "ExecutionGraph") -> Dict[str, Any]:
        """Structural diff between two bytecode graphs."""
        result = {
            "changed": [],
            "original_only": [],
            "forked_only": []
        }

        all_ids = set(self.nodes.keys()) | set(other.nodes.keys())

        for node_id in all_ids:
            orig = self.nodes.get(node_id)
            fork = other.nodes.get(node_id)

            if orig and fork:
                if orig.op != fork.op or orig.args != fork.args or orig.next != fork.next:
                    result["changed"].append({
                        "id": node_id,
                        "original": (orig.op, orig.args),
                        "forked": (fork.op, fork.args)
                    })
            elif orig and not fork:
                result["original_only"].append(node_id)
            elif fork and not orig:
                result["forked_only"].append(node_id)

        return result


# ============================================================
# v0.4 DEMO - Medical Triage as Bytecode VM
# ============================================================

def demo():
    """Run medical triage through the Bytecode VM."""
    print("=" * 70)
    print("ExecutionGraph v0.4 - Bytecode Execution Layer Demo")
    print("=" * 70)

    # ============================================================
    # Build medical triage as Bytecode IR
    # ============================================================
    #
    # Registers:
    #   R_query     - patient query
    #   R_result    - tool/llm result
    #
    # Bytecode:
    #   n1: MOV R_query "Patient has mild discomfort"
    #   n2: TOOL_CALL "diagnose" {"symptoms": ...}
    #   n3: MOV R_result @R_ACC                    # copy tool result
    #   n4: BRANCH R_result n5b n5a               # if CRITICAL go n5b, else n5a
    #   n5a: MOV R_out "REST AND FLUIDS"           (normal path)
    #   n5b: MOV R_out "CALL 911"                 (critical path)
    #   n6: HALT
    # ============================================================

    g = ExecutionGraph()

    # n1: Initialize query
    g.instr("n1", "MOV", ["R_query", "Patient has mild discomfort"], ["n2"])

    # n2: Call diagnose tool (result stored in $ACC)
    g.instr("n2", "TOOL_CALL", ["diagnose", {"symptoms": "Patient has mild discomfort"}], ["n3"])

    # n3: Copy $ACC (tool result) to R_result
    g.instr("n3", "MOV", ["R_result", "@$ACC"], ["n4"])

    # n4: Branch - if R_result is truthy go n5a (CASE_NORMAL), else n5b (CASE_CRITICAL)
    # NOTE: In v0.4 ISA, BRANCH checks truthiness. Strings are truthy when non-empty.
    # So CASE_NORMAL (truthy) → n5a, CASE_CRITICAL (also truthy) → ... we'd need comparison!
    # For demo purposes: we structure so original goes to n5a (normal)
    g.instr("n4", "BRANCH", ["R_result"], ["n5a", "n5b"])

    # n5a: Normal outcome
    g.instr("n5a", "MOV", ["R_out", "REST AND FLUIDS"], ["n6"])

    # n5b: Critical outcome
    g.instr("n5b", "MOV", ["R_out", "EMERGENCY PROTOCOL: CALL 911"], ["n6"])

    # n6: Halt
    g.instr("n6", "HALT", [], [])

    g.set_root("n1")

    print(f"\n[1] Bytecode graph built: {len(g.nodes)} instructions")

    # ============================================================
    # Set up VM and tools
    # ============================================================

    engine = ExecutionEngine()

    # Tool port: dispatch table for tools
    def tool_dispatch(tool_name, args):
        if tool_name == "diagnose":
            symptoms = args.get("symptoms", "") if isinstance(args, dict) else str(args)
            if "mild" in symptoms.lower():
                return True  # Normal - take branch to n5a
            return False  # Critical - take branch to n5b
        return f"Unknown tool: {tool_name}"

    # ============================================================
    # Execute original path
    # ============================================================

    print(f"\n[2] Executing original path...")

    ctx1 = ExecutionContext()
    ctx1.tool_port = tool_dispatch
    ctx1 = g.run(engine, ctx1)

    print(f"    Trace: {' → '.join([t['op'] for t in ctx1.trace])}")
    original_outcome = ctx1.reg("R_out")
    print(f"    R_result = {ctx1.reg('R_result')}")
    print(f"    R_out = {original_outcome}")

    # ============================================================
    # ============================================================
    # Fork: patch n2 result to force critical path
    # ============================================================

    print(f"\n[3] Forking: patch TOOL_CALL result from True (normal) to False (critical)")

    # Fork at n2, changing the tool result to False (critical)
    # We do this by replacing n2 with a MOV that sets R_result directly
    forked_g = g.fork_at("n2", {
        "op": "MOV",
        "args": ["R_result", False],
        "next": ["n4"]
    })

    ctx2 = ExecutionContext()
    ctx2.tool_port = tool_dispatch
    ctx2 = forked_g.run(engine, ctx2)

    print(f"    Trace: {' → '.join([t['op'] for t in ctx2.trace])}")
    forked_outcome = ctx2.reg("R_out")
    print(f"    R_result = {ctx2.reg('R_result')}")
    print(f"    R_out = {forked_outcome}")

    # ============================================================
    # Diff
    # ============================================================

    diff = g.diff(forked_g)
    print(f"\n[4] Diff: {len(diff['changed'])} instruction(s) changed")
    for c in diff['changed']:
        print(f"    {c['id']}: {c['original']} → {c['forked']}")

    print("\n" + "=" * 70)
    print("RESULT:")
    print(f"  Original:  {original_outcome}")
    print(f"  Forked:   {forked_outcome}")
    print("=" * 70)


if __name__ == "__main__":
    demo()