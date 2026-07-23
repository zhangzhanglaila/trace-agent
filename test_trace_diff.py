"""
Unit tests for TraceDiffer (M3.4).

Tests:
1. Branch alignment
2. Step alignment
3. First divergence detection
4. Output divergence detection
5. Path summary construction
6. Backward compatibility (no contexts)
"""
import pytest
from unittest.mock import Mock

from agent_obs.trace_diff import (
    TraceDiffer,
    TraceDiffResult,
    BranchDiff,
    StepDiff,
    FirstDivergence,
)
from agent_obs.trace_export import TraceExport, TraceRun


def _create_trace_export(runs, branches=None, trace_id="test_trace"):
    """Helper to create a TraceExport mock."""
    export = Mock(spec=TraceExport)
    export.trace_id = trace_id
    export.runs = runs or []
    export.branches = branches or []
    return export


def _create_run(run_id, name, run_type="tool", status="success", error=None,
                inputs=None, outputs=None, branch_info=None):
    """Helper to create a TraceRun mock."""
    run = Mock(spec=TraceRun)
    run.id = run_id
    run.name = name
    run.run_type = run_type
    run.status = status
    run.error = error
    run.inputs = inputs or {}
    run.outputs = outputs or {}
    run.branch_info = branch_info
    return run


def test_branch_alignment_same_path():
    """Test branch alignment when both runs take the same path."""
    runs_a = [_create_run("r1", "Branch: should_search", "branch", branch_info={"condition_value": True})]
    runs_b = [_create_run("r1", "Branch: should_search", "branch", branch_info={"condition_value": True})]

    branches = [{"condition": "should_search", "branch_step": "r1"}]

    export_a = _create_trace_export(runs_a, branches, "trace_a")
    export_b = _create_trace_export(runs_b, branches, "trace_b")

    differ = TraceDiffer(export_a, export_b)
    result = differ.diff()

    assert len(result.branch_diffs) == 1
    assert result.branch_diffs[0].diverged is False
    assert result.branch_diffs[0].run_a_path == "true"
    assert result.branch_diffs[0].run_b_path == "true"


def test_branch_alignment_diverged():
    """Test branch alignment when runs take different paths."""
    runs_a = [_create_run("r1", "Branch: should_search", "branch", branch_info={"condition_value": True})]
    runs_b = [_create_run("r1", "Branch: should_search", "branch", branch_info={"condition_value": False})]

    branches = [{"condition": "should_search", "branch_step": "r1"}]

    export_a = _create_trace_export(runs_a, branches, "trace_a")
    export_b = _create_trace_export(runs_b, branches, "trace_b")

    differ = TraceDiffer(export_a, export_b)
    result = differ.diff()

    assert len(result.branch_diffs) == 1
    assert result.branch_diffs[0].diverged is True
    assert result.branch_diffs[0].run_a_path == "true"
    assert result.branch_diffs[0].run_b_path == "false"


def test_step_alignment_with_status_difference():
    """Test step alignment detecting status differences."""
    runs_a = [_create_run("r1", "Tool: weather", "tool", status="success")]
    runs_b = [_create_run("r1", "Tool: weather", "tool", status="error", error="API timeout")]

    export_a = _create_trace_export(runs_a, [], "trace_a")
    export_b = _create_trace_export(runs_b, [], "trace_b")

    differ = TraceDiffer(export_a, export_b)
    result = differ.diff()

    assert len(result.step_diffs) == 1
    assert result.step_diffs[0].diverged is True
    assert result.step_diffs[0].run_a_status == "success"
    assert result.step_diffs[0].run_b_status == "error"
    assert result.step_diffs[0].run_b_error == "API timeout"


def test_step_alignment_only_in_one_run():
    """Test detection of steps only present in one run."""
    runs_a = [
        _create_run("r1", "Tool: weather", "tool"),
        _create_run("r2", "Tool: activity_search", "tool"),
    ]
    runs_b = [_create_run("r1", "Tool: weather", "tool")]

    export_a = _create_trace_export(runs_a, [], "trace_a")
    export_b = _create_trace_export(runs_b, [], "trace_b")

    differ = TraceDiffer(export_a, export_b)
    result = differ.diff()

    assert len(result.step_diffs) == 2
    only_in_a = [sd for sd in result.step_diffs if sd.only_in == "run_a"]
    assert len(only_in_a) == 1
    assert only_in_a[0].step_name == "Tool: activity_search"


