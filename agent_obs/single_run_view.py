"""
单次运行透明化 —— 自包含 HTML 视图（M1.4）

把一份 SingleRunReport（agent_obs/single_run.py + health.py 的产物）渲染成一个
零依赖、可离线打开的 HTML：状态徽章 + 诊断横幅 + 步骤时间线（耗时条 + 高亮
失败/卡点/慢步骤 + 点击展开输入输出）。

别人只要打开这个 HTML 文件，就能看清自己 Agent 单次运行的全过程与卡点，
无需 npm 构建、无需起服务。（深度融入 Vue DevTools 见后续 M1.6。）

用法：
    from agent_obs.single_run import build_single_run_report
    from agent_obs.health import analyze_health
    from agent_obs.single_run_view import write_html

    report = build_single_run_report(ctx)
    analyze_health(report, completed=True)
    write_html(report, "single_run_report.html")
"""

import json
from typing import Dict

_TEMPLATE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AgentTrace · 单次运行报告</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;
         background:#f5f7fa; color:#303133; padding:32px; }
  .wrap { max-width:920px; margin:0 auto; }
  .head { display:flex; align-items:center; gap:14px; flex-wrap:wrap; margin-bottom:6px; }
  .head h1 { font-size:20px; font-weight:700; }
  .meta { color:#909399; font-size:13px; margin-bottom:18px; }
  .badge { padding:3px 12px; border-radius:12px; font-size:13px; font-weight:600; color:#fff; }
  .b-success { background:#67c23a; } .b-failed { background:#f56c6c; }
  .b-stuck { background:#e6a23c; } .b-unknown { background:#909399; }
  .diag { border-left:4px solid #409eff; background:#ecf5ff; padding:12px 16px; border-radius:6px;
          margin-bottom:24px; font-size:14px; }
  .diag.failed { border-color:#f56c6c; background:#fef0f0; }
  .diag.stuck  { border-color:#e6a23c; background:#fdf6ec; }
  .step { background:#fff; border:1px solid #ebeef5; border-left:4px solid #dcdfe6; border-radius:6px;
          padding:12px 16px; margin-bottom:10px; cursor:pointer; transition:box-shadow .15s; }
  .step:hover { box-shadow:0 2px 12px rgba(0,0,0,.08); }
  .step.error { border-left-color:#f56c6c; }
  .step.stuck { border-left-color:#e6a23c; }
  .step.slow  { border-left-color:#e6a23c; }
  .step.running { border-left-color:#e6a23c; }
  .row { display:flex; align-items:center; gap:12px; }
  .icon { width:20px; text-align:center; font-weight:700; }
  .i-ok { color:#67c23a; } .i-error { color:#f56c6c; } .i-running { color:#e6a23c; }
  .kind { font-size:11px; padding:2px 8px; border-radius:4px; background:#f0f2f5; color:#606266;
          text-transform:uppercase; letter-spacing:.5px; }
  .name { flex:1; font-weight:600; font-size:14px; word-break:break-all; }
  .flags { display:flex; gap:6px; }
  .flag { font-size:11px; padding:2px 8px; border-radius:4px; color:#fff; font-weight:600; }
  .f-fail { background:#f56c6c; } .f-stuck { background:#e6a23c; } .f-slow { background:#e6a23c; }
  .dur { color:#909399; font-size:12px; min-width:72px; text-align:right; }
  .bar { height:4px; background:#409eff; border-radius:2px; margin-top:8px; opacity:.6; }
  .detail { display:none; margin-top:12px; padding-top:12px; border-top:1px dashed #ebeef5; }
  .step.open .detail { display:block; }
  .detail pre { background:#fafafa; border:1px solid #ebeef5; border-radius:4px; padding:8px 10px;
                font-size:12px; overflow-x:auto; white-space:pre-wrap; word-break:break-all; }
  .detail .lbl { font-size:12px; color:#909399; margin:8px 0 4px; }
  .err { color:#f56c6c; }
  footer { text-align:center; color:#c0c4cc; font-size:12px; margin-top:24px; }
</style>
</head>
<body>
<div class="wrap">
  <div class="head">
    <h1 id="title"></h1>
    <span id="status" class="badge"></span>
  </div>
  <div class="meta" id="meta"></div>
  <div id="diag" class="diag"></div>
  <div id="steps"></div>
  <footer>AgentTrace · 单次运行透明化</footer>
</div>
<script>
const REPORT = __REPORT_JSON__;

function esc(s){ return String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
function fmtMs(v){ return v==null ? '-' : (v>=1000 ? (v/1000).toFixed(2)+'s' : v.toFixed(0)+'ms'); }

function render(r){
  document.getElementById('title').textContent = r.run_name || '单次运行报告';
  const st = document.getElementById('status');
  st.textContent = ({success:'成功',failed:'失败',stuck:'卡住',unknown:'未知'}[r.status]||r.status);
  st.className = 'badge b-' + r.status;
  document.getElementById('meta').textContent =
    `${r.step_count} 步 · 总耗时 ${fmtMs(r.duration_ms)}` + (r.run_id?` · run_id=${r.run_id}`:'');

  const h = r.health || {};
  const diag = document.getElementById('diag');
  diag.className = 'diag' + (r.status==='failed'?' failed':r.status==='stuck'?' stuck':'');
  diag.textContent = '📋 ' + (h.summary || '（无诊断）');

  const maxDur = Math.max(1, ...r.steps.map(s => s.duration_ms||0));
  const box = document.getElementById('steps');
  r.steps.forEach(s => {
    const isFail = s.id===h.failed_step_id, isStuck = s.id===h.stuck_step_id,
          isSlow = (h.slow_step_ids||[]).includes(s.id);
    const cls = ['step', isFail?'error':'', isStuck?'stuck':'', isSlow?'slow':'',
                 s.status==='running'?'running':''].filter(Boolean).join(' ');
    const icon = s.status==='error' ? '<span class="icon i-error">✗</span>'
               : s.status==='running' ? '<span class="icon i-running">…</span>'
               : '<span class="icon i-ok">✓</span>';
    const flags = [isFail?'<span class="flag f-fail">失败点</span>':'',
                   isStuck?'<span class="flag f-stuck">卡点</span>':'',
                   isSlow?'<span class="flag f-slow">慢</span>':''].join('');
    const barW = Math.round(((s.duration_ms||0)/maxDur)*100);
    const errBlock = s.error ? `<div class="lbl">错误</div><pre class="err">${esc(s.error)}</pre>` : '';
    const el = document.createElement('div');
    el.className = cls;
    el.innerHTML = `
      <div class="row">
        ${icon}
        <span class="kind">${esc(s.kind)}</span>
        <span class="name">${esc(s.name)}</span>
        <span class="flags">${flags}</span>
        <span class="dur">${fmtMs(s.duration_ms)}</span>
      </div>
      <div class="bar" style="width:${barW}%"></div>
      <div class="detail">
        <div class="lbl">输入</div><pre>${esc(JSON.stringify(s.input,null,2))}</pre>
        <div class="lbl">输出</div><pre>${esc(JSON.stringify(s.output,null,2))}</pre>
        ${errBlock}
      </div>`;
    el.addEventListener('click', () => el.classList.toggle('open'));
    box.appendChild(el);
  });
}
render(REPORT);
</script>
</body>
</html>
"""


def render_html(report: Dict) -> str:
    """把 SingleRunReport 渲染为自包含 HTML 字符串。"""
    # 安全嵌入 JSON：转义 </ 防止提前闭合 <script>
    payload = json.dumps(report, ensure_ascii=False).replace("</", "<\\/")
    return _TEMPLATE.replace("__REPORT_JSON__", payload)


def write_html(report: Dict, path: str) -> str:
    """渲染并写入 HTML 文件，返回路径。"""
    html = render_html(report)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path
