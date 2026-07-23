"""
Unit tests for diff_renderer module (M3.4).

Tests:
1. Executive format output
2. Engineer format output
3. Debug format output
4. Verdict format output
5. JSON/dict output
6. Backward-compatible convenience functions
"""
import pytest
from unittest.mock import Mock

from agent_obs.diff_renderer import (
    DiffRenderer,
    RenderFormat,
    render_diff,
    render_causal_verdict,
    render_diff_dict,
)
from agent_obs.trace_diff import (
    TraceDiffResult,
    BranchDiff,
    StepDiff,
    FirstDivergence,
)


def _create_divergent_diff():
    """Helper to create a divergent diff result."""
    branch = BranchDiff(
        branch_id="should_search",
        condition="should_search",
        run_a_path="true",
        run_b_path="false",
        diverged=True,
    )
    step = StepDiff(
        step_name="Tool: weather",
        run_a_status="success",
        run_b_status="error",
        run_b_error="API timeout",
        diverged=True,
    )
    first_div = FirstDivergence(
        type="branch",
        id="should_search",
        description="Decision should_search evaluated differently",
    )

    return TraceDiffResult(
        trace_id_a="trace_a",
        trace_id_b="trace_b",
        branch_diffs=[branch],
        step_diffs=[step],
        first_divergence=first_div,
        run_a_path=["weather"],
        run_b_path=["calculator"],
        output_a="Weather is sunny",
        output_b="Error: API timeout",
        output_diverged=True,
        has_diverged=True,
        summary="Output diverged because should_search flipped",
        causal_narrative="Causal Chain Comparison:\n  = Step 1: classify\n  A: Step 2: search\n  B: Step 2: calculate",
        causal_chain=["= Step 1: classify", "A: Step 2: search", "B: Step 2: calculate"],
    )


def _create_identical_diff():
    """Helper to create a non-divergent diff result."""
    return TraceDiffResult(
        trace_id_a="trace_a",
        trace_id_b="trace_b",
        branch_diffs=[],
        step_diffs=[],
        first_divergence=FirstDivergence(type="none", id="", description="No divergence"),
        run_a_path=["weather"],
        run_b_path=["weather"],
        output_a="Sunny",
        output_b="Sunny",
        output_diverged=False,
        has_diverged=False,
        summary="Both runs followed identical paths",
    )


def test_executive_format():
    """Test executive format renders one-line summary."""
    diff = _create_divergent_diff()
    renderer = DiffRenderer(format=RenderFormat.EXECUTIVE)
    output = renderer.render(diff)

    assert "ROOT CAUSE FOUND" in output
    assert diff.summary in output
    assert "Decision Change" not in output  # Executive should not include engineer details


def test_engineer_format():
    """Test engineer format includes decision, path, and result."""
    diff = _create_divergent_diff()
    renderer = DiffRenderer(format=RenderFormat.ENGINEER)
    output = renderer.render(diff)

    assert "ROOT CAUSE FOUND" in output
    assert "[Decision Change]" in output
    assert "should_search" in output
    assert "[Path Impact]" in output
    assert "[Result]" in output
    assert "Final output differs" in output


def test_debug_format():
    """Test debug format includes causal chain and step diffs."""
    diff = _create_divergent_diff()
    renderer = DiffRenderer(format=RenderFormat.DEBUG)
    output = renderer.render(diff)

    assert "[Causal Explanation]" in output
    assert "classify" in output
    assert "search" in output
    assert "calculate" in output
    assert "[Step Deltas]" in output
    assert "Tool: weather" in output


def test_verdict_format():
    """Test verdict format includes all verdict sections."""
    diff = _create_divergent_diff()
    renderer = DiffRenderer(format=RenderFormat.VERDICT)
    output = renderer.render(diff)

    assert "VERDICT" in output
    assert "ROOT CAUSE VARIABLE" in output
    assert "BLAST RADIUS" in output
    assert "DIAGNOSIS" in output
    assert "Type:" in output
    assert "Confidence:" in output
    assert "Suggested Fix:" in output


def test_identical_runs():
    """Test renderer with non-divergent traces."""
    diff = _create_identical_diff()

    for fmt in [RenderFormat.EXECUTIVE, RenderFormat.ENGINEER,
                RenderFormat.DEBUG, RenderFormat.VERDICT]:
        renderer = DiffRenderer(format=fmt)
        output = renderer.render(diff)
        assert "NO DIFFERENCE" in output or "No divergence detected" in output


def test_to_dict_structure():
    """Test dictionary output structure."""
    diff = _create_divergent_diff()
    renderer = DiffRenderer()
    result = renderer.to_dict(diff)

    assert result["has_diverged"] is True
    assert result["trace_id_a"] == "trace_a"
    assert result["trace_id_b"] == "trace_b"
    assert "verdict" in result
    assert "root_cause" in result
    assert "diagnosis" in result
    assert "fix_suggestions" in result
    assert "first_divergence" in result
    assert "output" in result
    assert "paths" in result
    assert "branch_diffs" in result
    assert "step_diffs" in result
    assert "causal_chain" in result


def test_to_dict_identical():
    """Test dictionary output for identical runs."""
    diff = _create_identical_diff()
    renderer = DiffRenderer()
    result = renderer.to_dict(diff)

    assert result["has_diverged"] is False
    assert result["summary"] == diff.summary
    assert "diagnosis" not in result  # Should not include detailed diagnosis for identical runs


def test_backward_compatible_render_diff():
    """Test backward-compatible render_diff function."""
    diff = _create_divergent_diff()

    level1 = render_diff(diff, level=1)
    assert "ROOT CAUSE FOUND" in level1
    assert "Decision Change" not in level1

    level2 = render_diff(diff, level=2)
    assert "[Decision Change]" in level2

    level3 = render_diff(diff, level=3)
    assert "[Causal Explanation]" in level3


def test_backward_compatible_render_causal_verdict():
    """Test backward-compatible render_causal_verdict function."""
    diff = _create_divergent_diff()
    output = render_causal_verdict(diff)

    assert "VERDICT" in output
    assert "DIAGNOSIS" in output
    assert "ROOT CAUSE VARIABLE" in output


def test_render_diff_dict():
    """Test render_diff_dict convenience function."""
    diff = _create_divergent_diff()
    result = render_diff_dict(diff)

    assert isinstance(result, dict)
    assert result["has_diverged"] is True
    assert "verdict" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
