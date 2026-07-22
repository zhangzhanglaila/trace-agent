"""M1.1 单元测试：SingleRunReport 构建器（agent_obs/single_run.py）。

覆盖：正常时间线抽取、失败步骤、疑似卡住(running)、耗时/顺序、来源鸭子类型。
运行：pytest test_single_run.py -v
"""

from agent_obs.single_run import build_single_run_report
from agent_obs.trace_core import TraceContext


# ── 构造原始 steps 的小工具 ──

def _llm(step_id, prompt, output, latency=10.0, start=100.0, error=None):
    return {
        "type": "llm", "id": step_id, "prompt": prompt, "output": output,
        "start_time": start, "end_time": start + latency / 1000,
        "latency_ms": latency, "status": "success", "error": error,
    }


def _tool(step_id, name, args, result, latency=20.0, start=101.0, error=None):
    return {
        "type": "tool", "id": step_id, "name": name, "args": args, "result": result,
        "start_time": start, "end_time": start + latency / 1000,
        "latency_ms": latency, "status": "success" if not error else "error",
        "error": error,
    }


# ── 测试 ──

def test_empty_source():
    r = build_single_run_report([])
    assert r["status"] == "unknown"
    assert r["step_count"] == 0
    assert r["steps"] == []
    assert r["health"]["summary"] == ""


def test_timeline_extraction_and_order():
    steps = [
        _llm("llm_1", "hi", "hello", latency=10.0, start=100.0),
        _tool("tool_2", "weather_api", {"city": "Tokyo"}, "clear", latency=25.0, start=100.01),
    ]
    r = build_single_run_report(steps, run_id="run-1", run_name="demo")
    assert r["run_id"] == "run-1"
    assert r["run_name"] == "demo"
    assert r["status"] == "success"
    assert r["step_count"] == 2
    # 顺序保持
    assert [s["id"] for s in r["steps"]] == ["llm_1", "tool_2"]
    # kind 映射
    assert r["steps"][0]["kind"] == "llm"
    assert r["steps"][1]["kind"] == "tool"
    # 输入/输出抽取
    assert r["steps"][0]["input"] == {"prompt": "hi"}
    assert r["steps"][0]["output"] == {"output": "hello"}
    assert r["steps"][1]["input"] == {"city": "Tokyo"}
    assert r["steps"][1]["output"] == {"result": "clear"}
    # 耗时
    assert r["steps"][0]["duration_ms"] == 10.0


def test_failed_step_marks_report_failed():
    steps = [
        _llm("llm_1", "hi", "hello"),
        _tool("tool_2", "db_query", {"q": "x"}, None, error="ConnectionError: timeout"),
    ]
    r = build_single_run_report(steps)
    assert r["status"] == "failed"
    failed = [s for s in r["steps"] if s["status"] == "error"]
    assert len(failed) == 1
    assert failed[0]["id"] == "tool_2"
    assert "ConnectionError" in failed[0]["error"]


def test_running_step_detected_when_llm_has_no_output():
    # span 起了没结束：output 仍为 None、无 error → running（疑似卡住）
    steps = [_llm("llm_1", "hi", None, error=None)]
    steps[0]["output"] = None
    r = build_single_run_report(steps)
    assert r["steps"][0]["status"] == "running"
    # 无 error → 顶层不算 failed
    assert r["status"] == "success"


def test_duration_from_timestamps():
    steps = [
        _llm("llm_1", "hi", "hello", latency=10.0, start=100.0),
        _tool("tool_2", "t", {}, "r", latency=30.0, start=100.05),
    ]
    r = build_single_run_report(steps)
    # (100.05 + 0.030 - 100.0) * 1000 = 80.0
    assert r["duration_ms"] == 80.0
    assert r["started_at"] == 100.0


def test_duration_falls_back_to_latency_sum():
    steps = [
        {"type": "chain", "id": "c1", "name": "a", "latency_ms": 5.0},
        {"type": "chain", "id": "c2", "name": "b", "latency_ms": 7.0},
    ]
    r = build_single_run_report(steps)
    assert r["duration_ms"] == 12.0
    assert r["started_at"] is None


def test_accepts_trace_context_source():
    """端到端：真实 TraceContext → 报告。"""
    ctx = TraceContext(run_name="ctx_run")
    sid = ctx.start_span("classify", inputs={"prompt": "hello"})
    ctx.end_span(sid, outputs={"result": "greeting"})
    r = build_single_run_report(ctx, run_name="ctx_run")
    assert r["step_count"] >= 1
    assert r["run_name"] == "ctx_run"
    names = [s["name"] for s in r["steps"]]
    assert any("classify" in n for n in names)
