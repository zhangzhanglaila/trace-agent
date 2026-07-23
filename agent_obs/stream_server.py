"""
实时监控 SSE 推送服务器（M2.2）

提供一个最小可行的 HTTP/SSE 服务器：Agent 运行时每步通过 `trace_run.on_step`
推送到 /stream 端点，前端用 EventSource 订阅并实时展示进度条。

独立运行：python -m agent_obs.stream_server

默认端口 8766（不与现有 DevTools 8765 冲突）。
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread, Event
from queue import Queue
import json
import time

_STREAM_QUEUE: Queue = Queue()
_STREAM_EVENT = Event()


class StreamHandler(BaseHTTPRequestHandler):
    """SSE 端点：前端 EventSource 订阅 /stream 接收步骤事件。"""

    def do_GET(self):
        if self.path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            # 发送客户端初始连接确认
            self.wfile.write(b"data: connected\n\n")
            self.wfile.flush()

            # 持续推送队列中的事件
            try:
                while True:
                    _STREAM_EVENT.wait(timeout=1)  # 等待新事件
                    _STREAM_EVENT.clear()
                    while not _STREAM_QUEUE.empty():
                        event = _STREAM_QUEUE.get_nowait()
                        self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                # 客户端断开
                pass

    def log_message(self, format, *args):
        pass  # 静默日志


def push_step_event(step: dict):
    """推送步骤事件到所有订阅的客户端。

    由 trace_run.on_step 回调调用。
    """
    _STREAM_QUEUE.put(step)
    _STREAM_EVENT.set()


def start_server(port: int = 8766, background: bool = False):
    """启动 SSE 推送服务器。

    Args:
        port: 默认 8766（避开 8765 DevTools）。
        background: 是否后台运行（默认阻塞）。
    """
    server = HTTPServer(("127.0.0.1", port), StreamHandler)
    if background:
        t = Thread(target=server.serve_forever, daemon=True)
        t.start()
        time.sleep(0.2)  # 等待绑定
        return server
    else:
        print(f"SSE 推送服务器启动: http://127.0.0.1:{port}/stream")
        server.serve_forever()


if __name__ == "__main__":
    start_server()
