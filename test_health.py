"""M1.2 单元测试：HealthAnalyzer（agent_obs/health.py）。

覆盖四类：健康 / 失败步骤 / 卡点(running & 中断) / 慢步骤，以及严重度优先级。
运行：pytest test_health.py -v
"""

from agent_obs.single_run import build_single_run_report
from agent_obs.health import analyze_health, HealthConfig


def _step(sid, kind="tool", status="ok", duration=10.0, error=None, name=None):
    return {
        "id": sid, "name": name or sid, "kind": kind, "status": status,
        "input": {}, "output": {}, "duration_ms": duration, "error": error,
        "started_at": 100.0,
    }


def _report(steps, status="success"):
    return {
        "run_id": "r", "run_name": "t", "status": status, "started_at": 100.0,
        "duration_ms": sum(s["duration_ms"] for s in steps), "step_count": len(steps),
        "steps": steps, "health": {},
    }


# ── 健康 ──

def test_healthy_run():
    r = _report([_step("a"), _step("b"), _step("c")])
    analyze_health(r)
    assert r["status"] == "success"
    h = r["health"]
    assert h["failed_step_id"] is None
    assert h["stuck_step_id"] is None
    assert h["slow_step_ids"] == []
    assert "正常完成" in h["summary"]


# ── 失败步骤 ──

def test_failed_step():
    steps = [_step("a"), _step("db", status="error", error="ConnectionError: timeout", name="db_query")]
    r = _report(steps)
    analyze_health(r)
    assert r["status"] == "failed"
    assert r["health"]["failed_step_id"] == "db"
    assert "db_query" in r["health"]["summary"]
    assert "ConnectionError" in r["health"]["summary"]


# ── 卡点：running ──

def test_stuck_by_running_step():
    steps = [_step("a"), _step("llm1", kind="llm", status="running", name="call_model")]
    r = _report(steps)
    analyze_health(r)
    assert r["status"] == "stuck"
    assert r["health"]["stuck_step_id"] == "llm1"
    assert "卡" in r["health"]["summary"]


# ── 卡点：调用方告知中断 ──

def test_stuck_by_aborted_completed_false():
    steps = [_step("a"), _step("b", name="last_step")]
    r = _report(steps)
    analyze_health(r, completed=False)
    assert r["status"] == "stuck"
    assert r["health"]["stuck_step_id"] == "b"
    assert "最后执行到" in r["health"]["summary"]


def test_not_stuck_when_completed_none():
    steps = [_step("a"), _step("b")]
    r = _report(steps)
    analyze_health(r, completed=None)
    assert r["status"] == "success"
    assert r["health"]["stuck_step_id"] is None


# ── 慢步骤 ──

def test_slow_step_outlier():
    steps = [_step("a", duration=10.0), _step("b", duration=12.0),
             _step("slow", duration=500.0, name="heavy_tool"), _step("c", duration=11.0)]
    r = _report(steps)
    analyze_health(r)
    assert "slow" in r["health"]["slow_step_ids"]
    assert r["status"] == "success"  # 慢不改顶层状态
    assert "耗时偏高" in r["health"]["summary"]


def test_slow_ignores_uniformly_small_durations():
    # 所有步骤都很小，不应误报
    steps = [_step("a", duration=5.0), _step("b", duration=6.0), _step("c", duration=7.0)]
    r = _report(steps)
    analyze_health(r)
    assert r["health"]["slow_step_ids"] == []


def test_slow_factor_configurable():
    steps = [_step("a", duration=100.0), _step("b", duration=100.0), _step("big", duration=250.0)]
    r = _report(steps)
    # 默认 factor=3：阈值=max(100, 100*3)=300，250 不算慢
    analyze_health(r)
    assert r["health"]["slow_step_ids"] == []
    # 放宽 factor=2、降低下限：阈值=max(50,200)=200，250 算慢
    r2 = _report(steps)
    analyze_health(r2, config=HealthConfig(slow_factor=2.0, min_slow_ms=50.0))
    assert "big" in r2["health"]["slow_step_ids"]


# ── 严重度优先级：failed 压过 stuck/slow ──

def test_severity_priority_failed_over_stuck():
    steps = [_step("run", status="running", name="hang"),
             _step("err", status="error", error="boom", name="crash")]
    r = _report(steps)
    analyze_health(r)
    assert r["status"] == "failed"
    assert r["health"]["failed_step_id"] == "err"
    # 有失败步骤时不再另标卡点
    assert r["health"]["stuck_step_id"] is None


# ── 端到端：真实构建器 → 分析器 ──

def test_end_to_end_with_builder():
    raw = [
        {"type": "llm", "id": "llm_1", "prompt": "hi", "output": "ok",
         "latency_ms": 10.0, "start_time": 100.0, "end_time": 100.01, "status": "success"},
        {"type": "tool", "id": "tool_2", "name": "api", "args": {}, "result": None,
         "latency_ms": 5.0, "start_time": 100.02, "end_time": 100.02,
         "status": "error", "error": "HTTP 500"},
    ]
    report = build_single_run_report(raw, run_id="e2e")
    analyze_health(report)
    assert report["status"] == "failed"
    assert report["health"]["failed_step_id"] == "tool_2"
    assert "HTTP 500" in report["health"]["summary"]
