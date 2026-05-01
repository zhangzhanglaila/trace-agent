"""
TraceExporter: Converts internal ExecutionGraph → LangSmith-compatible trace JSON.

This is the product layer that bridges the causal engine to observability output.
"""
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import json
import time


@dataclass
class TraceRun:
    """
    A single run (step) in the exported trace — LangSmith-compatible schema.
    """
    id: str
    name: str                            # Human-readable name
    run_type: str                        # "llm" | "tool" | "chain" | "branch" | "merge"
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    parent_run_id: Optional[str] = None  # Tree hierarchy
    trace_id: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    latency_ms: Optional[float] = None
    status: str = "success"              # "success" | "error"
    error: Optional[str] = None
    # Extended fields for branch structure
    branch_info: Optional[Dict[str, Any]] = None  # {condition, value, paths}
    tags: List[str] = field(default_factory=list)


@dataclass
class TraceExport:
    """
    Full trace export — LangSmith-compatible with branch-aware structure.
    """
    trace_id: str
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    total_latency_ms: Optional[float] = None
    runs: List[TraceRun] = field(default_factory=list)
    branches: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "trace_id": self.trace_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_latency_ms": self.total_latency_ms,
            "runs": [],
            "branches": self.branches,
        }
        for run in self.runs:
            d = {
                "id": run.id,
                "name": run.name,
                "run_type": run.run_type,
                "inputs": run.inputs,
                "outputs": run.outputs,
                "parent_run_id": run.parent_run_id,
                "start_time": run.start_time,
                "end_time": run.end_time,
                "latency_ms": run.latency_ms,
                "status": run.status,
            }
            if run.error:
                d["error"] = run.error
            if run.branch_info:
                d["branch_info"] = run.branch_info
            if run.tags:
                d["tags"] = run.tags
            result["runs"].append(d)
        return result

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False, default=str)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TraceExport":
        """Deserialize from a dict (reverse of to_dict)."""
        export = cls(
            trace_id=data.get("trace_id", ""),
            start_time=data.get("start_time"),
            end_time=data.get("end_time"),
            total_latency_ms=data.get("total_latency_ms"),
            branches=data.get("branches", []),
        )
        for rd in data.get("runs", []):
            run = TraceRun(
                id=rd.get("id", ""),
                name=rd.get("name", ""),
                run_type=rd.get("run_type", "chain"),
                inputs=rd.get("inputs", {}),
                outputs=rd.get("outputs", {}),
                parent_run_id=rd.get("parent_run_id"),
                trace_id=rd.get("trace_id"),
                start_time=rd.get("start_time"),
                end_time=rd.get("end_time"),
                latency_ms=rd.get("latency_ms"),
                status=rd.get("status", "success"),
                error=rd.get("error"),
                branch_info=rd.get("branch_info"),
                tags=rd.get("tags", []),
            )
            export.runs.append(run)
        return export

    @classmethod
    def from_json(cls, json_str: str) -> "TraceExport":
        """Deserialize from a JSON string."""
        return cls.from_dict(json.loads(json_str))

    @classmethod
    def from_file(cls, path: str) -> "TraceExport":
        """Deserialize from a JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_json(f.read())


class TraceExporter:
    """
    Converts TraceCompiler output into a structured, LangSmith-compatible trace.

    Usage:
        tc = TraceCompiler()
        graph = tc.compile(trace_dict)
        exporter = TraceExporter(graph, tc.branches, tc.step_to_node)
        exported = exporter.export()
        print(exported.to_json())
    """

    def __init__(self, graph, branches: Dict[str, Any], step_to_node: Dict[str, str],
                 steps: List[Dict] = None, trace_id: str = None):
        self.graph = graph
        self.branches = branches
        self.step_to_node = step_to_node
        self.steps = steps or []
        self.trace_id = trace_id or f"trace_{int(time.time() * 1000)}"

        # Build reverse maps
        self.node_to_step: Dict[str, str] = {nid: sid for sid, nid in step_to_node.items()}
        self.step_data: Dict[str, Dict] = {}
        if steps:
            for step in steps:
                self.step_data[step.get("id", "")] = step

        # Build branch step lookup
        self._branch_step_to_id: Dict[str, str] = {}
        for bid, branch in branches.items():
            # branch.branch_id = "br_s2", eq_node = "s2"
            # Find the step that produces this branch
            if hasattr(branch, 'eq_node'):
                eq_step = self.node_to_step.get(branch.eq_node)
                if eq_step:
                    self._branch_step_to_id[eq_step] = bid

    def export(self) -> TraceExport:
        """Export the full trace."""
        export = TraceExport(trace_id=self.trace_id)

        # Build parent relationships
        parents = self._compute_parents()

        # Track min/max times
        min_start = None
        max_end = None

        # Convert each step to a TraceRun
        for i, step in enumerate(self.steps):
            sid = step.get("id", "")
            node_id = self.step_to_node.get(sid)
            if not node_id or node_id not in self.graph.nodes:
                continue

            instr = self.graph.nodes[node_id]
            run = self._step_to_run(step, instr, node_id, parents, export)
            export.runs.append(run)

            if run.start_time:
                if min_start is None or run.start_time < min_start:
                    min_start = run.start_time
            if run.end_time:
                if max_end is None or run.end_time > max_end:
                    max_end = run.end_time

        export.start_time = min_start
        export.end_time = max_end
        if min_start and max_end:
            export.total_latency_ms = (max_end - min_start) * 1000

        # Build branch summaries
        export.branches = self._build_branch_summaries(parents)

        return export

    def _compute_parents(self) -> Dict[str, Optional[str]]:
        """
        Compute parent_run_id for each step.

        Rules (in priority order):
        - Explicit parent_id from step data (set by TraceContext span stack)
        - First step: parent = None (root)
        - Branch targets: parent = branch step_id
        - Merge nodes: parent = branch step_id
        - Otherwise: parent = previous sequential step
        """
        parents: Dict[str, Optional[str]] = {}

        # Build a set of step IDs that are branch targets
        branch_targets: Dict[str, str] = {}  # target_step → branch_step
        for bid, branch in self.branches.items():
            eq_step = self.node_to_step.get(branch.eq_node) if hasattr(branch, 'eq_node') else None
            branch_step = eq_step
            if branch_step:
                if hasattr(branch, 'true_target') and branch.true_target:
                    branch_targets[branch.true_target] = branch_step
                if hasattr(branch, 'false_target') and branch.false_target:
                    branch_targets[branch.false_target] = branch_step

        # Build merge reverse map: merge_step → branch_step
        merge_to_branch: Dict[str, str] = {}
        for bid, branch in self.branches.items():
            if hasattr(branch, 'merge_step') and branch.merge_step:
                eq_step = self.node_to_step.get(branch.eq_node) if hasattr(branch, 'eq_node') else None
                if eq_step:
                    merge_to_branch[branch.merge_step] = eq_step

        for i, step in enumerate(self.steps):
            sid = step.get("id", "")

            # Priority 1: Explicit parent_id from span context
            explicit_parent = step.get("parent_id")
            if explicit_parent is not None:
                parents[sid] = explicit_parent if explicit_parent != "" else None
                continue

            if i == 0:
                parents[sid] = None
                continue

            if sid in branch_targets:
                parents[sid] = branch_targets[sid]
            elif sid in merge_to_branch:
                parents[sid] = merge_to_branch[sid]
            else:
                prev_sid = self.steps[i - 1].get("id", "")
                parents[sid] = prev_sid

        return parents

    def _step_to_run(self, step: Dict, instr, node_id: str,
                     parents: Dict[str, Optional[str]],
                     export: TraceExport) -> TraceRun:
        """Convert a single step to a TraceRun."""
        sid = step.get("id", "")
        step_type = step.get("type", "chain")

        # Determine run_type — prefer semantic_type if set
        sem_type = step.get("semantic_type")
        if sem_type:
            run_type = sem_type.lower()
        else:
            run_type_map = {
                "llm": "llm",
                "tool": "tool",
                "branch": "chain",
                "merge": "chain",
                "output": "chain",
            }
            run_type = run_type_map.get(step_type, "chain")

        # Build inputs/outputs
        inputs, outputs = self._extract_io(step, step_type, instr)

        # Branch info for branch steps
        branch_info = None
        if step_type == "branch":
            bid = self._branch_step_to_id.get(sid)
            if bid and bid in self.branches:
                b = self.branches[bid]
                branch_info = {
                    "condition": step.get("condition", ""),
                    "condition_value": step.get("value"),
                    "true_target": step.get("true_branch"),
                    "false_target": step.get("false_branch"),
                    "merge_node": step.get("merge"),
                }
                if hasattr(b, 'true_nodes'):
                    branch_info["true_path_length"] = len(b.true_nodes)
                if hasattr(b, 'false_nodes'):
                    branch_info["false_path_length"] = len(b.false_nodes)

        # Build name
        name = self._build_name(step, step_type, instr)

        # Tags
        tags = [step_type]
        if step_type == "branch":
            for bid, branch in self.branches.items():
                if hasattr(branch, 'true_target') and branch.true_target == sid:
                    tags.append("true-path-entry")
                if hasattr(branch, 'false_target') and branch.false_target == sid:
                    tags.append("false-path-entry")

        parent = parents.get(sid)

        return TraceRun(
            id=sid,
            name=name,
            run_type=run_type,
            inputs=inputs,
            outputs=outputs,
            parent_run_id=parent,
            trace_id=self.trace_id,
            start_time=step.get("start_time"),
            end_time=step.get("end_time"),
            latency_ms=step.get("latency_ms"),
            status=step.get("status", "success"),
            error=step.get("error"),
            branch_info=branch_info,
            tags=tags,
        )

    def _extract_io(self, step: Dict, step_type: str, instr) -> tuple:
        """Extract inputs and outputs from a step."""
        inputs = {}
        outputs = {}

        if step_type == "llm":
            inputs["prompt"] = step.get("prompt", "")
            outputs["result"] = step.get("output", "")
        elif step_type == "tool":
            inputs["tool"] = step.get("name", "")
            inputs["args"] = step.get("args", {})
            outputs["result"] = step.get("result")
        elif step_type == "branch":
            inputs["condition"] = step.get("condition", "")
            inputs["expected_value"] = step.get("value")
            outputs["branch_to"] = [step.get("true_branch"), step.get("false_branch")]
        elif step_type == "merge":
            inputs["sources"] = step.get("sources", [])
            outputs["merged"] = True
        elif step_type == "output":
            inputs["var"] = step.get("var", "")
            inputs["result"] = step.get("inputs", {}).get("result", "")
            outputs["value"] = step.get("value", "")
        else:
            outputs["raw"] = str(instr.args) if instr else ""

        return inputs, outputs

    def _build_name(self, step: Dict, step_type: str, instr) -> str:
        """Build a human-readable name for the step. Prefer semantic_name if set."""
        sem_name = step.get("semantic_name")
        if sem_name:
            return sem_name
        if step_type == "llm":
            prompt = step.get("prompt", "")
            return f"LLM: {prompt[:60]}"
        elif step_type == "tool":
            name = step.get("name", "unknown")
            return f"Tool: {name}"
        elif step_type == "branch":
            cond = step.get("condition", "?")
            val = step.get("value")
            return f"[Decision] {cond}={val}"
        elif step_type == "merge":
            return "Merge"
        elif step_type == "output":
            var = step.get("var", "output")
            return f"Output: {var}"
        return f"Step: {step_type}"

    def _build_branch_summaries(self, parents: Dict) -> List[Dict]:
        """Build branch summaries for the export."""
        result = []
        for bid, branch in self.branches.items():
            eq_step = self.node_to_step.get(branch.eq_node) if hasattr(branch, 'eq_node') else None
            summary = {
                "branch_id": bid,
                "branch_step": eq_step,
                "condition": None,
                "true_path": [],
                "false_path": [],
                "merge_step": None,
            }
            if hasattr(branch, 'true_nodes'):
                true_path_steps = []
                for nid in branch.true_nodes:
                    sid = self.node_to_step.get(nid)
                    if sid:
                        true_path_steps.append(sid)
                summary["true_path"] = true_path_steps
            if hasattr(branch, 'false_nodes'):
                false_path_steps = []
                for nid in branch.false_nodes:
                    sid = self.node_to_step.get(nid)
                    if sid:
                        false_path_steps.append(sid)
                summary["false_path"] = false_path_steps
            if hasattr(branch, 'merge_step'):
                summary["merge_step"] = branch.merge_step
            if eq_step and eq_step in self.step_data:
                summary["condition"] = self.step_data[eq_step].get("condition")
            if hasattr(branch, 'true_exit') and branch.true_exit is not None:
                summary["true_exit"] = self.node_to_step.get(branch.true_exit, str(branch.true_exit))
            if hasattr(branch, 'false_exit') and branch.false_exit is not None:
                summary["false_exit"] = self.node_to_step.get(branch.false_exit, str(branch.false_exit))
            result.append(summary)
        return result
