"""
Unit tests for diagnosis module (M3.2).

Tests:
1. DiagnosticFeatures extraction from TraceDiffResult
2. ErrorClassifier classification logic
3. FixSuggester template-based suggestions
4. Custom rule registration and execution
"""
import pytest
from agent_obs.diagnosis import (
    DiagnosticFeatures,
    ErrorClassifier,
    FixSuggester,
    ErrorCategory,
    ConfidenceLevel,
    Diagnosis,
    diagnose,
)
from agent_obs.trace_diff import TraceDiffResult, BranchDiff, StepDiff, FirstDivergence


def _create_mock_diff_result(
    error_count_a=0,
    error_count_b=0,
    has_retry=False,
    branch_divergences=0,
    output_diverged=False,
    has_failure_output=False,
    has_partial_output=False,
    first_divergence_type=None,
    tool_divergences=0,
    selected_tool_diverged=False,
):
    """Helper to create a mock TraceDiffResult with specific features."""
    # Create step diffs with errors
    step_diffs = []
    for i in range(error_count_a):
        sd = StepDiff(step_name=f"step_a_{i}")
        sd.run_a_error = f"error_{i}"
        sd.diverged = True
        step_diffs.append(sd)
    for i in range(error_count_b):
        sd = StepDiff(step_name=f"step_b_{i}")
        sd.run_b_error = f"error_{i}"
        sd.diverged = True
        step_diffs.append(sd)

    # Add tool divergences
    for i in range(tool_divergences):
        sd = StepDiff(step_name=f"Tool: tool_{i}")
        sd.diverged = True
        step_diffs.append(sd)

    # Create branch diffs
    branch_diffs = []
    for i in range(branch_divergences):
        bd = BranchDiff(
            branch_id=f"branch_{i}",
            condition=f"condition_{i}",
            run_a_path="true",
            run_b_path="false",
            diverged=True,
        )
        branch_diffs.append(bd)

    # Create first divergence
    first_divergence = FirstDivergence(
        type=first_divergence_type or "none",
        id="test_divergence",
        description="Test divergence",
    ) if first_divergence_type else None

    # Create output strings
    output_a = "[FAIL] Test failed" if has_failure_output else "Success"
    output_b = "[PARTIAL] Partial output" if has_partial_output else "Success"

    # Create causal narrative with selected_tool if needed
    narrative = ""
    if selected_tool_diverged:
        narrative = 'var: selected_tool: "tool_a" -> "tool_b"'

    return TraceDiffResult(
        trace_id_a="trace_a",
        trace_id_b="trace_b",
        step_diffs=step_diffs,
        branch_diffs=branch_diffs,
        first_divergence=first_divergence,
        output_diverged=output_diverged,
        output_a=output_a if has_failure_output or has_partial_output else ("result_a" if output_diverged else "same"),
        output_b=output_b if has_failure_output or has_partial_output else ("result_b" if output_diverged else "same"),
        causal_narrative=narrative,
    )


def test_diagnostic_features_extraction():
    """Test that DiagnosticFeatures correctly extracts features from TraceDiffResult."""
    # Create a diff result with various features
    diff = _create_mock_diff_result(
        error_count_a=2,
        error_count_b=1,
        branch_divergences=2,
        output_diverged=True,
        has_failure_output=True,
        tool_divergences=1,
    )

    features = DiagnosticFeatures.from_diff_result(diff)

    # Verify extracted features
    assert features.total_steps_a == 4  # 2 errors + 1 tool + 1 step from error_b
    assert features.total_steps_b == 4
    assert features.error_count_a == 2
    assert features.error_count_b == 1
    assert features.total_errors == 3
    assert features.has_error_in_a is True
    assert features.has_error_in_b is True
    assert features.divergent_steps == 4  # 2 errors + 1 tool (counted in both)
    assert features.branch_divergences == 2
    assert features.branch_flip_count == 2  # Both branches diverged
    assert features.output_diverged is True
    assert features.has_failure_output is True
    assert features.tool_divergences == 1


