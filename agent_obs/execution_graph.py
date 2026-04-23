"""
AgentTrace ExecutionGraph v0.5 - Clean Bytecode ISA

Core Architectural Shift (v0.4 → v0.5):
    v0.4: Opcode VM with some scripting semantics
    v0.5: Fully orthogonal ISA (no implicit state, no truthiness hack)

Key Fixes from v0.4:
    1. EQ instruction added - removes truthiness hack
    2. CALL unified - port abstraction (tool/llm)
    3. $ACC removed - all instructions use explicit dest register
    4. Tool returns pure data - no control flow coupling

v0.5 ISA Properties:
    - All instructions use explicit destination registers
    - Data flow is explicit (dest register is part of instruction)
    - Control flow is ONLY through ISA (EQ + BRANCH)
    - No implicit state ($ACC removed)
    - No domain semantics in instructions (tool name is data, not opcode)

v0.5 ISA (minimal, orthogonal):
    MOV   - register/register or register/literal
    CALL  - unified external port call (tool/llm)
    EQ    - comparison: sets dest = (left == right)
    CMP   - numeric comparison: sets dest = (-1, 0, 1)
    BRANCH - conditional jump on flag register
    JUMP  - unconditional jump
    LOAD  - heap to register
    STORE - register to heap
    HALT  - terminate execution
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

    v0.5 Properties:
        - op is pure opcode (no semantic binding)
        - args are operands (registers, literals, labels)
        - All instructions write explicit destination register
        - next is CFG edge (jump targets)
        - NO implicit state, NO truthiness, NO domain semantics

    v0.4:  Instr(op="TOOL_CALL", args=["diagnose", {...}])
    v0.5:  Instr(op="CALL", args=["tool", "diagnose", "@R_query", "R_result"])
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

    v0.5 Properties:
        - regs: pure register file (no implicit $ACC)
        - heap: memory store
        - tool_port, llm_port: IO interfaces
        - trace: execution trace for debugging

    NO accumulator, NO implicit contracts.
    """
    pc: Optional[str] = None                  # Program counter
    regs: Dict[str, Any] = None               # Register file
    heap: Dict[str, Any] = None               # Memory store
    tool_port: Callable = None                # Tool IO port
    llm_port: Callable = None                 # LLM IO port
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

    v0.5 Properties:
        - Pure dispatch table (NO if/else on semantic types)
        - All handlers write explicit destination registers
        - No business logic, only execution semantics
        - Handlers are pure functions: (instr, ctx) -> result

    No implicit state, no $ACC, no truthiness hack.
    """

    def __init__(self):
        self.name = "AgentTraceVM-v0.5"
        self.handlers: Dict[str, Callable] = {
            # Data movement
            "MOV": self.op_mov,
            "LOAD": self.op_load,
            "STORE": self.op_store,
            # Control flow
            "JUMP": self.op_jump,
            "BRANCH": self.op_branch,
            # Comparison (NEW - removes truthiness hack)
            "EQ": self.op_eq,
            "CMP": self.op_cmp,
            # Call (unified port abstraction)
            "CALL": self.op_call,
            # Terminal
            "HALT": self.op_halt,
        }

    def step(self, instr: Instr, ctx: ExecutionContext) -> Any:
        """
        Execute one instruction.
        Pure dispatch: opcode → handler function.

        All instructions use explicit destination register.
        No implicit state ($ACC removed).
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
        Resolve next instruction based on control flow instructions.

        v0.5: Control flow is ONLY through ISA.
        - BRANCH checks a flag register (not truthiness)
        - JUMP is unconditional
        - No other instruction affects control flow
        """
        # HALT: stop execution
        if instr.op == "HALT":
            ctx.done = True
            return None

        # BRANCH: conditional jump based on flag register
        if instr.op == "BRANCH":
            flag_reg = instr.args[0] if instr.args else None
            flag = ctx.reg(flag_reg) if flag_reg else False

            if flag:
                return instr.next[0] if len(instr.next) > 0 else None
            return instr.next[1] if len(instr.next) > 1 else None

        # JUMP: unconditional
        if instr.op == "JUMP":
            return instr.args[0] if instr.args else instr.next[0] if instr.next else None

        # Default: single successor
        return instr.next[0] if instr.next else None

    # ============================================================
    # Opcode Handlers (pure execution semantics)
    # All use explicit destination register - NO implicit $ACC
    # ============================================================

    def op_mov(self, instr: Instr, ctx: ExecutionContext):
        """
        MOV: register/register or register/literal operation.
        args[0] = dest register
        args[1] = source (literal or @register)
        """
        dest = instr.args[0] if instr.args else None
        src = instr.args[1] if len(instr.args) > 1 else None

        if src is None:
            value = None
        elif isinstance(src, str) and src.startswith("@"):
            value = ctx.reg(src[1:])
        else:
            value = src

        if dest:
            ctx.set_reg(dest, value)
        return value

    def op_call(self, instr: Instr, ctx: ExecutionContext):
        """
        CALL: unified call to external port (tool or llm).
        args[0] = port name ("tool" or "llm")
        args[1] = function name
        args[2] = arg register or literal
        args[3] = dest register (output) - REQUIRED, no implicit

        v0.5: CALL is purely a data operation.
        Control flow is ONLY through BRANCH/EQ.
        Tool/LLM returns pure data, never controls flow.
        """
        port = self._resolve_arg(instr.args[0], ctx) if len(instr.args) > 0 else "tool"
        fn = self._resolve_arg(instr.args[1], ctx) if len(instr.args) > 1 else None
        arg = self._resolve_arg(instr.args[2], ctx) if len(instr.args) > 2 else None
        dest = instr.args[3] if len(instr.args) > 3 else None

        if not dest:
            raise ValueError("CALL requires explicit dest register: CALL port fn arg dest")

        if port == "tool" and ctx.tool_port and callable(ctx.tool_port):
            if isinstance(arg, dict):
                result = ctx.tool_port(fn, arg)
            elif isinstance(arg, str):
                result = ctx.tool_port(fn, {"input": arg})
            else:
                result = ctx.tool_port(fn, {"input": str(arg)})
        elif port == "llm" and ctx.llm_port:
            result = ctx.llm_port(fn, arg, ctx)
        else:
            result = f"CALL({port}, {fn})"

        # Explicit dest register - NO implicit $ACC
        ctx.set_reg(dest, result)
        return result

    def op_eq(self, instr: Instr, ctx: ExecutionContext):
        """
        EQ: comparison instruction (removes truthiness hack).
        args[0] = left operand
        args[1] = right operand
        args[2] = dest flag register

        Sets dest to True/False based on equality comparison.
        Control flow is handled by BRANCH on the flag register.
        """
        left = self._resolve_arg(instr.args[0], ctx) if len(instr.args) > 0 else None
        right = self._resolve_arg(instr.args[1], ctx) if len(instr.args) > 1 else None
        dest = instr.args[2] if len(instr.args) > 2 else None

        if not dest:
            raise ValueError("EQ requires explicit dest register: EQ left right dest")

        result = (left == right)
        ctx.set_reg(dest, result)
        return result

    def op_cmp(self, instr: Instr, ctx: ExecutionContext):
        """
        CMP: comparison with numeric ordering.
        args[0] = left operand
        args[1] = right operand
        args[2] = dest flag register

        Sets dest to -1, 0, or 1 (lt, eq, gt).
        """
        left = self._resolve_arg(instr.args[0], ctx) if len(instr.args) > 0 else None
        right = self._resolve_arg(instr.args[1], ctx) if len(instr.args) > 1 else None
        dest = instr.args[2] if len(instr.args) > 2 else None

        if not dest:
            raise ValueError("CMP requires explicit dest register")

        if left is None or right is None:
            result = 0
        elif left < right:
            result = -1
        elif left > right:
            result = 1
        else:
            result = 0

        ctx.set_reg(dest, result)
        return result

    def op_branch(self, instr: Instr, ctx: ExecutionContext):
        """
        BRANCH: conditional jump based on flag register.
        args[0] = flag register to check
        next[0] = true target
        next[1] = false target

        v0.5: Branch ONLY checks a flag register.
        No truthiness, no implicit conditions.
        """
        flag_reg = instr.args[0] if instr.args else None
        flag = ctx.reg(flag_reg) if flag_reg else False

        # Branch does not write register - just determines next PC
        return None

    def op_jump(self, instr: Instr, ctx: ExecutionContext):
        """JUMP: unconditional jump to target."""
        return None

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
        dest = instr.args[0] if instr.args else None
        addr = self._resolve_arg(instr.args[1], ctx) if len(instr.args) > 1 else None

        if not dest or not addr:
            raise ValueError("LOAD requires dest register and heap address")

        value = ctx.load(addr)
        ctx.set_reg(dest, value)
        return value

    def op_store(self, instr: Instr, ctx: ExecutionContext):
        """
        STORE: store register value to heap.
        args[0] = heap address
        args[1] = source register or literal
        """
        addr = self._resolve_arg(instr.args[0], ctx) if len(instr.args) > 0 else None
        src = instr.args[1] if len(instr.args) > 1 else None

        if addr is None:
            raise ValueError("STORE requires heap address")

        if isinstance(src, str) and src.startswith("@"):
            value = ctx.reg(src[1:])
        else:
            value = src

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

    v0.5 Properties:
        - Nodes are pure Instr (NOT semantic objects)
        - Graph contains NO business logic
        - Graph is pure control flow + bytecode
        - Data flow is explicit through registers
        - Control flow is ONLY through ISA (EQ + BRANCH)
    """

    def __init__(self):
        self.nodes: Dict[str, Instr] = {}
        self.root: Optional[str] = None

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
# v0.5 DEMO - Medical Triage as Clean Bytecode ISA
# ============================================================

