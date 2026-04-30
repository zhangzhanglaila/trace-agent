"""
Trace Diff: Semantic, branch-aware comparison of two agent traces.

Not a JSON diff — a causal diff that answers "why did this run differ from that one?"
Aligns by branch condition + path, then by step name.
Pinpoints the first decision that caused divergence.
"""
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
import json

from .trace_export import TraceExport, TraceRun


# ============================================================
# Diff Result Types
# ============================================================

@dataclass
class BranchDiff:
    branch_id: str                # Aligned by condition name
    condition: str                # Human-readable condition
    run_a_path: str               # "true" or "false" or "none"
    run_b_path: str               # "true" or "false" or "none"
    diverged: bool                # True if paths differ
    run_a_branch_step: Optional[str] = None  # step id in run_a
    run_b_branch_step: Optional[str] = None  # step id in run_b
    run_a_condition_value: Any = None
    run_b_condition_value: Any = None


@dataclass
class StepDiff:
    step_name: str                # Aligned by name
    only_in: Optional[str] = None  # "run_a" or "run_b" or None
    run_a_status: Optional[str] = None
    run_b_status: Optional[str] = None
    run_a_error: Optional[str] = None
    run_b_error: Optional[str] = None
    run_a_output: Any = None
    run_b_output: Any = None
    diverged: bool = False


@dataclass
class FirstDivergence:
    """The first decision point that caused paths to split."""
    type: str                     # "branch" | "step" | "none"
    id: str                       # branch condition name or step name
    description: str              # Human-readable explanation
    run_a: Any = None
    run_b: Any = None


@dataclass
class TraceDiffResult:
    trace_id_a: str
    trace_id_b: str
    summary: str = ""                                      # One-line human explanation
    branch_diffs: List[BranchDiff] = field(default_factory=list)
    step_diffs: List[StepDiff] = field(default_factory=list)
    first_divergence: Optional[FirstDivergence] = None
    run_a_path: List[str] = field(default_factory=list)
    run_b_path: List[str] = field(default_factory=list)
    output_diverged: bool = False
    has_diverged: bool = False
    output_a: Any = None
    output_b: Any = None
    causal_chain: List[str] = field(default_factory=list)   # Root-cause chain of step names
    causal_narrative: str = ""                                # Full explain_diff() narrative

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "trace_id_a": self.trace_id_a,
            "trace_id_b": self.trace_id_b,
            "summary": self.summary,
            "output_diverged": self.output_diverged,
            "output_a": self.output_a,
            "output_b": self.output_b,
            "run_a_path": self.run_a_path,
            "run_b_path": self.run_b_path,
            "branch_diffs": [],
            "step_diffs": [],
            "first_divergence": None,
        }
        for bd in self.branch_diffs:
            result["branch_diffs"].append({
                "branch_id": bd.branch_id,
                "condition": bd.condition,
                "run_a_path": bd.run_a_path,
                "run_b_path": bd.run_b_path,
                "diverged": bd.diverged,
            })
        for sd in self.step_diffs:
            d: Dict[str, Any] = {"step_name": sd.step_name, "diverged": sd.diverged}
            if sd.only_in:
                d["only_in"] = sd.only_in
            if sd.run_a_status != sd.run_b_status:
                d["run_a_status"] = sd.run_a_status
                d["run_b_status"] = sd.run_b_status
            result["step_diffs"].append(d)
        if self.first_divergence:
            result["first_divergence"] = {
                "type": self.first_divergence.type,
                "id": self.first_divergence.id,
                "description": self.first_divergence.description,
                "run_a": self.first_divergence.run_a,
                "run_b": self.first_divergence.run_b,
            }
        return result

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False, default=str)


# ============================================================
# Diff Engine
# ============================================================