def test_error_classifier_retry_loop():
    """Test classification of error-retry loop pattern."""
    # Create a diff result with retry pattern (multiple errors in both runs)
    diff = _create_mock_diff_result(
        error_count_a=3,
        error_count_b=3,
        has_failure_output=True,
        branch_divergences=1,
    )

    features = DiagnosticFeatures.from_diff_result(diff)
    classifier = ErrorClassifier()
    diagnosis = classifier.classify(features)

    # Should classify as retry loop
    assert "Retry" in diagnosis.error_type or "Retry" in diagnosis.description
    assert diagnosis.confidence in (ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM)
    assert diagnosis.category == ErrorCategory.RECOVERY_FAILURE


def test_error_classifier_tool_divergence_with_error():
    """Test classification of tool selection divergence causing error."""
    # Create a diff result where tool divergence leads to error in run B
    diff = _create_mock_diff_result(
        error_count_b=2,
        tool_divergences=1,
        has_failure_output=True,
    )

    features = DiagnosticFeatures.from_diff_result(diff)
    classifier = ErrorClassifier()
    diagnosis = classifier.classify(features)

    # Should classify as tool selection issue
    assert "Tool" in diagnosis.error_type or "Selection" in diagnosis.error_type
    assert diagnosis.category == ErrorCategory.PLANNING_ERROR


def test_fix_suggester_templates():
    """Test that FixSuggester generates appropriate suggestions."""
    # Create a retry loop diagnosis
    diagnosis = Diagnosis(
        error_type="Error-Retry Loop (Missing Fallback)",
        confidence=ConfidenceLevel.HIGH,
        category=ErrorCategory.RECOVERY_FAILURE,
        description="Agent retried without changing strategy",
    )

    features = DiagnosticFeatures(
        has_retry_pattern=True,
        total_errors=4,
        branch_flip_count=1,
    )

    suggester = FixSuggester()
    suggestions = suggester.suggest(diagnosis, features)

    # Verify suggestions include template recommendations
    assert len(suggestions) > 0
    assert any("fallback" in s.lower() for s in suggestions)
    assert any("retry" in s.lower() for s in suggestions)
    # Should include context-aware suggestion about branch flip
    assert any("branch" in s.lower() for s in suggestions)


def test_custom_rule_registration():
    """Test that custom rules can be registered and executed."""

    # Define a custom rule
    def custom_rule(diagnosis: Diagnosis, features: DiagnosticFeatures):
        if "Test" in diagnosis.error_type:
            return ["Custom suggestion for test error"]
        return None

    # Register the rule
    FixSuggester.register_rule(custom_rule)

    # Create a test diagnosis
    diagnosis = Diagnosis(
        error_type="Test Error Pattern",
        confidence=ConfidenceLevel.MEDIUM,
        category=ErrorCategory.GENERAL,
        description="Test description",
    )

    features = DiagnosticFeatures()

    suggester = FixSuggester()
    suggestions = suggester.suggest(diagnosis, features)

    # Verify custom rule was applied
    assert any("Custom suggestion" in s for s in suggestions)

    # Clean up: remove the custom rule
    FixSuggester._custom_rules.remove(custom_rule)


def test_diagnose_one_stop_function():
    """Test the diagnose() one-stop function."""
    # Create a diff result with retry pattern
    diff = _create_mock_diff_result(
        error_count_a=3,
        error_count_b=2,
        has_failure_output=True,
    )

    diagnosis, suggestions = diagnose(diff)

    # Verify we get both diagnosis and suggestions
    assert diagnosis is not None
    assert isinstance(diagnosis, Diagnosis)
    assert len(suggestions) > 0
    assert diagnosis.error_type
    assert diagnosis.confidence in (ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM, ConfidenceLevel.LOW)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
