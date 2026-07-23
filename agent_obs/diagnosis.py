"""
Diagnosis Module: Structured error classification and fix suggestions (M3.2).

Replaces keyword-matching based classification with feature-based classification.
Extracts structured features from TraceDiffResult and uses them for diagnosis.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Callable
from enum import Enum


class ErrorCategory(Enum):
    """High-level error categories."""
    PLANNING_ERROR = "Planning Error"
    RECOVERY_FAILURE = "Recovery Failure"
    EDGE_CASE_HANDLING = "Edge Case Handling"
    INPUT_SENSITIVITY = "Input Sensitivity"
    GENERAL = "General"


class ConfidenceLevel(Enum):
    """Confidence levels for diagnoses."""
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


@dataclass
class DiagnosticFeatures:
    """
    Structured features extracted from TraceDiffResult for classification.

    Features are derived from the trace structure, not text parsing.
    """
    # Step-level features
    total_steps_a: int = 0
    total_steps_b: int = 0
    divergent_steps: int = 0  # Steps with status/error/output differences

    # Error features
    error_count_a: int = 0
    error_count_b: int = 0
    total_errors: int = 0  # Combined
    has_error_in_a: bool = False
    has_error_in_b: bool = False

    # Retry pattern features
    has_retry_pattern: bool = False
    retry_count: int = 0  # Estimated retry occurrences

    # Branch features
    branch_divergences: int = 0
    branch_flip_count: int = 0  # Branches that flipped (true->false or vice versa)

    # Output features
    output_diverged: bool = False
    has_failure_output: bool = False  # [FAIL] or [PARTIAL] in output
    has_partial_output: bool = False

    # Step presence features
    steps_only_in_a: int = 0
    steps_only_in_b: int = 0

    # First divergence type (if any)
    first_divergence_type: Optional[str] = None  # "branch", "step", "value", "none"

    # Tool selection features
    tool_divergences: int = 0  # Number of tools called differently
    selected_tool_diverged: bool = False  # Whether 'selected_tool' variable changed

    @staticmethod
    def from_diff_result(diff_result: 'TraceDiffResult') -> 'DiagnosticFeatures':
        """Extract features from a TraceDiffResult."""
        features = DiagnosticFeatures()

        # Step counts
        features.total_steps_a = len(diff_result.step_diffs)
        features.total_steps_b = len(diff_result.step_diffs)

        # Error counts
        for sd in diff_result.step_diffs:
            if sd.run_a_error:
                features.error_count_a += 1
                features.has_error_in_a = True
            if sd.run_b_error:
                features.error_count_b += 1
                features.has_error_in_b = True
            if sd.diverged:
                features.divergent_steps += 1
            if sd.only_in == "run_a":
                features.steps_only_in_a += 1
            if sd.only_in == "run_b":
                features.steps_only_in_b += 1

        features.total_errors = features.error_count_a + features.error_count_b

        # Retry pattern detection: multiple errors in both runs suggest retry
        if features.error_count_a >= 2 and features.error_count_b >= 2:
            features.has_retry_pattern = True
            features.retry_count = min(features.error_count_a, features.error_count_b)
        # Also check for repeated tool names with errors
        else:
            tool_names_with_error = set()
            for sd in diff_result.step_diffs:
                if (sd.run_a_error or sd.run_b_error) and sd.step_name.startswith("Tool:"):
                    tool_names_with_error.add(sd.step_name)
            # If same tool appears multiple times with error, likely retry
            if len(tool_names_with_error) > 0 and features.total_errors >= 2:
                features.has_retry_pattern = True
                features.retry_count = features.total_errors // 2  # Rough estimate

        # Branch features
        for bd in diff_result.branch_diffs:
            if bd.diverged:
                features.branch_divergences += 1
                # Check if path flipped (true<->false, none<->true/false)
                if bd.run_a_path in ("true", "false", "none") and bd.run_b_path in ("true", "false", "none"):
                    if bd.run_a_path != bd.run_b_path:
                        features.branch_flip_count += 1

        # Output features
        features.output_diverged = diff_result.output_diverged
        output_str_a = str(diff_result.output_a) if diff_result.output_a else ""
        output_str_b = str(diff_result.output_b) if diff_result.output_b else ""
        features.has_failure_output = (
            "[FAIL]" in output_str_a or "[FAIL]" in output_str_b or
            "error" in output_str_a.lower() or "error" in output_str_b.lower()
        )
        features.has_partial_output = (
            "[PARTIAL]" in output_str_a or "[PARTIAL]" in output_str_b
        )

        # First divergence type
        if diff_result.first_divergence:
            features.first_divergence_type = diff_result.first_divergence.type

        # Tool divergence detection
        for sd in diff_result.step_diffs:
            if sd.step_name.startswith("Tool:") and sd.diverged:
                features.tool_divergences += 1
        # Check if selected_tool variable diverged (from causal_narrative)
        if diff_result.causal_narrative and "selected_tool:" in diff_result.causal_narrative:
            features.selected_tool_diverged = True

        return features


@dataclass
class Diagnosis:
    """Structured diagnosis result."""
    error_type: str  # Human-readable error type
    confidence: ConfidenceLevel
    category: ErrorCategory
    description: str  # Human-readable explanation


class ErrorClassifier:
    """
    Classify errors based on structured features, not keyword matching.

    Uses a decision-tree-like approach with clear rules.
    """

    def classify(self, features: DiagnosticFeatures) -> Diagnosis:
        """Classify error based on extracted features."""

        # ── Rule 1: Error-Retry Loop (Missing Fallback) ──
        if (features.has_retry_pattern and
            features.total_errors >= 2 and
            features.has_failure_output):
            return Diagnosis(
                error_type="Error-Retry Loop (Missing Fallback)",
                confidence=ConfidenceLevel.HIGH if features.total_errors >= 3 else ConfidenceLevel.MEDIUM,
                category=ErrorCategory.RECOVERY_FAILURE,
                description="Agent retried a failing operation without changing strategy, "
                          "leading to repeated failures."
            )

        # ── Rule 2: Tool Selection Divergence with Error ──
        if (features.tool_divergences > 0 and
            features.has_error_in_b and not features.has_error_in_a):
            return Diagnosis(
                error_type="Tool Selection Divergence → Error Cascade",
                confidence=ConfidenceLevel.HIGH,
                category=ErrorCategory.PLANNING_ERROR,
                description="The agent selected different tools between runs, "
                          "and the incorrect tool choice in Run B caused an error cascade."
            )

        # ── Rule 3: Branch Flip with Partial Output ──
        if (features.branch_flip_count > 0 and
            features.has_partial_output):
            return Diagnosis(
                error_type="Branch Condition Flip → Incomplete Output",
                confidence=ConfidenceLevel.HIGH,
                category=ErrorCategory.EDGE_CASE_HANDLING,
                description="A decision condition evaluated differently, "
                          "causing the agent to follow an incomplete path."
            )

        # ── Rule 4: Tool Output Ambiguity ──
        if (features.branch_divergences > 0 and
            features.has_partial_output and
            features.first_divergence_type == "branch"):
            return Diagnosis(
                error_type="Tool Output Ambiguity → Wrong Default",
                confidence=ConfidenceLevel.HIGH,
                category=ErrorCategory.EDGE_CASE_HANDLING,
                description="A tool produced ambiguous output, causing a "
                          "branch condition to default incorrectly."
            )

        # ── Rule 5: Input-Driven Tool Selection (No Error) ──
        if (features.tool_divergences > 0 and
            not features.has_error_in_a and not features.has_error_in_b):
            return Diagnosis(
                error_type="Input-Driven Tool Selection",
                confidence=ConfidenceLevel.HIGH,
                category=ErrorCategory.INPUT_SENSITIVITY,
                description="The inputs were different enough to cause different "
                          "tool selections, but both runs completed successfully."
            )

        # ── Rule 6: General Execution Path Divergence ──
        if features.output_diverged:
            return Diagnosis(
                error_type="Execution Path Divergence",
                confidence=ConfidenceLevel.LOW,
                category=ErrorCategory.GENERAL,
                description="The runs followed different paths and produced different outputs."
            )

        # ── Default: Minor Variation ──
        return Diagnosis(
            error_type="Minor Path Variation",
            confidence=ConfidenceLevel.LOW,
            category=ErrorCategory.GENERAL,
            description="The runs had minor differences but converged to similar results."
        )


class FixSuggester:
    """
    Generate fix suggestions based on diagnosis and features.

    Supports template-based suggestions with optional custom rules.
    """

    # Template fix suggestions by error type
    TEMPLATES: Dict[str, List[str]] = {
        "Error-Retry Loop (Missing Fallback)": [
            "Add a fallback tool for the retry path instead of re-calling the same tool.",
            "Implement exponential backoff with a different strategy on each retry.",
            "Add a maximum retry limit with a degraded but safe response.",
        ],
        "Tool Selection Divergence → Error Cascade": [
            "Add deterministic routing rules for the step where the misroute occurred.",
            "Implement tool output validation: verify that the selected tool's output "
            "matches the expected schema before proceeding.",
            "Add a tool selection guardrail with explicit preconditions for each tool.",
        ],
        "Branch Condition Flip → Incomplete Output": [
            "Add input normalization to handle edge cases that cause condition flips.",
            "Review the branch condition for boundary value handling.",
            "Default to a safe fallback path when the condition is ambiguous.",
        ],
        "Tool Output Ambiguity → Wrong Default": [
            "Add input validation on tool outputs before routing decisions.",
            "Check the root cause variable for edge cases (empty, null, unexpected format).",
            "Default to a safe fallback when confidence is low or data is missing.",
        ],
        "Input-Driven Tool Selection": [
            "Add input normalization: map similar queries to canonical tool selections.",
            "Consider introducing a confidence threshold for tool switching.",
        ],
    }

    # Custom rule registry: (diagnosis_pattern) -> suggestion_generator
    _custom_rules: List[Callable[[Diagnosis, DiagnosticFeatures], Optional[List[str]]]] = []

    @classmethod
    def register_rule(cls, rule: Callable[[Diagnosis, DiagnosticFeatures], Optional[List[str]]]):
        """Register a custom suggestion rule."""
        cls._custom_rules.append(rule)

    def suggest(self, diagnosis: Diagnosis, features: DiagnosticFeatures) -> List[str]:
        """Generate fix suggestions based on diagnosis and features."""
        suggestions = []

        # ── Try custom rules first ──
        for rule in self._custom_rules:
            custom_suggestions = rule(diagnosis, features)
            if custom_suggestions:
                suggestions.extend(custom_suggestions)

        # ── Use template-based suggestions ──
        template = self.TEMPLATES.get(diagnosis.error_type, [])
        if template:
            suggestions.extend(template)

        # ── Add specific context-aware suggestions ──
        if features.selected_tool_diverged:
            suggestions.append(
                "Consider adding a tool selection guardrail: "
                "define explicit preconditions for tool usage."
            )

        if features.branch_flip_count > 0:
            suggestions.append(
                f"Review the {features.branch_flip_count} branch condition(s) that flipped."
            )

        # ── Default suggestion ──
        if not suggestions:
            suggestions.append(
                "Review the first divergence point and add a guard condition."
            )

        return suggestions


def diagnose(diff_result: 'TraceDiffResult') -> tuple:
    """
    One-stop diagnosis: extract features, classify, and suggest fixes.

    Returns (Diagnosis, List[str] suggestions).
    """
    features = DiagnosticFeatures.from_diff_result(diff_result)
    classifier = ErrorClassifier()
    diagnosis = classifier.classify(features)

    suggester = FixSuggester()
    suggestions = suggester.suggest(diagnosis, features)

    return diagnosis, suggestions
