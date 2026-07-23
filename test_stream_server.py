"""M2.2 单元测试：SSE 推送服务器（agent_obs/stream_server.py）。

验证 push_step_event 能把事件放入队列、start_server 可后台启动。
运行：pytest test_stream_server.py -v
"""

import time
from agent_obs.stream_server import push_step_event, start_server, _STREAM_QUEUE


def test_push_step_event_enqueues():
    """push_step_event 应把事件放入队列。"""
    while not _STREAM_QUEUE.empty():
        _STREAM_QUEUE.get_nowait()
    initial = 0
    push_step_event({"id": "test_1", "name": "stepA"})
    assert _STREAM_QUEUE.qsize() == initial + 1


def test_multiple_pushes_are_queued():
    """多次推送应依次入队。"""
    while not _STREAM_QUEUE.empty():
        _STREAM_QUEUE.get_nowait()
    push_step_event({"id": "a"})
    push_step_event({"id": "b"})
    push_step_event({"id": "c"})
    assert _STREAM_QUEUE.qsize() == 3


def test_start_server_background():
    """start_server(background=True) 应不阻塞并返回。"""
    server = start_server(port=8767, background=True)
    assert server is not None
    # 简单验证端口绑定成功（不能再次绑定同一端口）
    import socket
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 8767))
        assert False, "端口应已被占用"
    except OSError:
        pass  # 预期：端口被占用
    finally:
        s.close()


def test_event_has_required_fields():
    """推送的事件应包含前端渲染所需字段。"""
    while not _STREAM_QUEUE.empty():
        _STREAM_QUEUE.get_nowait()
    step = {
        "id": "llm_1",
        "semantic_type": "LLM",
        "semantic_name": "[LLM] model",
        "latency_ms": 123.4,
        "status": "success",
    }
    push_step_event(step)
    out = _STREAM_QUEUE.get_nowait()
    assert out["id"] == "llm_1"
    assert out["semantic_type"] == "LLM"
    assert "latency_ms" in out
