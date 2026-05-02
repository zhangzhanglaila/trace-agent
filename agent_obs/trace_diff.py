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
                    # Status or error divergence
                    if ra.status != rb.status:
                        sd.diverged = True
                        sd.run_a_status = ra.status
                        sd.run_b_status = rb.status
                    if ra.error != rb.error:
                        sd.diverged = True
                        sd.run_a_error = ra.error
                        sd.run_b_error = rb.error
                    # Output value divergence (catches cases where status is
                    # "success" in both but result values differ semantically)
                    sd.run_a_output = ra.outputs
                    sd.run_b_output = rb.outputs
                    if self._outputs_meaningfully_differ(ra.outputs, rb.outputs):
                        sd.diverged = True
                    # Branch value differs → covered by branch diff, don't flag as step diff
                diffs.append(sd)

        return diffs

    @staticmethod
    def _outputs_meaningfully_differ(out_a, out_b) -> bool:
        """Compare step outputs, ignoring only trivial identity differences."""
        if out_a == out_b:
            return False
        if out_a is None or out_b is None:
            return out_a is not None or out_b is not None
        # Compare the 'result' key for dict outputs (the canonical output)
        if isinstance(out_a, dict) and isinstance(out_b, dict):
            ra = out_a.get("result")
            rb = out_b.get("result")
            if ra is not None or rb is not None:
                return ra != rb
        return out_a != out_b

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

        # 3. Check step output divergence (same step, different values)
        for sd in step_diffs:
            if sd.diverged and sd.run_a_output is not None and sd.run_b_output is not None:
                # Build a meaningful description from the output diff
                a_val = _brief(sd.run_a_output)
                b_val = _brief(sd.run_b_output)
                return FirstDivergence(
                    type="value",
                    id=sd.step_name,
                    description=(
                        f"Step '{sd.step_name}' produced different results: "
                        f"run_a → {a_val}, run_b → {b_val}"
                    ),
                    run_a=a_val,
                    run_b=b_val,
                )

        # 4. No divergence
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
        # Priority 1: Explicit output step (type "output" or chain named "Output:")
        for run in reversed(trace.runs):
            if run.run_type in ("output", "chain") and ("output" in run.name.lower() or run.run_type == "output"):
                val = run.outputs.get("value") or run.outputs.get("result")
                if not val:
                    val = run.inputs.get("result") or run.inputs.get("value")
                if val is not None:
                    return val

        # Priority 2: Last tool result (for auto-traced agents)
        for run in reversed(trace.runs):
            if run.run_type == "tool":
                val = run.outputs.get("result") or run.inputs.get("result")
                if not val:
                    for k, v in run.outputs.items():
                        if k != "args" and v:
                            val = str(v)[:500]
                            break
                if val is not None:
                    return val

        # Priority 3: Last run output
        for run in reversed(trace.runs):
            val = run.outputs.get("result") or run.outputs.get("value")
            if not val:
                val = run.inputs.get("result") or run.inputs.get("value")
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


# ============================================================
# Interview-Ready Causal Verdict Renderer
# ============================================================