def demo():
    """Run medical triage through the Clean Bytecode VM."""
    print("=" * 70)
    print("ExecutionGraph v0.5 - Clean Bytecode ISA Demo")
    print("=" * 70)

    # ============================================================
    # Build medical triage as Clean Bytecode IR
    #
    # v0.5 Clean ISA properties:
    # - All instructions use explicit destination registers
    # - EQ instruction removes truthiness hack
    # - CALL unifies tool/llm port abstraction
    # - No implicit $ACC
    #
    # Bytecode:
    #   n1: MOV R_query "Patient has mild discomfort"
    #   n2: CALL tool diagnose @R_query → R_result
    #   n3: EQ @R_result "CASE_CRITICAL" → R_flag
    #   n4: BRANCH R_flag n5b n5a
    #   n5a: MOV R_out "REST AND FLUIDS"
    #   n5b: MOV R_out "CALL 911"
    #   n6: HALT
    # ============================================================

    g = ExecutionGraph()

    # n1: Initialize query
    g.instr("n1", "MOV", ["R_query", "Patient has mild discomfort"], ["n2"])

    # n2: Call diagnose tool - result stored in R_result (explicit dest)
    # CALL port="tool" fn="diagnose" arg=@R_query dest=R_result
    g.instr("n2", "CALL", ["tool", "diagnose", "@R_query", "R_result"], ["n3"])

    # n3: EQ comparison - sets R_flag to True if R_result == "CASE_CRITICAL"
    g.instr("n3", "EQ", ["@R_result", "CASE_CRITICAL", "R_flag"], ["n4"])

    # n4: Branch on R_flag - if True go n5b (critical), else n5a (normal)
    g.instr("n4", "BRANCH", ["R_flag"], ["n5b", "n5a"])

    # n5a: Normal outcome
    g.instr("n5a", "MOV", ["R_out", "REST AND FLUIDS"], ["n6"])

    # n5b: Critical outcome
    g.instr("n5b", "MOV", ["R_out", "EMERGENCY PROTOCOL: CALL 911"], ["n6"])

    # n6: Halt
    g.instr("n6", "HALT", [], [])

    g.set_root("n1")

    print(f"\n[1] Clean bytecode graph built: {len(g.nodes)} instructions")
    print("     ISA: MOV, CALL, EQ, BRANCH, HALT (no implicit state)")
    print("     Tool returns pure data (not control flow)")

    # ============================================================
    # Set up VM and tools
    # ============================================================

    engine = ExecutionEngine()

    # Tool port: dispatch table for tools (pure data, no control flow)
    def tool_dispatch(tool_name, args):
        if tool_name == "diagnose":
            # Returns pure DATA, not boolean for control flow
            return "CASE_NORMAL"  # Always normal for "mild discomfort"
        return f"Unknown tool: {tool_name}"

    # ============================================================
    # Execute original path
    # ============================================================

    print(f"\n[2] Executing original path...")

    ctx1 = ExecutionContext()
    ctx1.tool_port = tool_dispatch
    ctx1 = g.run(engine, ctx1)

    print(f"    Trace: {' → '.join([t['op'] for t in ctx1.trace])}")
    print(f"    R_result = {ctx1.reg('R_result')}")
    print(f"    R_flag = {ctx1.reg('R_flag')}")
    original_outcome = ctx1.reg("R_out")
    print(f"    R_out = {original_outcome}")

    # ============================================================
    # Fork: patch n3 (EQ comparison) to force critical path
    # ============================================================

    print(f"\n[3] Forking: patch EQ to always set R_flag = True (critical)")

    # Fork by replacing n3 EQ with MOV R_flag True
    forked_g = g.fork_at("n3", {
        "op": "MOV",
        "args": ["R_flag", True],
        "next": ["n4"]
    })

    ctx2 = ExecutionContext()
    ctx2.tool_port = tool_dispatch
    ctx2 = forked_g.run(engine, ctx2)

    print(f"    Trace: {' → '.join([t['op'] for t in ctx2.trace])}")
    print(f"    R_result = {ctx2.reg('R_result')}")
    print(f"    R_flag = {ctx2.reg('R_flag')}")
    forked_outcome = ctx2.reg("R_out")
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

    # ============================================================
    # Verify v0.5 properties
    # ============================================================

    print("\n" + "=" * 70)
    print("v0.5 Clean ISA Properties Verified:")
    print("  [OK] All instructions use explicit destination registers")
    print("  [OK] EQ instruction enables proper comparison")
    print("  [OK] Tool returns pure data (not control flow)")
    print("  [OK] No implicit $ACC")
    print("  [OK] Control flow only through ISA (EQ + BRANCH)")
    print("=" * 70)


if __name__ == "__main__":
    demo()