def test_first_divergence_branch():
    """Test first divergence detection prioritizes branches."""
    runs_a = [
        _create_run("r1", "Branch: should_search", "branch", branch_info={"condition_value": True}),
        _create_run("r2", "Tool: weather", "tool"),
    ]
    runs_b = [
        _create_run("r1", "Branch: should_search", "branch", branch_info={"condition_value": False}),
        _create_run("r3", "Tool: calculator", "tool"),
    ]

    branches = [{"condition": "should_search", "branch_step": "r1"}]

    export_a = _create_trace_export(runs_a, branches, "trace_a")
    export_b = _create_trace_export(runs_b, branches, "trace_b")

    differ = TraceDiffer(export_a, export_b)
    result = differ.diff()

    assert result.first_divergence is not None
    assert result.first_divergence.type == "branch"
    assert result.first_divergence.id == "should_search"


def test_first_divergence_step():
    """Test first divergence detection falls back to steps when no branch divergence."""
    runs_a = [_create_run("r1", "Tool: weather", "tool")]
    runs_b = [
        _create_run("r1", "Tool: weather", "tool"),
        _create_run("r2", "Tool: activity_search", "tool"),
    ]

    export_a = _create_trace_export(runs_a, [], "trace_a")
    export_b = _create_trace_export(runs_b, [], "trace_b")

    differ = TraceDiffer(export_a, export_b)
    result = differ.diff()

    assert result.first_divergence is not None
    assert result.first_divergence.type == "step"
    assert "activity_search" in result.first_divergence.id


def test_path_summary():
    """Test path summary construction."""
    runs_a = [
        _create_run("r1", "Tool: weather", "tool", inputs={"tool": "weather"}),
        _create_run("r2", "LLM: summarize", "llm"),
    ]
    runs_b = [
        _create_run("r1", "Tool: calculator", "tool", inputs={"tool": "calculator"}),
        _create_run("r2", "LLM: summarize", "llm"),
    ]

    export_a = _create_trace_export(runs_a, [], "trace_a")
    export_b = _create_trace_export(runs_b, [], "trace_b")

    differ = TraceDiffer(export_a, export_b)
    result = differ.diff()

    assert result.run_a_path == ["weather", "llm"]
    assert result.run_b_path == ["calculator", "llm"]


def test_output_divergence():
    """Test output divergence detection."""
    runs_a = [_create_run("r1", "Output", "output", outputs={"value": "result_a"})]
    runs_b = [_create_run("r1", "Output", "output", outputs={"value": "result_b"})]

    export_a = _create_trace_export(runs_a, [], "trace_a")
    export_b = _create_trace_export(runs_b, [], "trace_b")

    differ = TraceDiffer(export_a, export_b)
    result = differ.diff()

    assert result.output_diverged is True
    assert result.output_a == "result_a"
    assert result.output_b == "result_b"
    assert result.has_diverged is True


def test_no_divergence():
    """Test identical traces produce no divergence."""
    runs_a = [_create_run("r1", "Tool: weather", "tool")]
    runs_b = [_create_run("r1", "Tool: weather", "tool")]

    export_a = _create_trace_export(runs_a, [], "trace_a")
    export_b = _create_trace_export(runs_b, [], "trace_b")

    differ = TraceDiffer(export_a, export_b)
    result = differ.diff()

    assert result.has_diverged is False
    assert result.output_diverged is False
    assert result.first_divergence is not None
    assert result.first_divergence.type == "none"


def test_branch_step_normalization():
    """Test that branch steps are normalized for alignment."""
    runs_a = [_create_run("r1", "Branch: should_search=True", "branch")]
    runs_b = [_create_run("r1", "Branch: should_search=False", "branch")]

    export_a = _create_trace_export(runs_a, [], "trace_a")
    export_b = _create_trace_export(runs_b, [], "trace_b")

    differ = TraceDiffer(export_a, export_b)
    result = differ.diff()

    # Should align as the same step, not divergent presence
    assert len(result.step_diffs) == 1
    assert result.step_diffs[0].only_in is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
