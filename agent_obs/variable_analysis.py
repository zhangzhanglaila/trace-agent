"""
Variable Analysis Module: Robust variable-level difference extraction (M3.3).

Extracts variable differences directly from step structure, not from text parsing.
Prioritizes variables by causal significance.
"""
from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Tuple
from enum import Enum


class VariablePriority(Enum):
    """Priority levels for variables based on causal significance."""
    HIGHEST = 0  # selected_tool - routing decision
    HIGH = 1     # *_result - tool outputs
    MEDIUM = 2   # plan - planning output
    NORMAL = 3   # intent - classification
    LOW = 4      # input.* - routing input
    LOWEST = 5   # other


@dataclass
class VariableDiff:
    """A single variable difference between two runs."""
    name: str
    value_a: Any
    value_b: Any
    priority: VariablePriority
    source: str  # Description of where the variable came from

    def __str__(self) -> str:
        """Format as: name: "value_a" → "value_b" """
        # Truncate long values
        val_a = self._truncate(self.value_a)
        val_b = self._truncate(self.value_b)
        return f'{self.name}: "{val_a}" → "{val_b}"'

    def _truncate(self, value: Any) -> str:
        """Truncate long values for display."""
        if isinstance(value, dict):
            # Extract 'result' key if present
            result = value.get("result", value)
            if isinstance(result, dict):
                # Show key fields concisely
                parts = [f"{k}={str(v)[:30]}" for k, v in list(result.items())[:2]]
                return "{" + ", ".join(parts) + "}"
            return str(result)[:50]
        s = str(value)
        return s[:50] if len(s) > 50 else s


class VariableAnalyzer:
    """
    Analyze variable differences between two runs.

    Extracts variables directly from step 'produces' fields,
    prioritizes by causal significance.
    """

    # Priority mapping for variable names
    PRIORITY_RULES = [
        (lambda n: n == "selected_tool", VariablePriority.HIGHEST, "LLM routing decision"),
        (lambda n: n.endswith("_result"), VariablePriority.HIGH, "tool output"),
        (lambda n: n == "plan", VariablePriority.MEDIUM, "LLM planning output"),
        (lambda n: n == "intent", VariablePriority.NORMAL, "LLM classification"),
        (lambda n: n.startswith("input."), VariablePriority.LOW, "routing input"),
        (lambda n: n in ("should_search", "should_calculate", "route_to_", "need_",
                        "needs_", "advice_", "risk_"),
         VariablePriority.LOWEST, "decision evaluation"),
    ]

    def __init__(self, steps_a: List[Dict], steps_b: List[Dict]):
        """
        Initialize analyzer with step lists from two runs.

        Args:
            steps_a: List of step dicts from run A (with 'produces' field)
            steps_b: List of step dicts from run B (with 'produces' field)
        """
        self.steps_a = steps_a
        self.steps_b = steps_b

    def extract_all_variables(self, steps: List[Dict]) -> Dict[str, Any]:
        """Extract all produced variables from a list of steps."""
        variables = {}
        for step in steps:
            produces = step.get("produces", {})
            if isinstance(produces, dict):
                variables.update(produces)
        return variables

    def get_priority(self, var_name: str) -> VariablePriority:
        """Determine priority for a variable name."""
        for rule, priority, _ in self.PRIORITY_RULES:
            if rule(var_name):
                return priority
        return VariablePriority.LOWEST

    def get_source(self, var_name: str) -> str:
        """Get human-readable source description for a variable."""
        for rule, _, source in self.PRIORITY_RULES:
            if rule(var_name):
                return source
        return "trace variable"

    def diff(self) -> List[VariableDiff]:
        """
        Compare variables between two runs.

        Returns a list of VariableDiff sorted by priority.
        """
        vars_a = self.extract_all_variables(self.steps_a)
        vars_b = self.extract_all_variables(self.steps_b)

        # Find differences
        diffs = []
        all_names = set(vars_a.keys()) | set(vars_b.keys())

        for name in all_names:
            val_a = vars_a.get(name)
            val_b = vars_b.get(name)

            # Skip if values are the same
            if val_a == val_b:
                continue

            # Handle None values
            if val_a is None and val_b is None:
                continue
            if (val_a is None and val_b is not None) or (val_a is not None and val_b is None):
                # One is None, one isn't - that's a difference
                pass

            priority = self.get_priority(name)
            source = self.get_source(name)

            diffs.append(VariableDiff(
                name=name,
                value_a=val_a,
                value_b=val_b,
                priority=priority,
                source=source,
            ))

        # Sort by priority (lower number = higher priority)
        diffs.sort(key=lambda d: d.priority.value)
        return diffs

    def get_root_cause_variable(self) -> Optional[Tuple[str, Any, Any, str]]:
        """
        Get the most significant variable difference (root cause).

        Returns (name, value_a, value_b, source) or None.
        """
        diffs = self.diff()
        if not diffs:
            return None
        root = diffs[0]
        return (root.name, root.value_a, root.value_b, root.source)


def extract_variable_diff(steps_a: List[Dict], steps_b: List[Dict]) -> List[str]:
    """
    One-liner: extract variable diffs as formatted strings.

    Returns list of "name: 'value_a' → 'value_b'" strings.
    """
    analyzer = VariableAnalyzer(steps_a, steps_b)
    diffs = analyzer.diff()
    return [str(d) for d in diffs]