def render_causal_verdict(diff: TraceDiffResult) -> str:
    """
    Render the diff as a visually impactful causal verdict.

    Upgraded output structure (product-ready):
      0. VERDICT — one-line human-readable summary (秒懂)
      1. ROOT CAUSE VARIABLE — variable-level, not just tool-level
      2. BLAST RADIUS — visual cascade showing downstream impact
      3. WHY — plain-language explanation of the failure mechanism
      4. DIAGNOSIS — error type classifier + confidence + suggested fix
    """
    lines = []
    H = "=" * 58

    if not diff.has_diverged:
        lines.append("")
        lines.append(f"  {H}")
        lines.append(f"     No divergence detected. Both runs followed identical paths.")
        lines.append(f"  {H}")
        lines.append("")
        return "\n".join(lines)

    narrative = diff.causal_narrative or ""

    # ── Extract structured info ──
    verdict_text = _build_verdict(diff, narrative)
    root_var, var_a_val, var_b_val, var_source = _extract_root_variable(diff, narrative)
    impact_line = _extract_line(narrative, "Impact score:")
    downstream_line = _extract_line(narrative, "Downstream impact:")
    diag_type, diag_conf, diag_cat = _classify_error(diff, narrative)
    fix_text = _suggest_fix(diag_type, root_var, diff, narrative)

    # ── 0: VERDICT (one-line summary — most important) ──
    lines.append("")
    lines.append(f"  VERDICT")
    lines.append(f"  {verdict_text}")
    lines.append("")

    # ── 1: ROOT CAUSE VARIABLE (variable-level, not tool-level) ──
    lines.append(f"  {H}")
    lines.append(f"     ROOT CAUSE VARIABLE")
    lines.append(f"  {H}")
    lines.append("")

    if root_var:
        lines.append(f"  Variable: `{root_var}` ({var_source})")
        lines.append("")
        lines.append(f"  Value Diff:")
        lines.append(f"    Run A: {var_a_val}")
        lines.append(f"    Run B: {var_b_val}")
    else:
        # Fallback to old root cause format
        root_cause, _, _ = _extract_root_cause(diff, narrative)
        if root_cause:
            for line in root_cause.split("\n"):
                lines.append(f"  {line}")
    lines.append("")

    # ── 2: BLAST RADIUS ──
    lines.append(f"  {H}")
    lines.append(f"     BLAST RADIUS")
    lines.append(f"  {H}")
    lines.append("")

    if impact_line:
        lines.append(f"  {impact_line.strip()}")
    if downstream_line:
        lines.append(f"  {downstream_line.strip()}")
    lines.append("")

    cascade = _build_cascade(diff, narrative)
    if cascade:
        lines.append(f"  Failure cascade:")
        lines.append("")
        for line in cascade:
            lines.append(f"  {line}")
        lines.append("")

    # ── 3: WHY ──
    why = _build_why_explanation(diff, narrative)
    if why:
        lines.append(f"  {H}")
        lines.append(f"     WHY")
        lines.append(f"  {H}")
        lines.append("")
        for line in why:
            lines.append(f"  {line}")
        lines.append("")

    # ── 4: DIAGNOSIS + FIX ──
    lines.append(f"  {H}")
    lines.append(f"     DIAGNOSIS")
    lines.append(f"  {H}")
    lines.append("")

    lines.append(f"  Type:    {diag_type}")
    lines.append(f"  Confidence: {diag_conf}")
    lines.append(f"  Category:   {diag_cat}")
    lines.append("")

    if fix_text:
        lines.append(f"  Suggested Fix:")
        for fix_line in fix_text:
            lines.append(f"    {fix_line}")
        lines.append("")

    lines.append(f"  {H}")
    return "\n".join(lines)


# ============================================================
# Verdict + Variable-level helpers (product-ready upgrades)
# ============================================================

def _brief(val) -> str:
    """Short human-readable summary of a value for divergence descriptions."""
    if isinstance(val, dict):
        result = val.get("result", val)
        if isinstance(result, dict):
            # Show key fields concisely
            parts = []
            for k, v in result.items():
                if k in ("recommendation", "note", "plan"):
                    parts.append(f"{k}={str(v)[:60]}")
                else:
                    parts.append(f"{k}={_brief(v)}")
            return "{" + ", ".join(parts[:4]) + "}"
        return str(result)[:80]
    return str(val)[:80]


