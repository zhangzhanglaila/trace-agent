"""
Unit tests for variable_analysis module (M3.3).

Tests:
1. Variable extraction from steps
2. Priority ordering (selected_tool > *_result > plan > intent > input.*)
3. Value comparison and formatting
"""
import pytest
from agent_obs.variable_analysis import (
    VariableDiff,
    VariableAnalyzer,
    VariablePriority,
    extract_variable_diff,
)


def test_variable_extraction():
    """Test that VariableAnalyzer correctly extracts variables from steps."""
    steps_a = [
        {"id": "s1", "produces": {"selected_tool": "tool_a", "intent": "search"}},
        {"id": "s2", "produces": {"weather_result": "sunny", "temperature": 25}},
    ]
    steps_b = [
        {"id": "s1", "produces": {"selected_tool": "tool_b", "intent": "search"}},
        {"id": "s2", "produces": {"weather_result": "rainy", "temperature": 20}},
    ]

    analyzer = VariableAnalyzer(steps_a, steps_b)
    vars_a = analyzer.extract_all_variables(steps_a)
    vars_b = analyzer.extract_all_variables(steps_b)

    # Verify extraction
    assert "selected_tool" in vars_a
    assert "intent" in vars_a
    assert "weather_result" in vars_a
    assert "temperature" in vars_a
    assert vars_a["selected_tool"] == "tool_a"
    assert vars_b["selected_tool"] == "tool_b"


def test_priority_ordering():
    """Test that variables are sorted by priority correctly."""
    steps_a = [
        {"id": "s1", "produces": {"input.city": "Paris"}},
        {"id": "s2", "produces": {"intent": "search"}},
        {"id": "s3", "produces": {"plan": "use_tool"}},
        {"id": "s4", "produces": {"weather_result": "sunny"}},
        {"id": "s5", "produces": {"selected_tool": "weather_api"}},
    ]
    steps_b = [
        {"id": "s1", "produces": {"input.city": "Tokyo"}},
        {"id": "s2", "produces": {"intent": "calculate"}},
        {"id": "s3", "produces": {"plan": "use_calculator"}},
        {"id": "s4", "produces": {"weather_result": "cloudy"}},
        {"id": "s5", "produces": {"selected_tool": "calculator"}},
    ]

    analyzer = VariableAnalyzer(steps_a, steps_b)
    diffs = analyzer.diff()

    # Should have 5 differences
    assert len(diffs) == 5

    # First should be selected_tool (HIGHEST priority)
    assert diffs[0].name == "selected_tool"
    assert diffs[0].priority == VariablePriority.HIGHEST

    # Second should be weather_result (HIGH priority, *_result)
    assert diffs[1].name == "weather_result"
    assert diffs[1].priority == VariablePriority.HIGH

    # Third should be plan (MEDIUM priority)
    assert diffs[2].name == "plan"
    assert diffs[2].priority == VariablePriority.MEDIUM

    # Fourth should be intent (NORMAL priority)
    assert diffs[3].name == "intent"
    assert diffs[3].priority == VariablePriority.NORMAL

    # Fifth should be input.city (LOW priority)
    assert diffs[4].name == "input.city"
    assert diffs[4].priority == VariablePriority.LOW


def test_value_comparison():
    """Test that value comparison works correctly."""
    steps_a = [
        {"id": "s1", "produces": {"count": 5, "flag": True}},
        {"id": "s2", "produces": {"data": {"result": "success", "score": 0.9}}},
    ]
    steps_b = [
        {"id": "s1", "produces": {"count": 10, "flag": False}},
        {"id": "s2", "produces": {"data": {"result": "failure", "score": 0.3}}},
    ]

    analyzer = VariableAnalyzer(steps_a, steps_b)
    diffs = analyzer.diff()

    # Should find 3 differences (count, flag, data)
    assert len(diffs) == 3

    # Check numeric values
    count_diff = next(d for d in diffs if d.name == "count")
    assert count_diff.value_a == 5
    assert count_diff.value_b == 10

    # Check boolean values
    flag_diff = next(d for d in diffs if d.name == "flag")
    assert flag_diff.value_a is True
    assert flag_diff.value_b is False


