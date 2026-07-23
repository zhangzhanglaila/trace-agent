"""
单次运行透明化 —— 一行接入（M1.5）

把「跑一次 → 建报告 → 分析健康 → 出 HTML」这套包成两条通道：

1) 上下文管理器（推荐，包住一次运行即可）：
       from agenttrace import trace_run
       with trace_run("my_agent", html_path="run.html") as run:
           agent.invoke("...")          # 你的 Agent 代码零改动
       print(run.status, run.summary)   # 自动拿到报告

2) 装饰器（装饰 Agent 入口函数）：
       from agenttrace import observe
       @observe(html_path="run.html")
       def my_agent(query): ...
       my_agent("...")
       my_agent.last_report             # 最近一次运行的报告

即使运行中途抛异常，报告依然会生成（并写入 HTML），高亮出错/卡住的那一步——
这正是「不知道卡在哪一步」的答案。异常仍会照常向上抛出，不改变你的错误处理。

步骤级精确边界见 `step`（= instrument.auto.trace_step）：给关键函数加 @step 换取
更准确的步骤命名与输入输出。
"""

import time
import threading
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Dict, Optional

from .trace_core import trace_root
from .instrument.auto import auto_trace
from .single_run import build_single_run_report
from .health import analyze_health, HealthConfig
from .single_run_view import write_html


class _TimeoutWatcher:
    """M2.3 卡住告警：后台线程监控超时未触发新步。"""

    def __init__(self, timeout: float, on_alert: Callable[[float], None]):
        self.timeout = timeout
        self.on_alert = on_alert
        self.last_step_time: Optional[float] = None
        self._start_time: Optional[float] = None  # 记录 watcher 启动时间
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def touch(self):
        """记录有新步发生（重置计时）。"""
        self.last_step_time = time.time()

    def start(self):
        """启动后台监控线程。"""
        self._start_time = time.time()  # 记录启动时刻
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()

    def _watch(self):
        """后台线程：每秒检查一次是否超时。"""
        while not self._stop.is_set():
            current = time.time()
            # 优先用 last_step_time（最后一步时刻），否则用 start_time
            reference = self.last_step_time or self._start_time
            if reference:
                elapsed = current - reference
                if elapsed > self.timeout:
                    self.on_alert(elapsed)
                    self.last_step_time = None  # 防止重复告警
            self._stop.wait(1)  # 每秒检查一次

    def stop(self):
        """停止监控线程。"""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)


class RunHandle:
    """一次运行的句柄；退出后 `report` 被填充。"""

    def __init__(self, name: str):
        self.name = name
        self.report: Optional[Dict] = None

    @property
    def status(self) -> Optional[str]:
        return self.report["status"] if self.report else None

    @property
    def summary(self) -> Optional[str]:
        return self.report["health"]["summary"] if self.report else None


@contextmanager
def trace_run(
    name: str = "agent_run",
    *,
    html_path: Optional[str] = None,
    config: Optional[HealthConfig] = None,
    patch: bool = True,
    on_step: Optional[Callable] = None,
    stuck_timeout: float = 30.0,
):
    """包住一次运行，退出时自动产出 SingleRunReport（并可写 HTML）。

    Args:
        name: 运行名称（展示用）。
        html_path: 若给定，退出时把报告渲染成自包含 HTML 写到此路径。
        config: 健康分析阈值（慢步骤等），缺省用默认。
        patch: 是否自动 patch LangChain/OpenAI（默认开，保证 LLM 步被捕获）。
        on_step: 每步结束时回调（M2.1 实时监控），收到原始步骤 dict。
        stuck_timeout: 卡住告警阈值（秒），超时未触发新步则推送告警（M2.3）。

    Yields:
        RunHandle —— 退出 with 块后 `.report`/`.status`/`.summary` 可用。
    """
    if patch:
        auto_trace()  # 幂等
    handle = RunHandle(name)
    holder: Dict[str, Any] = {"ctx": None, "completed": True, "last_step_id": None}

    # M2.3 卡住告警 watcher
    def on_alert(elapsed):
        # 获取最后执行的步骤 ID 用于告警
        last_id = holder.get("last_step_id")
        from .stream_server import push_alert_event
        msg = f"运行疑似卡住：已 {elapsed:.0f} 秒未触发新步骤"
        push_alert_event("stuck", msg, step_id=last_id)

    watcher = _TimeoutWatcher(stuck_timeout, on_alert) if stuck_timeout > 0 else None

    def wrapped_on_step(step):
        # 更新最后步骤 ID
        holder["last_step_id"] = step.get("id")
        if watcher:
            watcher.touch()
        if on_step:
            on_step(step)

    try:
        if watcher:
            watcher.start()
        with trace_root(name, auto_export=False, on_step_end=wrapped_on_step) as ctx:
            holder["ctx"] = ctx
            if watcher:
                watcher.touch()  # 开始运行时也要 touch 一下
            yield handle
    except BaseException:
        holder["completed"] = False
        raise
    finally:
        if watcher:
            watcher.stop()
        ctx = holder["ctx"]
        if ctx is not None:
            report = build_single_run_report(ctx, run_name=name)
            analyze_health(report, completed=holder["completed"], config=config)
            handle.report = report
            if html_path:
                write_html(report, html_path)


def observe(
    func: Optional[Callable] = None,
    *,
    name: Optional[str] = None,
    html_path: Optional[str] = None,
    config: Optional[HealthConfig] = None,
):
    """装饰 Agent 入口函数，调用即自动产出单次运行报告。

    支持 `@observe` 与 `@observe(name=..., html_path=...)` 两种写法。
    被装饰函数会附带 `.last_report`（最近一次运行的报告，失败时同样填充）。
    """

    def deco(f: Callable) -> Callable:
        @wraps(f)
        def wrapper(*args, **kwargs):
            run_name = name or getattr(f, "__name__", "agent_run")
            ref: Dict[str, RunHandle] = {}
            try:
                with trace_run(run_name, html_path=html_path, config=config) as run:
                    ref["handle"] = run
                    return f(*args, **kwargs)
            finally:
                h = ref.get("handle")
                wrapper.last_report = h.report if h else None

        wrapper.last_report = None
        return wrapper

    return deco(func) if callable(func) else deco