def _build_verdict(diff: TraceDiffResult, narrative: str) -> str:
    """Build a one-line human-readable verdict — the most important output."""
    output_a = str(diff.output_a)[:80] if diff.output_a else "no output"
    output_b = str(diff.output_b)[:80] if diff.output_b else "no output"

    has_error_a = "[FAIL]" in output_a or "[PARTIAL]" in output_a or "error" in output_a.lower()
    has_error_b = "[FAIL]" in output_b or "[PARTIAL]" in output_b or "error" in output_b.lower()

    # Extract the key variable (already prioritized + cleaned)
    root_var, var_a, var_b, _ = _extract_root_variable(diff, narrative)

    # ── Build the most human-readable verdict ──
    if root_var == "selected_tool":
        if has_error_b and not has_error_a:
            return (f"Run B failed because the LLM router selected `{var_b}` "
                    f"instead of `{var_a}` — the wrong tool received incompatible "
                    f"arguments, triggering an error cascade.")
        if has_error_a and not has_error_b:
            return (f"Run A failed because the LLM router selected `{var_a}` "
                    f"instead of `{var_b}` — the misrouted tool failed and "
                    f"the retry budget was exhausted.")

    if root_var and var_a and var_b:
        if has_error_b and not has_error_a:
            return (f"Run B failed because `{root_var}` = `{var_b}` "
                    f"(vs `{var_a}` in Run A) — this single variable change "
                    f"cascaded into a degraded final output.")
        if has_error_a and not has_error_b:
            return (f"Run A failed because `{root_var}` = `{var_a}` "
                    f"(vs `{var_b}` in Run B) — this divergence propagated "
                    f"through downstream steps.")
        if diff.output_diverged:
            return (f"Both runs took different paths because `{root_var}` diverged "
                    f"(`{var_a}` vs `{var_b}`), producing different final outputs.")
        return (f"`{root_var}` diverged (`{var_a}` vs `{var_b}`) but both "
                f"runs converged to similar results via different paths.")

    # Fallback
    if diff.first_divergence and diff.first_divergence.type != "none":
        fd = diff.first_divergence
        if diff.output_diverged:
            return (f"Output diverged at `{fd.id}` — "
                    f"Run A: {fd.run_a}, Run B: {fd.run_b}.")
        return (f"Paths split at `{fd.id}` but outputs converged.")

    return diff.summary if diff.summary else "Execution paths diverged."


def _extract_root_variable(diff: TraceDiffResult, narrative: str) -> tuple:
    """
    Extract the root cause at the VARIABLE level (not tool level).

    Collects ALL variable diffs, then picks the most causally significant one.
    Priority: selected_tool > *_result > plan > intent > input.* > other

    Returns (variable_name, run_a_value, run_b_value, source_description).
    """
    import re

    # ── Collect all variable diffs ──
    candidates = []  # (priority, var_name, val_a, val_b, source)
    for line in narrative.split("\n"):
        line_s = line.strip()
        if "var:" not in line_s:
            continue

        var_part = line_s.split("var:", 1)[1].strip()
        colon_idx = var_part.find(":")
        if colon_idx < 0:
            continue

        var_name = var_part[:colon_idx].strip()
        values_part = var_part[colon_idx + 1:].strip()

        # Parse the two values separated by →
        arrow_match = re.search(r'"([^"]*)"\s*→\s*"([^"]*)"', values_part)
        if not arrow_match:
            arrow_match = re.search(r"'([^']*)'\s*→\s*'([^']*)'", values_part)
        if not arrow_match:
            # Truncated format with Unicode arrow
            arrow_match = re.search(r'"([^"]*)"\s*.*?"([^"]*)"', values_part)

        if arrow_match:
            val_a = arrow_match.group(1)
            val_b = arrow_match.group(2)

            # Clean values: extract tool name from plan JSON if applicable
            if var_name == "plan" or var_name == "selected_tool":
                # Try to extract just the tool name from JSON-like strings
                tool_match_a = re.search(r"'tool':\s*'(\w+)'", val_a)
                tool_match_b = re.search(r"'tool':\s*'(\w+)'", val_b)
                if tool_match_a and tool_match_b:
                    val_a = tool_match_a.group(1)
                    val_b = tool_match_b.group(1)
                # Truncate long values
                if len(val_a) > 50:
                    val_a = val_a[:47] + "..."
                if len(val_b) > 50:
                    val_b = val_b[:47] + "..."

            source = _infer_variable_source(var_name, narrative)

            # Assign priority (lower = more significant)
            if var_name == "selected_tool":
                priority = 0
            elif var_name.endswith("_result"):
                priority = 1
            elif var_name == "plan":
                priority = 2
            elif var_name == "intent":
                priority = 3
            elif var_name.startswith("input."):
                priority = 4
            else:
                priority = 5

            candidates.append((priority, var_name, val_a, val_b, source))

    # ── Pick the highest-priority (lowest number) candidate ──
    if candidates:
        candidates.sort(key=lambda c: c[0])
        _, var_name, val_a, val_b, source = candidates[0]
        return var_name, val_a, val_b, source

    # ── Fallback: extract from diff structure ──
    if diff.first_divergence and diff.first_divergence.type == "branch":
        fd = diff.first_divergence
        bd = next((bd for bd in diff.branch_diffs if bd.condition == fd.id), None)
        if bd:
            return (bd.condition, str(bd.run_a_path), str(bd.run_b_path),
                    "decision evaluation")

    return "", "", "", ""