def test_value_formatting():
    """Test VariableDiff string formatting."""
    # Simple values
    diff = VariableDiff(
        name="test_var",
        value_a="value_a",
        value_b="value_b",
        priority=VariablePriority.LOWEST,
        source="test"
    )
    assert str(diff) == 'test_var: "value_a" → "value_b"'

    # Long values should be truncated (to 50 chars)
    diff_long = VariableDiff(
        name="long_var",
        value_a="a" * 100,
        value_b="b" * 100,
        priority=VariablePriority.LOWEST,
        source="test"
    )
    formatted = str(diff_long)
    # Should be truncated to 50 characters
    assert len(formatted.split('" → "')[0].split(': "')[1]) == 50
    assert len(formatted.split('" → "')[1].rstrip('"')) == 50

    # Dict values should extract 'result' key
    diff_dict = VariableDiff(
        name="dict_var",
        value_a={"result": "success", "details": "more info here"},
        value_b={"result": "failure", "details": "even more details"},
        priority=VariablePriority.HIGH,
        source="tool output"
    )
    formatted_dict = str(diff_dict)
    assert "success" in formatted_dict
    assert "failure" in formatted_dict


def test_get_root_cause_variable():
    """Test get_root_cause_variable returns highest priority diff."""
    steps_a = [
        {"id": "s1", "produces": {"low_priority_var": "a"}},
        {"id": "s2", "produces": {"high_priority_result": "x"}},
        {"id": "s3", "produces": {"selected_tool": "tool_a"}},
    ]
    steps_b = [
        {"id": "s1", "produces": {"low_priority_var": "b"}},
        {"id": "s2", "produces": {"high_priority_result": "y"}},
        {"id": "s3", "produces": {"selected_tool": "tool_b"}},
    ]

    analyzer = VariableAnalyzer(steps_a, steps_b)
    root = analyzer.get_root_cause_variable()

    # Should return selected_tool (highest priority)
    assert root is not None
    assert root[0] == "selected_tool"
    assert root[1] == "tool_a"
    assert root[2] == "tool_b"
    assert root[3] == "LLM routing decision"


def test_no_differences():
    """Test behavior when there are no differences."""
    steps = [
        {"id": "s1", "produces": {"var1": "same", "var2": 42}},
    ]

    analyzer = VariableAnalyzer(steps, steps)
    diffs = analyzer.diff()

    # Should have no differences
    assert len(diffs) == 0

    # get_root_cause_variable should return None
    root = analyzer.get_root_cause_variable()
    assert root is None


def test_extract_variable_diff_one_liner():
    """Test the one-liner extract_variable_diff function."""
    steps_a = [
        {"id": "s1", "produces": {"tool": "A"}},
        {"id": "s2", "produces": {"result": "success"}},
    ]
    steps_b = [
        {"id": "s1", "produces": {"tool": "B"}},
        {"id": "s2", "produces": {"result": "failure"}},
    ]

    diffs = extract_variable_diff(steps_a, steps_b)

    # Should return list of formatted strings
    assert len(diffs) == 2
    assert all(" → " in d for d in diffs)
    assert any("tool" in d for d in diffs)


def test_none_value_handling():
    """Test handling of None values."""
    steps_a = [
        {"id": "s1", "produces": {"var1": "value", "var2": None}},
    ]
    steps_b = [
        {"id": "s1", "produces": {"var1": "value", "var2": "exists"}},
    ]

    analyzer = VariableAnalyzer(steps_a, steps_b)
    diffs = analyzer.diff()

    # var1 is same, var2 differs (None vs "exists")
    assert len(diffs) == 1
    assert diffs[0].name == "var2"
    assert diffs[0].value_a is None
    assert diffs[0].value_b == "exists"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
