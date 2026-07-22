"""
单次运行透明化 —— SingleRunReport 构建器（M1.1）

目标：别人的 Agent 只跑一次，就能拿到一份归一化的「步骤时间线」，
看清每一步的输入/输出/耗时/状态，为定位「卡在哪一步」打底。

设计约束（见 docs/03-设计规范.md）：
- 纯逻辑，无 IO、不依赖前端与 diff 引擎。
- 复用现有 TraceCapture.steps 的真实字段，不改录制内核。
- health 段在本步（M1.1）仅占位，由 M1.2 的 HealthAnalyzer 填充。

协议契约见 docs/02-技术架构.md「单次运行报告协议」。
"""

from typing import Any, Dict, List, Optional

# step.type → 报告中的 kind
_KIND_MAP = {
    "llm": "llm",
    "tool": "tool",
    "branch": "branch",
    "chain": "function",
    "output": "output",
    "merge": "merge",
}


def _extract_steps(source: Any) -> List[Dict]:
    """从多种来源鸭子类型地取出原始 step 列表。

    支持：
    - list[dict]                     —— 直接是 steps
    - dict{"steps": [...]}           —— TraceCapture.get_trace() 的产物
    - 具有 .steps 的对象             —— TraceCapture
    - 具有 .capture.steps 的对象     —— TraceContext
    """
    if source is None:
        return []
    if isinstance(source, list):
        return source
    if isinstance(source, dict):
        return list(source.get("steps", []))
    # TraceContext.capture.steps
    capture = getattr(source, "capture", None)
    if capture is not None and hasattr(capture, "steps"):
        return list(capture.steps)
    # TraceCapture.steps
    if hasattr(source, "steps"):
        return list(source.steps)
    return []


def _derive_name(step: Dict) -> str:
    """人可读的步骤名：语义名 > 名称 > 输出变量名 > 类型。"""
    for key in ("semantic_name", "name", "var", "condition"):
        val = step.get(key)
        if val:
            return str(val)
    return str(step.get("type", "step"))


def _derive_input(step: Dict) -> Dict:
    """按类型抽取输入。"""
    t = step.get("type")
    if t == "llm":
        return {"prompt": step.get("prompt", "")}
    if t == "tool":
        return dict(step.get("args") or {})
    if t == "branch":
        out = {}
        if "condition" in step:
            out["condition"] = step.get("condition")
        if step.get("consumes"):
            out["consumes"] = step["consumes"]
        return out
    # chain / 其他
    return dict(step.get("inputs") or {})


def _derive_output(step: Dict) -> Dict:
    """按类型抽取输出。"""
    t = step.get("type")
    if t == "llm":
        return {"output": step.get("output", "")}
    if t == "tool":
        return {"result": step.get("result")}
    if t == "branch":
        return {"value": step.get("value")}
    if t == "output":
        return {"value": step.get("value")}
    return dict(step.get("outputs") or {})


def _derive_status(step: Dict) -> str:
    """归一化状态：error / running(疑似卡住) / ok。

    running 判定（保守）：llm/tool 起了但产物仍为 None 且无 error —— span 起了没结束，
    是「卡住」的信号，最终定性交给 M1.2 的 HealthAnalyzer。
    """
    if step.get("error"):
        return "error"
    raw = step.get("status")
    if raw in ("error", "failed"):
        return "error"
    t = step.get("type")
    if t == "llm" and step.get("output") in (None, ""):
        return "running"
    if t == "tool" and step.get("result") is None and "result" in step:
        return "running"
    return "ok"


def _normalize_step(step: Dict) -> Dict:
    """把一条原始 step 归一化为协议中的 step。"""
    latency = step.get("latency_ms")
    return {
        "id": step.get("id"),
        "name": _derive_name(step),
        "kind": _KIND_MAP.get(step.get("type"), "function"),
        "status": _derive_status(step),
        "input": _derive_input(step),
        "output": _derive_output(step),
        "duration_ms": round(float(latency), 3) if isinstance(latency, (int, float)) else None,
        "error": step.get("error"),
        "started_at": step.get("start_time"),
    }


def _compute_duration_ms(raw_steps: List[Dict]) -> Optional[float]:
    """整段耗时：末步 end - 首步 start；无时间戳则退化为各步 latency 之和。"""
    starts = [s["start_time"] for s in raw_steps if isinstance(s.get("start_time"), (int, float))]
    ends = [s["end_time"] for s in raw_steps if isinstance(s.get("end_time"), (int, float))]
    if starts and ends:
        return round((max(ends) - min(starts)) * 1000, 3)
    latencies = [s["latency_ms"] for s in raw_steps if isinstance(s.get("latency_ms"), (int, float))]
    if latencies:
        return round(float(sum(latencies)), 3)
    return None


def build_single_run_report(
    source: Any,
    *,
    run_id: Optional[str] = None,
    run_name: str = "agent_run",
) -> Dict:
    """从一次运行的 trace 构建 SingleRunReport。

    Args:
        source: 原始 step 列表 / {"steps": [...]} / TraceCapture / TraceContext。
        run_id: 运行标识；缺省时留空由调用方补。
        run_name: 运行名称，用于展示。

    Returns:
        符合 docs/02-技术架构.md「单次运行报告协议 v1」的 dict。
        health 段为占位，由 M1.2 的 HealthAnalyzer 填充。
    """
    raw_steps = _extract_steps(source)
    steps = [_normalize_step(s) for s in raw_steps]

    started_at: Optional[float] = None
    for s in raw_steps:
        if isinstance(s.get("start_time"), (int, float)):
            started_at = s["start_time"]
            break

    has_error = any(s["status"] == "error" for s in steps)
    top_status = "failed" if has_error else ("success" if steps else "unknown")

    return {
        "run_id": run_id,
        "run_name": run_name,
        "status": top_status,
        "started_at": started_at,
        "duration_ms": _compute_duration_ms(raw_steps),
        "step_count": len(steps),
        "steps": steps,
        # M1.1 占位；M1.2 由 HealthAnalyzer 填充
        "health": {
            "failed_step_id": None,
            "stuck_step_id": None,
            "slow_step_ids": [],
            "summary": "",
        },
    }