def _infer_variable_source(var_name: str, narrative: str) -> str:
    """Infer where a variable came from."""
    if var_name in ("selected_tool", "plan"):
        return "LLM output"
    if var_name.endswith("_result"):
        tool = var_name.replace("_result", "")
        return f"tool `{tool}` output"
    if var_name in ("intent",):
        return "LLM classification"
    if var_name.startswith("input."):
        return "routing input"
    if var_name in ("should_search", "should_calculate", "route_to_", "need_",
                    "needs_", "advice_", "risk_"):
        return "decision evaluation"
    return "trace variable"


def _classify_error(diff: TraceDiffResult, narrative: str) -> tuple:
    """
    Classify the error type with confidence.

    Distinguishes:
      - True LLM misroute (hallucination / non-deterministic)
      - Error-retry loop (deterministic planner has no fallback for failures)
      - Input-driven divergence (different queries → different tools)
      - General path divergence

    Returns (type_description, confidence, category).
    """
    narrative_lower = narrative.lower()
    has_explicit_misroute = "misrouted" in narrative_lower or "hallucinat" in narrative_lower
    has_selected_tool = "selected_tool" in narrative_lower
    has_retry = "retry" in narrative_lower
    has_error = "error" in narrative_lower

    error_count = narrative_lower.count("error")
    output_a = str(diff.output_a) if diff.output_a else ""
    output_b = str(diff.output_b) if diff.output_b else ""
    has_fail_output = "[FAIL]" in output_a or "[FAIL]" in output_b

    # ── Classify ──
    # Check for explicit root cause variable with downstream impact
    rc_var, _, _ = _extract_root_cause(diff, narrative)
    has_root_cause = bool(rc_var)
    has_partial = "[PARTIAL]" in output_a or "[PARTIAL]" in output_b

    if has_explicit_misroute and has_error:
        diag_type = "LLM Hallucination → Error Cascade"
        category = "Planning Error"
        confidence = "High"
    elif has_error and has_retry and has_fail_output:
        diag_type = "Error-Retry Loop (Missing Fallback)"
        category = "Recovery Failure"
        confidence = "High" if error_count >= 3 else "Medium"
    elif has_root_cause and has_partial:
        # Root cause variable identified with partial output → high confidence
        diag_type = "Tool Output Ambiguity → Wrong Default"
        category = "Edge Case Handling"
        confidence = "High"
    elif has_root_cause:
        diag_type = "Variable Divergence → Path Split"
        category = "Input Sensitivity"
        confidence = "Medium"
    elif has_selected_tool and not has_error:
        diag_type = "Input-Driven Tool Selection"
        category = "Input Sensitivity"
        confidence = "High"
    elif has_selected_tool and has_error:
        diag_type = "Tool Selection Divergence"
        category = "Planning Gap"
        confidence = "Medium"
    elif has_error and has_retry:
        diag_type = "Error-Retry Exhaustion"
        category = "Recovery Failure"
        confidence = "Medium"
    elif diff.output_diverged:
        diag_type = "Execution Path Divergence"
        category = "General"
        confidence = "Low"
    else:
        diag_type = "Minor Path Variation"
        category = "General"
        confidence = "Low"

    return diag_type, confidence, category


