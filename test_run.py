"""M1.5 单元测试：一行接入 trace_run / observe（agent_obs/run.py）。

覆盖：成功运行出报告、失败运行仍出报告并定位、装饰器两种写法、HTML 落盘、
公开 API 可从 agenttrace 导入。运行：pytest test_run.py -v
"""

import pytest

from agent_obs.run import trace_run, observe
from agent_obs.trace_core import trace_span, SEM


def test_trace_run_success_builds_report():
    with trace_run("t_ok", patch=False) as run:
        with trace_span("stepA", SEM.TOOL, inputs={"x": 1}) as sp:
            sp["outputs"] = {"result": "ok"}
    assert run.report is not None
    assert run.status == "success"
    assert any("stepA" in (s["name"] or "") for s in run.report["steps"])
    assert "正常完成" in run.summary


def test_trace_run_failure_still_reports_and_locates():
    with pytest.raises(RuntimeError):
        with trace_run("t_fail", patch=False) as run:
            with trace_span("boom", SEM.TOOL):
                raise RuntimeError("kaboom")
    # 即使抛异常，报告依然生成并定位失败
    assert run.report is not None
    assert run.status == "failed"
    assert run.report["health"]["failed_step_id"] is not None
    assert "kaboom" in run.summary


def test_observe_decorator_plain():
    @observe
    def agent(x):
        with trace_span("work", SEM.TOOL) as sp:
            sp["outputs"] = {"result": x * 2}
        return x * 2

    out = agent(21)
    assert out == 42
    assert agent.last_report is not None
    assert agent.last_report["status"] == "success"


def test_observe_decorator_with_args_and_name():
    @observe(name="myagent")
    def agent():
        with trace_span("s", SEM.TOOL) as sp:
            sp["outputs"] = {"result": "done"}
        return "done"

    agent()
    assert agent.last_report["run_name"] == "myagent"


def test_observe_captures_report_on_failure():
    @observe
    def agent():
        raise ValueError("nope")

    with pytest.raises(ValueError):
        agent()
    assert agent.last_report is not None
    assert agent.last_report["status"] in ("failed", "stuck")


def test_trace_run_writes_html(tmp_path):
    out = tmp_path / "run.html"
    with trace_run("t_html", html_path=str(out), patch=False) as run:
        with trace_span("s", SEM.TOOL) as sp:
            sp["outputs"] = {"result": "ok"}
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert content.startswith("<!DOCTYPE html>")
    assert "t_html" in content


def test_public_api_importable():
    import agenttrace
    for name in ("enable", "dev", "trace_run", "observe", "RunHandle", "step"):
        assert hasattr(agenttrace, name), f"agenttrace.{name} missing"
