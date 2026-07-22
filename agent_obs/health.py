"""
单次运行健康分析器 —— HealthAnalyzer（M1.2）

吃一份 SingleRunReport（见 agent_obs/single_run.py / docs/02-技术架构.md），
自动定位三类问题并生成一句人话摘要，回填 report["health"] 并按需升级顶层 status：

- 失败步骤 failed_step_id：第一个 status==error 的步骤 → 顶层 "failed"
- 卡点     stuck_step_id ：最后一个 status==running 的步骤（span 起了没结束）；
           或调用方明确告知运行中断(completed=False)时取最后一步 → 顶层 "stuck"
- 慢步骤   slow_step_ids ：相对中位数的耗时离群点，阈值可配

设计约束（docs/03-设计规范.md）：纯逻辑、无 IO、规则集中一处、可单测。

卡点判定的背景（见开发日志 2026-07-22）：hang 的 span 会以默认 status=success
落库，因此「卡住」只能靠两个信号推断——① 某步 status=running（起了未结束）；
② 调用方捕获到运行异常中断（completed=False）。二者都没有时不臆断卡点。
"""

import statistics
from typing import Any, Dict, List, Optional


class HealthConfig:
    """健康判定阈值，集中一处便于调整。"""

    def __init__(self, slow_factor: float = 3.0, min_slow_ms: float = 100.0):
        # 慢步骤：duration >= max(min_slow_ms, median * slow_factor) 且严格大于中位数
        self.slow_factor = slow_factor
        self.min_slow_ms = min_slow_ms


def _find_failed_step(steps: List[Dict]) -> Optional[str]:
    for s in steps:
        if s.get("status") == "error":
            return s.get("id")
    return None


def _find_stuck_step(steps: List[Dict], completed: Optional[bool]) -> Optional[str]:
    """卡点：优先取最后一个 running 步骤；否则在明确中断时取最后一步。"""
    running = [s.get("id") for s in steps if s.get("status") == "running"]
    if running:
        return running[-1]
    if completed is False and steps:
        # 运行被异常中断，且没有 running 信号 → 最后执行到的步骤即卡点
        return steps[-1].get("id")
    return None


def _find_slow_steps(steps: List[Dict], config: HealthConfig) -> List[str]:
    """耗时离群点：相对中位数放大，避免把普遍偏慢误报为异常。"""
    durations = [
        (s.get("id"), float(s["duration_ms"]))
        for s in steps
        if isinstance(s.get("duration_ms"), (int, float))
    ]
    if len(durations) < 2:
        return []
    median = statistics.median(d for _, d in durations)
    threshold = max(config.min_slow_ms, median * config.slow_factor)
    return [sid for sid, d in durations if d >= threshold and d > median]


def _step_name(steps: List[Dict], step_id: Optional[str]) -> str:
    for s in steps:
        if s.get("id") == step_id:
            return s.get("name") or step_id or "?"
    return step_id or "?"


def _step_field(steps: List[Dict], step_id: Optional[str], field: str) -> Any:
    for s in steps:
        if s.get("id") == step_id:
            return s.get(field)
    return None


def _build_summary(
    steps: List[Dict],
    failed_id: Optional[str],
    stuck_id: Optional[str],
    slow_ids: List[str],
) -> str:
    """按严重度 failed > stuck > slow > healthy 生成一句人话。"""
    if failed_id:
        name = _step_name(steps, failed_id)
        err = _step_field(steps, failed_id, "error") or "未知错误"
        return f"运行失败：在「{name}」这一步出错 —— {err}"
    if stuck_id:
        name = _step_name(steps, stuck_id)
        status = _step_field(steps, stuck_id, "status")
        if status == "running":
            return f"运行疑似卡住：卡在「{name}」这一步（已开始但未结束）"
        return f"运行未正常结束：最后执行到「{name}」这一步"
    if slow_ids:
        name = _step_name(steps, slow_ids[0])
        dur = _step_field(steps, slow_ids[0], "duration_ms")
        extra = f"，共 {len(slow_ids)} 个慢步骤" if len(slow_ids) > 1 else ""
        return f"运行完成，但「{name}」这一步耗时偏高（{dur}ms）{extra}"
    return "运行正常完成，未发现异常步骤。"


def analyze_health(
    report: Dict,
    *,
    completed: Optional[bool] = None,
    config: Optional[HealthConfig] = None,
) -> Dict:
    """分析一份 SingleRunReport，回填 health 段并升级顶层 status。

    Args:
        report: build_single_run_report() 的产物。
        completed: 运行是否正常结束。None=未知（不据此判卡点）；
                   False=调用方捕获到异常中断（据此把最后一步判为卡点）。
        config: 阈值配置，缺省用默认 HealthConfig。

    Returns:
        同一个 report（原地修改），便于链式使用。
    """
    config = config or HealthConfig()
    steps = report.get("steps", [])

    failed_id = _find_failed_step(steps)
    stuck_id = None if failed_id else _find_stuck_step(steps, completed)
    slow_ids = _find_slow_steps(steps, config)

    report["health"] = {
        "failed_step_id": failed_id,
        "stuck_step_id": stuck_id,
        "slow_step_ids": slow_ids,
        "summary": _build_summary(steps, failed_id, stuck_id, slow_ids),
    }

    # 升级顶层 status：failed > stuck > 原状态
    if failed_id:
        report["status"] = "failed"
    elif stuck_id:
        report["status"] = "stuck"

    return report
