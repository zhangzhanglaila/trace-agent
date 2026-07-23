"""
Unit tests for TraceDiffer causal chain auto-integration (M3.1).

Tests:
1. Verify auto-fill of causal_narrative and causal_chain when contexts are provided
2. Verify normal operation without contexts (backward compatibility)
"""
import pytest
from unittest.mock import Mock, patch

from agent_obs.trace_diff import TraceDiffer, TraceDiffResult
from agent_obs.trace_export import TraceExport, TraceRun


def test_causal_chain_auto_fill_with_contexts():
    """Test that causal_narrative and causal_chain are auto-populated when contexts are provided."""
    # Create mock trace exports
    export_a = Mock(spec=TraceExport)
    export_a.trace_id = "trace_a"
    export_a.runs = []
    export_a.branches = []

    export_b = Mock(spec=TraceExport)
    export_b.trace_id = "trace_b"
    export_b.runs = []
    export_b.branches = []

    # Create mock contexts
    ctx_a = Mock()
    ctx_b = Mock()

    # Mock explain_diff to return a known narrative
    mock_narrative = """Causal Chain Comparison:
----------------------------------------
  = Step 1: classify_intent
  A: Step 2: tool_selector
  B: Step 2: different_tool
      var: selected_tool: "tool_a" -> "tool_b"

Root Cause Analysis:
----------------------------------------
Root cause: variable change
  selected_tool: "tool_a" -> "tool_b"
  └ caused by: Step 2: tool_selector
Downstream impact: 1 step(s) affected
Impact score: 3 (blast radius: 1/2 steps)"""

    with patch('agent_obs.trace_core.explain_diff', return_value=mock_narrative):
        # Create differ with contexts
        differ = TraceDiffer(export_a, export_b, context_a=ctx_a, context_b=ctx_b)
        result = differ.diff()

        # Verify auto-fill occurred
        assert result.causal_narrative == mock_narrative
        assert len(result.causal_chain) > 0
        # Check that causal_chain contains extracted steps
        assert any("classify_intent" in step for step in result.causal_chain)


def test_backward_compatibility_without_contexts():
    """Test that TraceDiffer works normally without contexts (backward compatibility)."""
    # Create minimal trace exports
    export_a = Mock(spec=TraceExport)
    export_a.trace_id = "trace_a"
    export_a.runs = []
    export_a.branches = []

    export_b = Mock(spec=TraceExport)
    export_b.trace_id = "trace_b"
    export_b.runs = []
    export_b.branches = []

    # Create differ without contexts
    differ = TraceDiffer(export_a, export_b)
    result = differ.diff()

    # Verify basic result structure
    assert result.trace_id_a == "trace_a"
    assert result.trace_id_b == "trace_b"
    # causal_narrative and causal_chain should be empty/default
    assert result.causal_narrative == ""
    assert result.causal_chain == []


def test_causal_chain_extraction_logic():
    """Test that _extract_causal_chain correctly parses narrative format."""
    export_a = Mock(spec=TraceExport)
    export_a.trace_id = "trace_a"
    export_a.runs = []
    export_a.branches = []

    export_b = Mock(spec=TraceExport)
    export_b.trace_id = "trace_b"
    export_b.runs = []
    export_b.branches = []

    ctx_a = Mock()
    ctx_b = Mock()

    # Test narrative with various step formats
    mock_narrative = """Causal Chain Comparison:
----------------------------------------
  = Step 1: root_step
  A: Step 2: branch_a
  B: Step 2: branch_b
      var: key: "value_a" -> "value_b"
  = Step 3: common_step

Root Cause Analysis:
----------------------------------------
Both runs followed identical paths."""

    with patch('agent_obs.trace_core.explain_diff', return_value=mock_narrative):
        differ = TraceDiffer(export_a, export_b, context_a=ctx_a, context_b=ctx_b)
        result = differ.diff()

        # Verify extraction
        assert len(result.causal_chain) == 4  # 4 steps in the chain section
        assert any("root_step" in step for step in result.causal_chain)
        assert any("branch_a" in step for step in result.causal_chain)
        assert any("branch_b" in step for step in result.causal_chain)
        assert any("common_step" in step for step in result.causal_chain)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