def _suggest_fix(diag_type: str, root_var: str,
                 diff: TraceDiffResult, narrative: str) -> list:
    """Generate actionable fix suggestions based on error classification."""
    fixes = []

    if "Tool Output Ambiguity" in diag_type:
        fixes.append("Add input validation on tool outputs before routing decisions")
        fixes.append(f"Check `{root_var}` for edge cases (empty, null, unexpected format)")
        fixes.append("Default to a safe fallback when confidence is low or data is missing")

    if "Misroute" in diag_type or "Non-deterministic" in diag_type:
        fixes.append("Add deterministic routing rules for the step where the misroute occurred")
        fixes.append("Or introduce tool output validation: verify that the selected tool's")
        fixes.append("  output matches expected schema before proceeding")

    if "Retry Loop" in diag_type:
        fixes.append("Add a fallback tool for the retry path instead of re-calling the same tool")
        fixes.append("Or implement exponential backoff with a different strategy on each retry")

    if "Input Sensitivity" in diag_type:
        fixes.append("Add input normalization: map similar queries to canonical tool selections")
        fixes.append("Or introduce a confidence threshold: only switch tools when signal is strong")

    if root_var == "selected_tool":
        # Specific fix for tool selection issues
        fixes.append("Consider adding a tool selection guardrail:")
        tools_involved = set()
        if diff.run_a_path:
            tools_involved.update(diff.run_a_path)
        if diff.run_b_path:
            tools_involved.update(diff.run_b_path)
        tool_list = sorted(t for t in tools_involved if t not in ("llm",))
        if tool_list:
            fixes.append(f"  Define explicit preconditions for: {', '.join(tool_list[:3])}")

    if not fixes:
        fixes.append("Review the first divergence point and add a guard condition")
        if diff.first_divergence:
            fixes.append(f"  Specifically at: {diff.first_divergence.id}")

    return fixes


def _extract_root_cause(diff: TraceDiffResult, narrative: str) -> tuple:
    """Extract root cause description, trigger variable, and values."""
    root_cause = ""
    trigger_var = ""
    trigger_vals = ""

    # Detect tool misroute pattern from narrative
    tool_change = _detect_tool_misroute(narrative)
    if tool_change:
        root_cause = tool_change
        # Find the trigger variable
        for line in narrative.split("\n"):
            line_s = line.strip()
            if "selected_tool" in line_s and "var:" in line_s:
                trigger_var = line_s.split("var:", 1)[1].strip()
                break
        return root_cause, trigger_var, trigger_vals

    # Try to extract from narrative
    rc_match = _extract_line(narrative, "Root cause:")
    if rc_match:
        root_cause = rc_match.strip()
    caused_by = _extract_line(narrative, "caused by:")
    if caused_by:
        root_cause = f"{root_cause}\n  {caused_by.strip()}"

    if not root_cause:
        # Build from diff structure
        if diff.first_divergence and diff.first_divergence.type != "none":
            fd = diff.first_divergence
            root_cause = f"Decision `{fd.id}` diverged"
            if fd.run_a is not None and fd.run_b is not None:
                root_cause += f":\n    Run A: {fd.run_a}\n    Run B: {fd.run_b}"

        diverged_branches = [bd for bd in diff.branch_diffs if bd.diverged]
        if diverged_branches:
            for bd in diverged_branches:
                root_cause = (f"Branch `{bd.condition}` took different paths:\n"
                             f"    Run A: took '{bd.run_a_path}' path\n"
                             f"    Run B: took '{bd.run_b_path}' path")

    if not root_cause:
        root_cause = diff.summary

    # Extract trigger variable from narrative
    for line in narrative.split("\n"):
        line_s = line.strip()
        if "var:" in line_s or "Root cause: variable change" in line_s:
            if "var:" in line_s:
                var_part = line_s.split("var:", 1)[1].strip()
                trigger_var = var_part
            break

    # Check for exclusive paths
    if not root_cause.strip():
        step_diffs = [sd for sd in diff.step_diffs if sd.only_in]
        if step_diffs:
            sd = step_diffs[0]
            this_run = "Run A" if sd.only_in == "run_a" else "Run B"
            root_cause = f"Step `{sd.step_name}` only executed in {this_run}"

    return root_cause, trigger_var, trigger_vals