class TraceDiffer:
    """
    Semantic, branch-aware diff of two agent traces.

    Alignment strategy:
      1. Branches aligned by condition name (semantic, not by generated ID)
      2. Steps aligned by name (e.g. "Tool: weather")
      3. First divergence = first branch where paths differ (causal), not first different step
    """

    def __init__(self, trace_a: TraceExport, trace_b: TraceExport):
        self.a = trace_a
        self.b = trace_b

        # Index runs by ID for quick lookup
        self._runs_a: Dict[str, TraceRun] = {}
        self._runs_b: Dict[str, TraceRun] = {}
        for r in self.a.runs:
            self._runs_a[r.id] = r
        for r in self.b.runs:
            self._runs_b[r.id] = r

        # Index branches by condition name
        self._branches_a: Dict[str, Dict] = {}
        self._branches_b: Dict[str, Dict] = {}
        for b in self.a.branches:
            cond = b.get("condition", "")
            if cond:
                self._branches_a[cond] = b
        for b in self.b.branches:
            cond = b.get("condition", "")
            if cond:
                self._branches_b[cond] = b

    def diff(self) -> TraceDiffResult:
        """Run full semantic diff."""
        result = TraceDiffResult(
            trace_id_a=self.a.trace_id,
            trace_id_b=self.b.trace_id,
        )

        # 1. Diff branches (aligned by condition name)
        result.branch_diffs = self._diff_branches()

        # 2. Diff steps (aligned by name)
        result.step_diffs = self._diff_steps()

        # 3. Find first divergence (causal: first branch that diverged)
        result.first_divergence = self._find_first_divergence(result.branch_diffs, result.step_diffs)

        # 4. Build human-readable path summaries
        result.run_a_path = self._build_path_summary(self.a)
        result.run_b_path = self._build_path_summary(self.b)

        # 5. Check output divergence and capture output values
        result.output_a = self._get_final_output(self.a)
        result.output_b = self._get_final_output(self.b)
        result.output_diverged = result.output_a != result.output_b

        # 6. Overall divergence flag
        result.has_diverged = (
            any(bd.diverged for bd in result.branch_diffs) or
            any(sd.diverged for sd in result.step_diffs)
        )

        # 7. Generate one-line human summary
        result.summary = self._build_summary(result)

        return result

    def _diff_branches(self) -> List[BranchDiff]:
        """Align branches by condition name, compare path taken."""
        diffs: List[BranchDiff] = []

        # Collect all condition names
        all_conditions = set(self._branches_a.keys()) | set(self._branches_b.keys())

        for cond in sorted(all_conditions):
            ba = self._branches_a.get(cond)
            bb = self._branches_b.get(cond)

            bd = BranchDiff(
                branch_id=cond,
                condition=cond,
                run_a_path="none",
                run_b_path="none",
                diverged=False,
            )

            if ba:
                bd.run_a_branch_step = ba.get("branch_step")
                bd.run_a_condition_value = self._get_branch_value(ba)
                bd.run_a_path = self._which_path_taken(ba, self._runs_a)

            if bb:
                bd.run_b_branch_step = bb.get("branch_step")
                bd.run_b_condition_value = self._get_branch_value(bb)
                bd.run_b_path = self._which_path_taken(bb, self._runs_b)

            bd.diverged = bd.run_a_path != bd.run_b_path
            diffs.append(bd)

        return diffs

    def _diff_steps(self) -> List[StepDiff]:
        """Align steps by name, detect differences in presence/status/error."""
        # Build name→run maps
        # For branch steps: normalize name to condition prefix so values don't cause
        # spurious "only in" diffs (e.g. "Branch: cond=True" vs "Branch: cond=False")
        def _step_key(run: TraceRun) -> str:
            name = run.name
            if name.startswith("Branch: "):
                # Strip the "=True"/"=False" suffix for alignment
                if "=True" in name:
                    return name.replace("=True", "")
                if "=False" in name:
                    return name.replace("=False", "")
            return name

        names_a: Dict[str, List[TraceRun]] = {}
        names_b: Dict[str, List[TraceRun]] = {}
        for r in self.a.runs:
            names_a.setdefault(_step_key(r), []).append(r)
        for r in self.b.runs:
            names_b.setdefault(_step_key(r), []).append(r)

        all_names = set(names_a.keys()) | set(names_b.keys())
        diffs: List[StepDiff] = []

        for name in sorted(all_names):
            ra_list = names_a.get(name, [])
            rb_list = names_b.get(name, [])

            max_len = max(len(ra_list), len(rb_list))
            for i in range(max_len):
                ra = ra_list[i] if i < len(ra_list) else None
                rb = rb_list[i] if i < len(rb_list) else None

                # Display name: use original if available
                display_name = ra.name if ra else (rb.name if rb else name)

                sd = StepDiff(step_name=display_name)
                if ra and not rb:
                    sd.only_in = "run_a"
                    sd.diverged = True
                elif rb and not ra:
                    sd.only_in = "run_b"
                    sd.diverged = True
                elif ra and rb:
                    if ra.status != rb.status:
                        sd.diverged = True
                        sd.run_a_status = ra.status
                        sd.run_b_status = rb.status
                    if ra.error != rb.error:
                        sd.diverged = True
                        sd.run_a_error = ra.error
                        sd.run_b_error = rb.error
                    # Branch value differs → covered by branch diff, don't flag as step diff
                diffs.append(sd)

        return diffs

    def _find_first_divergence(
        self, branch_diffs: List[BranchDiff], step_diffs: List[StepDiff]
    ) -> Optional[FirstDivergence]:
        """
        Find the first causal divergence point.

        Priority: branch divergence > step presence divergence.
        A branch divergence is causal — it's the decision that caused the paths to split.
        A step-only divergence is observational — a step present in one but not the other.
        """
        # 1. First check branches (causal divergence)
        for bd in branch_diffs:
            if bd.diverged:
                return FirstDivergence(
                    type="branch",
                    id=bd.condition,
                    description=(
                        f"Decision '{bd.condition}' evaluated differently: "
                        f"run_a took '{bd.run_a_path}' path, "
                        f"run_b took '{bd.run_b_path}' path"
                    ),
                    run_a=bd.run_a_path,
                    run_b=bd.run_b_path,
                )

        # 2. Then check step presence
        for sd in step_diffs:
            if sd.only_in:
                return FirstDivergence(
                    type="step",
                    id=sd.step_name,
                    description=f"Step '{sd.step_name}' only exists in {sd.only_in}",
                    run_a="present" if sd.only_in == "run_a" else "absent",
                    run_b="present" if sd.only_in == "run_b" else "absent",
                )

        # 3. No divergence
        return FirstDivergence(
            type="none",
            id="",
            description="Both runs followed identical paths",
        )

    def _which_path_taken(self, branch: Dict, run_map: Dict[str, TraceRun]) -> str:
        """
        Determine which branch path was actually executed.

        Strategy (in priority order):
          1. Check branch_info.condition_value on the branch step run (most reliable)
          2. Check which path has EXCLUSIVE steps (steps only on one side)
          3. Fallback to unknown
        """
        # Priority 1: Direct condition_value from branch step
        branch_step = branch.get("branch_step")
        if branch_step and branch_step in run_map:
            bi = run_map[branch_step].branch_info
            if bi:
                cv = bi.get("condition_value")
                if cv is True:
                    return "true"
                elif cv is False:
                    return "false"

        # Priority 2: Path-exclusive steps
        true_path = set(branch.get("true_path", []) or [])
        false_path = set(branch.get("false_path", []) or [])

        # Exclusive steps: on one path but not the other
        true_exclusive = true_path - false_path
        false_exclusive = false_path - true_path

        for sid in false_exclusive:
            if sid in run_map:
                return "false"
        for sid in true_exclusive:
            if sid in run_map:
                return "true"

        return "unknown"

    def _get_branch_value(self, branch: Dict) -> Any:
        """Extract the condition value from a branch summary."""
        # Try to find the value from the branch_step's run
        branch_step = branch.get("branch_step")
        run_map = self._runs_a if branch_step in self._runs_a else self._runs_b
        if branch_step and branch_step in run_map:
            bi = run_map[branch_step].branch_info
            if bi:
                return bi.get("condition_value")
        return branch.get("condition")

    def _build_path_summary(self, trace: TraceExport) -> List[str]:
        """Build a human-readable path summary: tool names in execution order."""
        path: List[str] = []
        for run in trace.runs:
            if run.run_type == "tool":
                tool_name = run.inputs.get("tool", run.name)
                path.append(tool_name)
            elif run.run_type == "llm":
                path.append("llm")
        return path

    def _build_summary(self, result: TraceDiffResult) -> str:
        """
        Generate a one-line human-readable explanation of WHY the runs differ.

        Rules:
        - Must name the decision that changed
        - Must say what path change it caused
        - Must state the final impact
        """
        if not result.has_diverged:
            return "Both runs followed identical paths and produced the same result."

        fd = result.first_divergence
        if fd is None:
            return "The runs differ, but no specific divergence point was identified."

        if fd.type == "branch":
            # The output changed because `cond` evaluated to X instead of Y
            cond = fd.id
            val_a = fd.run_a
            val_b = fd.run_b
            a_desc = self._describe_path_change(result)

            if result.output_diverged:
                return (
                    f"The output changed because `{cond}` "
                    f"evaluated to {val_b} instead of {val_a}, "
                    f"{a_desc}."
                )
            else:
                return (
                    f"The path diverged at `{cond}` "
                    f"({val_a} -> {val_b}), "
                    f"but the output converged to the same result."
                )

        elif fd.type == "step":
            name = fd.id
            where = fd.run_a if fd.run_a == "absent" else fd.run_b
            who = "run_a" if fd.run_a == "present" else "run_b"
            if result.output_diverged:
                return (
                    f"The output changed because step `{name}` "
                    f"only executed in {who}, causing different paths."
                )
            else:
                return (
                    f"Step `{name}` only executed in {who}, "
                    f"but the output remained the same."
                )

        return "The runs differ."

    def _describe_path_change(self, result: TraceDiffResult) -> str:
        """Describe the path change in natural language."""
        diverged_branches = [bd for bd in result.branch_diffs if bd.diverged]
        if not diverged_branches:
            return "causing different steps to execute"

        bd = diverged_branches[0]

        # Categorize the path change
        if bd.run_a_path == "true" and bd.run_b_path == "false":
            return "triggering a fallback path instead of returning early"
        elif bd.run_a_path == "false" and bd.run_b_path == "true":
            return "taking a direct path instead of the fallback"
        elif bd.run_a_path == "none":
            return f"causing a new branch path ({bd.run_b_path}) to execute"
        elif bd.run_b_path == "none":
            return f"skipping a branch path ({bd.run_a_path}) that previously executed"
        else:
            return f"switching from the {bd.run_a_path} path to the {bd.run_b_path} path"

    @staticmethod
    def _get_final_output(trace: TraceExport) -> Any:
        """Extract final output from a trace."""
        # Priority 1: Explicit output step
        for run in reversed(trace.runs):
            if run.run_type == "chain" and run.name.startswith("Output:"):
                val = run.outputs.get("value")
                if val is not None:
                    return val

        # Priority 2: Last tool result (for auto-traced agents)
        for run in reversed(trace.runs):
            if run.run_type == "tool":
                val = run.outputs.get("result")
                if val is not None:
                    return val

        # Priority 3: Last run output
        for run in reversed(trace.runs):
            val = run.outputs.get("result") or run.outputs.get("value")
            if val is not None:
                return val

        return None


