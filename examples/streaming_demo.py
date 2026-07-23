"""
M2.2 端到端演示：实时监控全链路。

演示：后端每步回调 → SSE 推送 → 前端实时进度条。

运行：
    python examples/streaming_demo.py

然后浏览器打开 examples/streaming_demo.html 查看实时进度条。
"""

import sys
import time
from pathlib import Path

# 添加项目根目录到 Python 路径，以便导入 agenttrace
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent_obs.stream_server import start_server, push_step_event
from agent_obs.trace_core import trace_span, SEM


def demo_agent():
    """一个模拟 Agent，每步耗时不同以展示进度条。"""
    print(">> 开始运行 Agent（每步会实时推送到前端）...")

    with trace_span("classify", SEM.LLM, inputs={"query": "东京天气"}) as sp:
        time.sleep(0.8)  # 模拟 LLM 调用
        sp["outputs"] = {"result": "weather"}

    with trace_span("search", SEM.TOOL, inputs={"city": "东京"}) as sp:
        time.sleep(0.3)
        sp["outputs"] = {"result": "晴 25°C"}

    with trace_span("respond", SEM.LLM, inputs={"weather": "晴 25°C"}) as sp:
        time.sleep(0.6)
        sp["outputs"] = {"result": "东京今天天气晴朗，25°C，适合出行。"}

    print(">> Agent 运行完成")


if __name__ == "__main__":
    # 1. 启动 SSE 推送服务器（后台）
    print(">> 启动 SSE 推送服务器 http://127.0.0.1:8766/stream")
    start_server(port=8766, background=True)

    print("\n请用浏览器打开 examples/streaming_demo.html 查看实时进度条")
    print("按 Enter 开始运行 Agent...")
    input()

    # 2. 运行 Agent，每步通过 on_step 推送
    from agent_obs.run import trace_run

    with trace_run("streaming_demo", on_step=push_step_event, patch=False):
        demo_agent()

    print("\n>> 演示结束。SSE 服务器继续运行，Ctrl+C 退出。")
    print(">> 刷新浏览器页面可重复查看效果。")

    # 保持服务器运行
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nSSE 服务器已关闭")