def _detect_tool_misroute(narrative: str) -> str:
    """Detect if the root cause is an LLM tool selection error."""
    tool_a = None
    tool_b = None
    for line in narrative.split("\n"):
        line_s = line.strip()
        if "selected_tool" in line_s and "var:" in line_s:
            import re
            match = re.search(r'"(\w+)"\s*.*?"(\w+)"', line_s)
            if match:
                tool_a, tool_b = match.group(1), match.group(2)
                break

    if tool_a and tool_b:
        # Determine which tool was wrong by checking which path had errors
        failed_a = "error" in narrative.lower() and "Run A" in narrative
        return (f"LLM Router selected different tools:\n"
                f"    Run A chose: `{tool_a}`\n"
                f"    Run B chose: `{tool_b}`\n"
                f"  This is a non-deterministic routing decision —\n"
                f"  the same context produced different tool choices.")

    # Check for plan-level diff
    for line in narrative.split("\n"):
        line_s = line.strip()
        if "plan:" in line_s and "var:" in line_s:
            import re
            tools = re.findall(r"'tool':\s*'(\w+)'", line_s)
            if len(tools) >= 2 and tools[0] != tools[1]:
                return (f"LLM Router selected different tools:\n"
                        f"    Run A chose: `{tools[0]}`\n"
                        f"    Run B chose: `{tools[1]}`")

    return ""


def _extract_line(text: str, prefix: str) -> str:
    """Extract the first line from text that starts with prefix."""
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped
    return ""


def _build_cascade(diff: TraceDiffResult, narrative: str) -> list:
    """Build a visual side-by-side cascade showing where paths diverged."""
    lines = []
    path_a = diff.run_a_path if diff.run_a_path else []
    path_b = diff.run_b_path if diff.run_b_path else []

    if not path_a and not path_b:
        return []

    # Detect divergence index — first position where paths differ
    div_idx = None
    for i in range(min(len(path_a), len(path_b))):
        if path_a[i] != path_b[i]:
            div_idx = i
            break
    if div_idx is None:
        div_idx = min(len(path_a), len(path_b))

    # Header
    a_label = "Run A"
    b_label = "Run B"
    lines.append(f"  {a_label:40s} {b_label}")

    # Show aligned steps
    max_len = max(len(path_a), len(path_b))
    shown = 0
    for i in range(max_len):
        if shown >= 10:
            remaining = max_len - shown
            if remaining > 0:
                lines.append(f"  ... ({remaining} more steps)")
            break

        a_step = path_a[i] if i < len(path_a) else "(end)"
        b_step = path_b[i] if i < len(path_b) else "(end)"

        if i < div_idx:
            # Same path
            lines.append(f"  {a_step:40s} {b_step}")
        elif i == div_idx:
            # Divergence point
            sep = "DIVERGED"
            lines.append(f"  {'':-^78}")
            lines.append(f"  {a_step:40s} {b_step}    <-- {sep}")
            lines.append(f"  {'':-^78}")
        else:
            # After divergence
            a_display = a_step if a_step != "(end)" else "(none)"
            b_display = b_step if b_step != "(end)" else "(none)"
            a_mark = ">> " if a_step != b_step and i < len(path_a) else "   "
            b_mark = ">> " if a_step != b_step and i < len(path_b) else "   "
            lines.append(f"  {a_mark}{a_display:<38s} {b_mark}{b_display}")
        shown += 1

    # Summary
    extra_a = len(path_a) - div_idx if div_idx < len(path_a) else 0
    extra_b = len(path_b) - div_idx if div_idx < len(path_b) else 0
    if extra_a > 0:
        lines.append(f"")
        lines.append(f"  Run A had {extra_a} extra step(s) after divergence.")
    if extra_b > 0:
        lines.append(f"  Run B had {extra_b} extra step(s) after divergence.")

    return lines


