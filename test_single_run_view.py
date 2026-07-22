"""M1.4 单元测试：单次运行 HTML 视图（agent_obs/single_run_view.py）。

用「渲染后的 HTML 内容断言」验证：状态、诊断、步骤名、高亮标记、错误信息、
JSON 安全嵌入。运行：pytest test_single_run_view.py -v
"""

from agent_obs.single_run import build_single_run_report
from agent_obs.health import analyze_health
from agent_obs.single_run_view import render_html


def _report(raw):
    r = build_single_run_report(raw, run_id="v1", run_name="view_demo")
    analyze_health(r)
    return r


def test_html_is_self_contained():
    html = render_html(_report([]))
    assert html.strip().startswith("<!DOCTYPE html>")
    # 无外链资源（自包含）
    assert "http://" not in html.split("<script>")[0]
    assert "src=" not in html  # 无外部脚本/图片引用


def test_html_embeds_status_and_steps():
    raw = [
        {"type": "llm", "id": "llm_1", "prompt": "hi", "output": "ok",
         "latency_ms": 12.0, "start_time": 100.0, "end_time": 100.012, "status": "success"},
        {"type": "tool", "id": "tool_2", "name": "weather_api", "args": {"city": "东京"},
         "result": None, "latency_ms": 3.0, "start_time": 100.02, "end_time": 100.02,
         "status": "error", "error": "连接超时"},
    ]
    html = render_html(_report(raw))
    # 顶层状态
    assert '"status": "failed"' in html or '"status":"failed"' in html
    # 步骤名与工具名
    assert "weather_api" in html
    # 错误信息与诊断被嵌入
    assert "连接超时" in html
    # 失败点 id 出现在 health
    assert "tool_2" in html


def test_html_escapes_script_break():
    # 输出里含 </script> 不应破坏页面
    raw = [{"type": "output", "id": "o1", "var": "answer",
            "value": "</script><b>x</b>", "latency_ms": 1.0}]
    html = render_html(_report(raw))
    # 原样 </script> 不应出现在嵌入的 JSON 里（被转义为 <\/script>）
    assert "</script><b>x</b>" not in html
    assert "<\\/script>" in html


def test_write_html_file(tmp_path):
    from agent_obs.single_run_view import write_html
    raw = [{"type": "llm", "id": "l1", "prompt": "hi", "output": "ok", "latency_ms": 5.0}]
    out = tmp_path / "report.html"
    write_html(_report(raw), str(out))
    content = out.read_text(encoding="utf-8")
    assert "view_demo" in content
    assert content.startswith("<!DOCTYPE html>")
