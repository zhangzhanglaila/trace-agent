"""
Diff Renderer Module: Unified rendering for trace diff results (M3.4).

Provides a configurable DiffRenderer that can output in multiple formats:
- executive: one-line summary
- engineer: decision + path + divergence
- debug: full causal chain + step diffs
- verdict: interview-ready causal verdict (VERDICT/ROOT CAUSE/BLAST RADIUS/WHY/DIAGNOSIS)

This module wraps the existing render_diff / render_causal_verdict logic in a
configurable class and adds JSON output support.
"""
from enum import Enum
from typing import Dict, Any, List, Optional

from .trace_diff import (
    TraceDiffResult,
    _build_verdict,
    _extract_root_variable,
    _extract_root_cause,
    _extract_line,
    _build_cascade,
    _build_why_explanation,
    _classify_error,
    _suggest_fix,
    _get_output_preview,
)


class RenderFormat(Enum):
    """Supported diff output formats."""
    EXECUTIVE = "executive"  # One-line summary
    ENGINEER = "engineer"    # Decision + path + divergence
    DEBUG = "debug"          # Full causal chain + step diffs
    VERDICT = "verdict"      # Interview-ready causal verdict


class DiffRenderer:
    """
    Unified renderer for TraceDiffResult.

    Usage:
        renderer = DiffRenderer(format=RenderFormat.ENGINEER)
        output = renderer.render(diff)
    """

    def __init__(self, format: RenderFormat = RenderFormat.ENGINEER,
                 include_causal_chain: bool = True):
        self.format = format
        self.include_causal_chain = include_causal_chain

    def render(self, diff: TraceDiffResult) -> str:
        """Render diff in the configured format."""
        if self.format == RenderFormat.EXECUTIVE:
            return self._render_executive(diff)
        if self.format == RenderFormat.ENGINEER:
            return self._render_engineer(diff)
        if self.format == RenderFormat.DEBUG:
            return self._render_debug(diff)
        if self.format == RenderFormat.VERDICT:
            return self._render_verdict(diff)
        return self._render_engineer(diff)

    def to_dict(self, diff: TraceDiffResult) -> Dict[str, Any]:
        """Render diff as a structured dictionary."""
        narrative = diff.causal_narrative or ""
        root_var, var_a, var_b, var_source = _extract_root_variable(diff, narrative)
        diag_type, diag_conf, diag_cat = _classify_error(diff, narrative)
        fix_text = _suggest_fix(diag_type, root_var, diff, narrative)

        result: Dict[str, Any] = {
            "has_diverged": diff.has_diverged,
            "summary": diff.summary,
            "trace_id_a": diff.trace_id_a,
            "trace_id_b": diff.trace_id_b,
        }

        if diff.has_diverged:
            result["verdict"] = _build_verdict(diff, narrative)
            result["root_cause"] = {
                "variable": root_var,
                "run_a": var_a,
                "run_b": var_b,
                "source": var_source,
            }
            result["diagnosis"] = {
                "type": diag_type,
                "confidence": diag_conf,
                "category": diag_cat,
            }
            result["fix_suggestions"] = fix_text
            result["first_divergence"] = {
                "type": diff.first_divergence.type if diff.first_divergence else "none",
                "id": diff.first_divergence.id if diff.first_divergence else "",
                "description": diff.first_divergence.description if diff.first_divergence else "",
            }
            result["output"] = {
                "diverged": diff.output_diverged,
                "run_a": diff.output_a,
                "run_b": diff.output_b,
            }
            result["paths"] = {
                "run_a": diff.run_a_path,
                "run_b": diff.run_b_path,
            }
            result["causal_chain"] = diff.causal_chain
            result["branch_diffs"] = [
                {
                    "condition": bd.condition,
                    "run_a_path": bd.run_a_path,
                    "run_b_path": bd.run_b_path,
                    "diverged": bd.diverged,
                }
                for bd in diff.branch_diffs
            ]
            result["step_diffs"] = [
                {
                    "step_name": sd.step_name,
                    "only_in": sd.only_in,
                    "run_a_status": sd.run_a_status,
                    "run_b_status": sd.run_b_status,
                    "run_a_error": sd.run_a_error,
                    "run_b_error": sd.run_b_error,
                    "diverged": sd.diverged,
                }
                for sd in diff.step_diffs if sd.diverged
            ]

        return result

    def _render_executive(self, diff: TraceDiffResult) -> str:
        """Render one-line executive summary."""
        lines = []
        hdr = "=" * 58
        lines.append("")
        lines.append(hdr)
        if diff.has_diverged:
            lines.append("  ROOT CAUSE FOUND")
        else:
            lines.append("  NO DIFFERENCE")
        lines.append(hdr)
        lines.append(f"  {diff.summary}")
        lines.append("")
        return "\n".join(lines)

    def _render_engineer(self, diff: TraceDiffResult) -> str:
        """Render engineer-level view: decision + path + divergence."""
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

        lines.append("")
        lines.append(hdr)
        lines.append("  ROOT CAUSE FOUND")
        lines.append(hdr)
        lines.append("")
        lines.append(f"  {diff.summary}")
        lines.append("")

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
            lines.append("  -> Final output differs")
            if out_a:
                lines.append(f"     run_a: {out_a}")
            if out_b:
                lines.append(f"     run_b: {out_b}")
        else:
            lines.append("  -> Output converged (same result via different paths)")
        lines.append("")
        lines.append(hdr)
        return "\n".join(lines)

    def _render_debug(self, diff: TraceDiffResult) -> str:
        """Render debug view with full causal chain and step diffs."""
        # Start with engineer view
        lines = self._render_engineer(diff).split("\n")
        # Remove trailing header
        while lines and lines[-1] == "=" * 58:
            lines.pop()

        # Add causal chain
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

        # Add step diffs
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
                    if sd.run_a_error != sd.run_b_error:
                        parts.append(f"error: {sd.run_a_error} -> {sd.run_b_error}")
                    lines.append(" | ".join(parts))
            lines.append("")

        lines.append("=" * 58)
        return "\n".join(lines)

    def _render_verdict(self, diff: TraceDiffResult) -> str:
        """Render interview-ready causal verdict."""
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

        # Extract structured info
        verdict_text = _build_verdict(diff, narrative)
        root_var, var_a_val, var_b_val, var_source = _extract_root_variable(diff, narrative)
        impact_line = _extract_line(narrative, "Impact score:")
        downstream_line = _extract_line(narrative, "Downstream impact:")
        diag_type, diag_conf, diag_cat = _classify_error(diff, narrative)
        fix_text = _suggest_fix(diag_type, root_var, diff, narrative)

        # VERDICT
        lines.append("")
        lines.append("  VERDICT")
        lines.append(f"  {verdict_text}")
        lines.append("")

        # ROOT CAUSE VARIABLE
        lines.append(f"  {H}")
        lines.append(f"     ROOT CAUSE VARIABLE")
        lines.append(f"  {H}")
        lines.append("")

        if root_var:
            lines.append(f"  Variable: `{root_var}` ({var_source})")
            lines.append("")
            lines.append("  Value Diff:")
            lines.append(f"    Run A: {var_a_val}")
            lines.append(f"    Run B: {var_b_val}")
        else:
            root_cause, _, _ = _extract_root_cause(diff, narrative)
            if root_cause:
                for line in root_cause.split("\n"):
                    lines.append(f"  {line}")
        lines.append("")

        # BLAST RADIUS
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
            lines.append("  Failure cascade:")
            lines.append("")
            for line in cascade:
                lines.append(f"  {line}")
            lines.append("")

        # WHY
        why = _build_why_explanation(diff, narrative)
        if why:
            lines.append(f"  {H}")
            lines.append(f"     WHY")
            lines.append(f"  {H}")
            lines.append("")
            for line in why:
                lines.append(f"  {line}")
            lines.append("")

        # DIAGNOSIS + FIX
        lines.append(f"  {H}")
        lines.append(f"     DIAGNOSIS")
        lines.append(f"  {H}")
        lines.append("")
        lines.append(f"  Type:    {diag_type}")
        lines.append(f"  Confidence: {diag_conf}")
        lines.append(f"  Category:   {diag_cat}")
        lines.append("")

        if fix_text:
            lines.append("  Suggested Fix:")
            for fix_line in fix_text:
                lines.append(f"    {fix_line}")
            lines.append("")

        lines.append(f"  {H}")
        return "\n".join(lines)


# Convenience functions for backward compatibility
def render_diff(diff: TraceDiffResult, level: int = 2) -> str:
    """Backward-compatible render_diff."""
    format_map = {
        1: RenderFormat.EXECUTIVE,
        2: RenderFormat.ENGINEER,
        3: RenderFormat.DEBUG,
    }
    fmt = format_map.get(level, RenderFormat.ENGINEER)
    return DiffRenderer(format=fmt).render(diff)


def render_causal_verdict(diff: TraceDiffResult) -> str:
    """Backward-compatible render_causal_verdict."""
    return DiffRenderer(format=RenderFormat.VERDICT).render(diff)


def render_diff_dict(diff: TraceDiffResult) -> Dict[str, Any]:
    """Render diff as a structured dictionary."""
    return DiffRenderer().to_dict(diff)