def _build_why_explanation(diff: TraceDiffResult, narrative: str) -> list:
    """Build a plain-language 'why' explanation."""
    lines = []
    narrative_lower = narrative.lower()

    # Detect the failure archetype
    is_misroute = "misrout" in narrative_lower or "selected_tool" in narrative_lower
    is_error_cascade = narrative_lower.count("error") >= 2
    is_threshold = "branch flip" in narrative_lower or "threshold" in narrative_lower

    if is_misroute:
        # Extract tool names from the path divergence
        import re
        only_a = set()
        only_b = set()

        # Get tool names from paths (these are cleaner than step diffs)
        if diff.run_a_path and diff.run_b_path:
            a_set = set(diff.run_a_path)
            b_set = set(diff.run_b_path)
            only_a = a_set - b_set
            only_b = b_set - a_set

        # Also try to parse tool names from narrative var lines
        for line in narrative.split("\n"):
            if "selected_tool" in line and "var:" in line:
                match = re.search(r'"(\w+)"\s*.*?"(\w+)"', line)
                if match:
                    only_a = {match.group(1)}
                    only_b = {match.group(2)}
                    break

        if only_a or only_b:
            lines.append(f"The LLM router made a non-deterministic tool selection error.")
            lines.append(f"")
            if only_a:
                lines.append(f"  Run A selected: {', '.join(sorted(only_a)[:3])}")
            if only_b:
                lines.append(f"  Run B selected: {', '.join(sorted(only_b)[:3])}")
            lines.append(f"")
            lines.append(f"This is the single decision that caused ALL downstream differences.")
            if is_error_cascade:
                lines.append(f"The wrong tool received incompatible arguments, triggering")
                lines.append(f"a cascade of error-retry cycles that consumed the step budget.")

    elif is_threshold:
        lines.append(f"A threshold condition evaluated differently due to a small input change.")
        lines.append(f"This type of 'butterfly effect' bug is common in agent pipelines")
        lines.append(f"where numeric values cross decision boundaries.")
    else:
        # Generic: show what changed between runs
        diverged_branches = [bd for bd in diff.branch_diffs if bd.diverged]
        if diverged_branches:
            bd = diverged_branches[0]
            lines.append(f"The decision `{bd.condition}` took different paths:")
            lines.append(f"  Run A: {bd.run_a_path}")
            lines.append(f"  Run B: {bd.run_b_path}")
            lines.append(f"")
            lines.append(f"This single branch flip caused the agent to follow a")
            lines.append(f"different execution path, producing a different result.")
        elif diff.first_divergence:
            fd = diff.first_divergence
            lines.append(f"The first divergence occurred at `{fd.id}`.")
            lines.append(f"All steps before this point were identical between runs.")

    # Show result comparison
    if diff.output_diverged:
        lines.append(f"")
        lines.append(f"Result:")
        out_a = str(diff.output_a)[:100] if diff.output_a else "(none)"
        out_b = str(diff.output_b)[:100] if diff.output_b else "(none)"
        lines.append(f"  Run A: {out_a}")
        lines.append(f"  Run B: {out_b}")

    return lines


def _build_diagnosis(diff: TraceDiffResult, narrative: str) -> list:
    """Build a diagnosis with actionable insight."""
    lines = []
    narrative_lower = narrative.lower()

    has_misroute = "misrout" in narrative_lower or "selected_tool" in narrative_lower
    has_error = "error" in narrative_lower
    has_retry = "retry" in narrative_lower

    if has_misroute and has_error and has_retry:
        lines.append("Pattern: LLM Misroute -> Error Cascade")
        lines.append("The planner picked the wrong tool, which received incompatible")
        lines.append("arguments and failed. The retry mechanism re-planned but picked")
        lines.append("ANOTHER wrong tool, consuming the step budget with no progress.")
    elif has_misroute:
        lines.append("Pattern: Non-deterministic LLM Routing")
        lines.append("The planner's tool selection is not deterministic — the same")
        lines.append("context can produce different tool choices across runs.")
        lines.append("Fix: Add deterministic routing rules for critical paths.")
    elif has_error and has_retry:
        lines.append("Pattern: Error-Retry Loop")
        lines.append("The agent retried a failing operation but did not change its")
        lines.append("approach, leading to repeated failures.")
        lines.append("Fix: Add exponential backoff or tool fallback on retry.")

    # Check output quality
    if diff.output_diverged:
        out_a = str(diff.output_a) if diff.output_a else ""
        out_b = str(diff.output_b) if diff.output_b else ""
        if "[FAIL]" in out_a or "[PARTIAL]" in out_a:
            lines.append(f"Run A output is degraded: {out_a[:60]}...")
        if "[FAIL]" in out_b or "[PARTIAL]" in out_b:
            lines.append(f"Run B output is degraded: {out_b[:60]}...")

    if not lines:
        if diff.first_divergence:
            lines.append(f"Divergence: {diff.first_divergence.id}")
            lines.append(f"Description: {diff.first_divergence.description}")

    return lines
