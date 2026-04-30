"""
CLI Trace Viewer: Renders agent trace as an ASCII tree.

Usage:
    from agent_obs.trace_viewer import TraceViewer
    viewer = TraceViewer(trace_export)
    viewer.render()
"""
from typing import Dict, Any, List, Optional
from dataclasses import dataclass


@dataclass
class TreeNode:
    """Node in the render tree."""
    id: str
    label: str
    meta: str = ""          # Timing, status info
    children: List["TreeNode"] = None
    branch_label: str = ""  # "true" or "false" for branch paths

    def __post_init__(self):
        if self.children is None:
            self.children = []


class TraceViewer:
    """
    Renders a trace export as a CLI ASCII tree.

    Supports:
    - ASCII tree rendering
    - Branch path labels (true/false)
    - Timing display per node
    - Status indicators ([OK]/[ERR])
    - JSON summary mode
    - Simple flat list mode
    """

    def __init__(self, trace_export=None):
        self.export = trace_export

    def render(self, mode: str = "tree") -> str:
        """
        Render the trace.

        Args:
            mode: "tree" (ASCII tree), "flat" (flat list), "json" (JSON summary)
        """
        if not self.export:
            return "(no trace)"

        if mode == "flat":
            return self._render_flat()
        elif mode == "json":
            return self._render_json()
        else:
            return self._render_tree()

    def print(self, mode: str = "tree"):
        """Print the rendered trace to stdout."""
        print(self.render(mode))

    def _render_tree(self) -> str:
        """Render as ASCII tree."""
        runs = self.export.runs if hasattr(self.export, 'runs') else self.export.get("runs", [])
        branches = []
        if hasattr(self.export, 'branches'):
            branches = self.export.branches
        elif isinstance(self.export, dict):
            branches = self.export.get("branches", [])

        if not runs:
            return "(no runs)"

        # Build branch lookup for path labeling
        branch_map = {}
        for b in branches:
            true_path = b.get("true_path", []) or []
            false_path = b.get("false_path", []) or []
            for sid in true_path:
                branch_map[sid] = "true"
            for sid in false_path:
                branch_map[sid] = "false"

        # Build run lookup
        run_map = {}
        for run in runs:
            rid = run.get("id") if isinstance(run, dict) else run.id
            run_map[rid] = run

        # Build tree from parent_run_id
        children_map: Dict[Optional[str], List] = {}
        for run in runs:
            rid = run.get("id") if isinstance(run, dict) else run.id
            pid = run.get("parent_run_id") if isinstance(run, dict) else run.parent_run_id
            if pid not in children_map:
                children_map[pid] = []
            children_map[pid].append(rid)

        # Find root nodes (parent_run_id is None)
        roots = children_map.get(None, [])

        lines = []
        trace_id = None
        if hasattr(self.export, 'trace_id'):
            trace_id = self.export.trace_id
        elif isinstance(self.export, dict):
            trace_id = self.export.get("trace_id")
        total_lat = self._get_attr(self.export, "total_latency_ms")

        header = f"Trace: {trace_id}"
        if total_lat:
            header += f"  [{total_lat:.0f}ms total]"
        lines.append(header)
        lines.append("=" * 60)

        for root_id in roots:
            self._render_node(root_id, run_map, children_map, branch_map,
                            lines, prefix="", is_last=True, is_root=True)

        return "\n".join(lines)

    def _render_node(self, node_id: str, run_map: Dict, children_map: Dict,
                     branch_map: Dict, lines: List[str], prefix: str,
                     is_last: bool, is_root: bool = False):
        """Render a single node and its children recursively."""
        run = run_map.get(node_id)
        if not run:
            return

        # Build connector
        if is_root:
            connector = ""
        elif is_last:
            connector = prefix + "└── "
        else:
            connector = prefix + "├── "

        # Build label
        name = self._get_attr(run, "name", "?")
        run_type = self._get_attr(run, "run_type", "?")
        status = self._get_attr(run, "status", "success")
        latency = self._get_attr(run, "latency_ms")
        error = self._get_attr(run, "error")

        # Status icon
        status_icon = "[OK]" if status == "success" else "[ERR]"

        # Branch label
        branch_label = branch_map.get(node_id, "")
        label_parts = [f"[{run_type}]"]
        if branch_label:
            label_parts.append(f"({branch_label})")
        label_parts.append(name)

        # Timing
        if latency is not None:
            label_parts.append(f"[{latency:.0f}ms]")

        # Error
        if error:
            label_parts.append(f"[ERROR: {error}]")

        line = f"{connector}{status_icon} {' '.join(label_parts)}"
        lines.append(line)

        # Render children
        children = children_map.get(node_id, [])
        if not children:
            return

        # Sort children: branch step's children come first, then sequential
        child_prefix = prefix + ("    " if is_last else "│   ")

        for i, child_id in enumerate(children):
            is_last_child = (i == len(children) - 1)
            self._render_node(child_id, run_map, children_map, branch_map,
                            lines, child_prefix, is_last_child, is_root=False)

    def _render_flat(self) -> str:
        """Render as a flat list."""
        runs = self.export.runs if hasattr(self.export, 'runs') else self.export.get("runs", [])
        if not runs:
            return "(no runs)"

        lines = ["Trace Steps:", "-" * 40]
        for run in runs:
            rid = self._get_attr(run, "id", "?")
            name = self._get_attr(run, "name", "?")
            run_type = self._get_attr(run, "run_type", "?")
            latency = self._get_attr(run, "latency_ms")
            status = self._get_attr(run, "status", "success")
            parent = self._get_attr(run, "parent_run_id", "root")

            timing = f" [{latency:.0f}ms]" if latency else ""
            status_mark = "[OK]" if status == "success" else "[ERR]"
            lines.append(f"  {status_mark} {rid} [{run_type}] {name}{timing}  (parent: {parent})")

        return "\n".join(lines)

    def _render_json(self) -> str:
        """Render as JSON summary."""
        import json
        if hasattr(self.export, 'to_dict'):
            return json.dumps(self.export.to_dict(), indent=2, ensure_ascii=False, default=str)
        return json.dumps(self.export, indent=2, ensure_ascii=False, default=str)

    @staticmethod
    def _get_attr(obj, attr: str, default=None):
        """Get attribute from object or dict."""
        if isinstance(obj, dict):
            return obj.get(attr, default)
        return getattr(obj, attr, default)


def view_trace(trace_export, mode: str = "tree"):
    """Quick one-liner to view a trace export."""
    viewer = TraceViewer(trace_export)
    viewer.print(mode)