# ============================================================
# CLI Renderer
# ============================================================

def render_diff(diff: TraceDiffResult, level: int = 2) -> str:
    """
    Render diff result at the requested detail level.

    Level 1: Executive summary (one line)
    Level 2: Engineer (decision + path + divergence) [default]
    Level 3: Debug (full causal chain + step diffs)
    """
    lines = []
    hdr = "=" * 58

    if not diff.has_diverged:
        lines.append("")
        lines.append(hdr)
        lines.append("  NO DIFFERENCE")
        lines.append(hdr)
        lines.append(f"  {diff.summary}")
        lines.append("")
        return "\n".join(lines)

    # ── Level 1: Executive ──
    lines.append("")
    lines.append(hdr)
    lines.append("  ROOT CAUSE FOUND")
    lines.append(hdr)
    lines.append("")
    lines.append(f"  {diff.summary}")
    lines.append("")

    if level < 2:
        lines.append(hdr)
        return "\n".join(lines)

    # ── Level 2: Engineer ──
    diverged_branches = [bd for bd in diff.branch_diffs if bd.diverged]
    if diverged_branches:
        lines.append("  [Decision Change]")
        for bd in diverged_branches:
            lines.append(f"  - {bd.condition}: {bd.run_a_path} -> {bd.run_b_path}")
        lines.append("")

    lines.append("  [Path Impact]")
    path_a = " -> ".join(diff.run_a_path) if diff.run_a_path else "(empty)"
    path_b = " -> ".join(diff.run_b_path) if diff.run_b_path else "(empty)"
    lines.append(f"  run_a: {path_a}")
    lines.append(f"  run_b: {path_b}")
    lines.append("")

    if diff.first_divergence and diff.first_divergence.type != "none":
        lines.append("  [First Divergence]")
        lines.append(f"  -> {diff.first_divergence.id}")
        lines.append("")

    lines.append("  [Result]")
    if diff.output_diverged:
        out_a = _get_output_preview(diff, "a")
        out_b = _get_output_preview(diff, "b")
        lines.append(f"  -> Final output differs")
        if out_a:
            lines.append(f"     run_a: {out_a}")
        if out_b:
            lines.append(f"     run_b: {out_b}")
    else:
        lines.append(f"  -> Output converged (same result via different paths)")
    lines.append("")

    if level < 3:
        lines.append(hdr)
        return "\n".join(lines)

    # ── Level 3: Causal Chain ──
    if diff.causal_narrative:
        lines.append("  [Causal Explanation]")
        for line in diff.causal_narrative.split("\n"):
            if line.strip():
                lines.append(f"  {line}")
        lines.append("")
    elif diff.causal_chain:
        lines.append("  [Causal Chain]")
        for i, step in enumerate(diff.causal_chain):
            arrow = "  ->" if i < len(diff.causal_chain) - 1 else "  [!]"
            lines.append(f"  {arrow} {step}")
        lines.append("")

    # ── Step Diffs (only diverged) ──
    diverged_steps = [sd for sd in diff.step_diffs if sd.diverged]
    if diverged_steps:
        lines.append("  [Step Deltas]")
        for sd in diverged_steps:
            if sd.only_in:
                lines.append(f"  - '{sd.step_name}' only in {sd.only_in}")
            else:
                parts = [f"  - '{sd.step_name}'"]
                if sd.run_a_status != sd.run_b_status:
                    parts.append(f"status: {sd.run_a_status} -> {sd.run_b_status}")
                lines.append(" | ".join(parts))
        lines.append("")

    lines.append(hdr)
    return "\n".join(lines)


def _get_output_preview(diff: TraceDiffResult, which: str) -> str:
    """Get a short preview of the final output for display."""
    val = diff.output_a if which == "a" else diff.output_b
    if val is not None:
        s = str(val)
        return s[:80] if len(s) > 80 else s
    return ""


def diff_traces(trace_a: TraceExport, trace_b: TraceExport) -> TraceDiffResult:
    """Quick one-liner: diff two trace exports."""
    differ = TraceDiffer(trace_a, trace_b)
    return differ.diff()
