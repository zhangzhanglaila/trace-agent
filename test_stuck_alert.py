"""M2.3 单元测试：卡住/超时实时告警（agent_obs/run.py _TimeoutWatcher）。

验证超时未触发新步时推送告警事件。运行：pytest test_stuck_alert.py -v
"""

import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from agent_obs.run import _TimeoutWatcher
from agent_obs.stream_server import push_alert_event, _STREAM_QUEUE


def test_watcher_touch_resets_timer():
    """touch 应重置计时，避免超时。"""
    alerts = []
    watcher = _TimeoutWatcher(timeout=0.5, on_alert=lambda e: alerts.append(e))

    watcher.start()
    time.sleep(0.15)
    watcher.touch()
    time.sleep(0.7)  # 小于 1s 检查周期，但大于 0.5s 阈值
    watcher.touch()  # 在后台线程检查前再次 touch
    time.sleep(0.7)
    watcher.stop()

    # 因为检查间隔是 1s，而我们在 0.7s 就 touch 了，所以不会超时
    assert len(alerts) == 0, f"预期无告警（touch 重置了计时），实际收到 {len(alerts)} 次"


def test_watcher_fires_after_timeout():
    """超时应触发告警。"""
    alerts = []
    watcher = _TimeoutWatcher(timeout=0.5, on_alert=lambda e: alerts.append(e))

    watcher.start()
    time.sleep(0.15)  # 等线程启动
    watcher.touch()
    time.sleep(2.0)  # 足够长让后台线程至少检查两次
    watcher.stop()

    print(f"alerts count: {len(alerts)}")
    assert len(alerts) >= 1, f"预期至少 1 次告警，实际 {len(alerts)} 次"


def test_watcher_no_touch_timeout():
    """不 touch 时应在超时后告警。"""
    alerts = []
    watcher = _TimeoutWatcher(timeout=0.5, on_alert=lambda e: alerts.append(e))

    watcher.start()
    time.sleep(0.15)  # 等线程启动
    # 不 touch，直接等超时
    time.sleep(2.0)
    watcher.stop()

    print(f"alerts count: {len(alerts)}")
    assert len(alerts) >= 1, f"预期至少 1 次告警，实际 {len(alerts)} 次"


def test_alert_pushed_to_queue():
    """告警应被推送到 SSE 队列。"""
    while not _STREAM_QUEUE.empty():
        _STREAM_QUEUE.get_nowait()

    push_alert_event("stuck", "test message", step_id="step_1")
    assert _STREAM_QUEUE.qsize() == 1

    event = _STREAM_QUEUE.get_nowait()
    assert event["alert"] == "stuck"
    assert event["message"] == "test message"
    assert event["step_id"] == "step_1"


def test_multiple_alerts_queued():
    """多次告警应依次入队。"""
    while not _STREAM_QUEUE.empty():
        _STREAM_QUEUE.get_nowait()

    push_alert_event("stuck", "a1")
    push_alert_event("timeout", "a2")
    assert _STREAM_QUEUE.qsize() == 2

