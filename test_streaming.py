"""M2.1 单元测试：步骤事件流实时回调。

验证 TraceContext 与 trace_run 的 on_step_end/on_step 回调机制，
每步结束时立即收到步骤数据。运行：pytest test_streaming.py -v
"""

from agent_obs.trace_core import TraceContext, trace_root, trace_span, SEM
from agent_obs.run import trace_run


def test_trace_context_on_step_end_fired():
    """TraceContext 每步结束时应触发 on_step_end 回调。"""
    collected = []

    def cb(step):
        collected.append(step["id"])

    ctx = TraceContext("test", on_step_end=cb)
    sid1 = ctx.start_span("A", SEM.TOOL, inputs={"x": 1})
    ctx.end_span(sid1, outputs={"result": 1})
    sid2 = ctx.start_span("B", SEM.TOOL, inputs={"x": 2})
    ctx.end_span(sid2, outputs={"result": 2})

    assert collected == [sid1, sid2]


def test_trace_root_proxies_on_step_end():
    """trace_root 应透传 on_step_end 到 TraceContext。"""
    collected = []

    with trace_root("root_test", on_step_end=lambda s: collected.append(s.get("semantic_name") or s.get("name") or s.get("type"))) as ctx:
        sid = ctx.start_span("inner_step", SEM.TOOL)
        ctx.end_span(sid)

    # 验证回调被触发
    assert len(collected) > 0


def test_trace_run_on_step_callback():
    """trace_run 的 on_step 参数应透传到底层。"""
    collected = []

    with trace_run("stream_test", patch=False, on_step=lambda s: collected.append(s.get("semantic_name") or s.get("name", ""))):
        with trace_span("step1", SEM.TOOL) as sp:
            sp["outputs"] = {"r": 1}

    assert any("step1" in name for name in collected)


def test_callback_receives_step_details():
    """回调应收到完整的步骤字段（id/semantic_name/status/latency_ms 等）。"""
    received = []

    def cb(step):
        received.append(step)

    ctx = TraceContext("detail_test", on_step_end=cb)
    sid = ctx.start_span("work", SEM.LLM, inputs={"p": "hi"})
    ctx.end_span(sid, outputs={"o": "ok"})

    assert len(received) == 1
    s = received[0]
    assert s["id"] == sid
    # chain 步用 semantic_name
    assert "work" in s.get("semantic_name", "")
    assert s["type"] == "llm"
    assert s["status"] == "success"
    assert "latency_ms" in s
    assert isinstance(s["latency_ms"], (int, float))


def test_callback_with_error_step():
    """失败步骤同样触发回调，status=error。"""
    received = []

    ctx = TraceContext("err_test", on_step_end=lambda s: received.append(s))
    sid = ctx.start_span("boom", SEM.TOOL)
    ctx.end_span(sid, status="error", error="kaboom")

    assert received[0]["status"] == "error"
    assert received[0]["error"] == "kaboom"
