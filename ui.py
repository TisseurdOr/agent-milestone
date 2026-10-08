"""Zero-dependency local web console for agent-milestone.

The console is intentionally local-first and uses the same TrailStore as the
MCP server. It provides a GitHub-like tabbed experience:

  Browse  - inspect one milestone/branch trajectory
  Diff    - pick base/compare refs in a dedicated tab
  Replay  - dry-run tool plan
  Reflog  - ref history
  Export  - markdown output
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from store import DEFAULT_DB_PATH, TrailStore

INDEX_HTML = r"""<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>agent-milestone · 控制台</title>
<style>
:root{--bg:#0f1117;--panel:#171a23;--panel2:#1e2230;--line:#2d3343;--text:#e6e9f0;--muted:#8b93a7;--blue:#6ea8fe;--green:#63d3a6;--red:#ff7b7b;--yellow:#f5c86b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
header{display:flex;gap:12px;align-items:center;padding:14px 18px;border-bottom:1px solid var(--line);background:var(--panel)}
header h1{font-size:16px;margin:0;flex:1}.muted{color:var(--muted);font-size:12px}
button{background:var(--panel2);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:7px 11px;cursor:pointer}
button:hover{border-color:var(--blue)}button.primary{background:#2f5fd0;border-color:#2f5fd0}
main{display:grid;grid-template-columns:300px 1fr;height:calc(100vh - 61px)}
aside{border-right:1px solid var(--line);overflow:auto;padding:12px}
#refs{display:flex;flex-direction:column;gap:6px}.ref{padding:9px;border:1px solid var(--line);border-radius:8px;background:var(--panel);cursor:pointer}
.ref:hover{border-color:var(--blue)}.ref.active{border-color:var(--blue);background:#1b2540}
.ref b{display:block;font-size:13px}.ref small{color:var(--muted)}
.kind{display:inline-block;border-radius:99px;font-size:10px;padding:1px 7px;margin-left:6px;background:#26324a;color:var(--blue)}
.kind.milestone{background:#233b33;color:var(--green)}
.tree-folder{margin:4px 0}.tree-folder>summary{list-style:none;display:flex;align-items:center;gap:6px;padding:5px 6px;border-radius:6px;cursor:pointer}
.tree-folder>summary::-webkit-details-marker{display:none}.tree-folder>summary:hover{background:var(--panel2)}
.tree-children{margin-left:14px;border-left:1px solid var(--line);padding-left:8px}
.tree-leaf{display:flex;align-items:center;gap:6px;padding:5px 6px;border-radius:6px;cursor:pointer}
.tree-leaf:hover{background:var(--panel2)}.tree-leaf.active{background:#1b2540;outline:1px solid var(--blue)}
.tree-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.tree-meta{color:var(--muted);font-size:11px;margin-left:auto}
.icon{display:inline-flex;width:16px;height:16px;align-items:center;justify-content:center;color:var(--muted)}
.icon svg{width:14px;height:14px;fill:currentColor}
.icon.branch{color:#6ea8fe}.icon.tag{color:#63d3a6}.icon.folder{color:#f5c86b}
section{padding:16px;overflow:auto}
.tabs{display:flex;gap:6px;border-bottom:1px solid var(--line);margin-bottom:14px}
.tab{border:0;border-bottom:2px solid transparent;border-radius:0;background:transparent;color:var(--muted);padding:8px 12px}
.tab.active{color:var(--text);border-bottom-color:var(--blue)}
.panel.hidden{display:none}.toolbar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px;margin-bottom:12px}
pre{white-space:pre-wrap;word-break:break-word;background:#0b0d12;border:1px solid var(--line);border-radius:8px;padding:10px;overflow:auto}
.step{border-left:3px solid var(--line);padding:8px 10px;margin:8px 0;background:var(--panel2);border-radius:6px}
.step.user{border-color:var(--blue)}.step.assistant{border-color:var(--green)}.step.tool{border-color:var(--red)}
.role{font-size:12px;color:var(--muted);margin-bottom:4px}.toolname{font-family:monospace;font-weight:700;color:var(--red)}
select,input,textarea{background:#0b0d12;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:7px}
.comparebar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
.diff-row{padding:7px 9px;border-radius:6px;margin:4px 0;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}
.diff-row.add{background:#143326;color:#9be7bd}.diff-row.del{background:#3a1d22;color:#ffb3b3}
.diff-title{font-weight:700;margin:8px 0 4px}
.modal{position:fixed;inset:0;background:rgba(0,0,0,.65);display:flex;align-items:center;justify-content:center;z-index:50}
.modal-box{width:min(640px,92vw);background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px;box-shadow:0 24px 80px rgba(0,0,0,.4)}
.modal-box h3{margin:0 0 12px}.modal-body{display:flex;flex-direction:column;gap:8px}.modal-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:16px}
.modal-body label{color:var(--muted);font-size:12px}.modal-body textarea{min-height:220px}
.modal-error{background:#3a1d22;border:1px solid var(--red);color:#ffb3b3;border-radius:8px;padding:8px 10px;margin-top:10px}
.toast{position:fixed;right:20px;bottom:20px;background:#233b33;border:1px solid var(--green);color:var(--text);border-radius:10px;padding:10px 14px;z-index:60;max-width:520px}
.toast.error{background:#3a1d22;border-color:var(--red)}
.hidden{display:none}
</style>
</head>
<body>
<header>
  <h1>agent-milestone · 控制台</h1>
  <span class="muted" id="dbLabel"></span>
  <button onclick="loadAll()">刷新</button>
  <button onclick="newCheckpoint()">新建 checkpoint</button>
  <button onclick="newBranch()">新建 branch</button>
</header>
<main>
  <aside>
    <div class="muted" style="margin-bottom:8px">Milestones / Branches</div>
    <div id="refs"></div>
  </aside>
  <section>
    <nav class="tabs">
      <button class="tab active" data-tab="browse" onclick="showTab('browse')">轨迹</button>
      <button class="tab" data-tab="diff" onclick="showTab('diff')">Diff</button>
      <button class="tab" data-tab="replay" onclick="showTab('replay')">Replay</button>
      <button class="tab" data-tab="reflog" onclick="showTab('reflog')">Reflog</button>
      <button class="tab" data-tab="export" onclick="showTab('export')">导出</button>
    </nav>

    <div id="panel-browse" class="panel">
      <div class="toolbar">
        <button onclick="rollbackRef()">回滚到...</button>
        <button onclick="undoLast()">撤回上一个操作</button>
        <button onclick="moveToBranch()">移动到 branch...</button>
        <button onclick="renameRef()">重命名</button>
        <button onclick="deleteRef()">删除</button>
      </div>
      <div class="card"><h3 id="title">选择左侧一个 ref</h3><div id="meta" class="muted"></div></div>
      <div id="content" class="card">暂无内容</div>
    </div>

    <div id="panel-diff" class="panel hidden">
      <div class="comparebar">
        <span class="muted">base</span>
        <select id="diffBase"></select>
        <span class="muted">←</span>
        <select id="diffCompare"></select>
        <button class="primary" onclick="renderDiff()">Compare</button>
        <button onclick="swapDiff()">Swap</button>
      </div>
      <div id="diffResult" class="card muted">选择两个 ref 后点击 Compare</div>
    </div>

    <div id="panel-replay" class="panel hidden">
      <div class="toolbar">
        <select id="replayRef"></select>
        <button class="primary" onclick="renderReplay()">Run dry-run</button>
      </div>
      <div id="replayResult" class="card muted">Replay 只会输出工具调用计划，不会执行工具。</div>
    </div>

    <div id="panel-reflog" class="panel hidden">
      <div class="toolbar">
        <button onclick="renderReflog()">刷新 Reflog</button>
        <button onclick="runGc()">GC dry-run</button>
      </div>
      <div id="reflogResult" class="card muted">暂无记录</div>
    </div>

    <div id="panel-export" class="panel hidden">
      <div class="toolbar">
        <select id="exportRef"></select>
        <button class="primary" onclick="renderExport()">导出 Markdown</button>
      </div>
      <pre id="exportResult">选择 ref 后导出</pre>
    </div>
  </section>
</main>
<div id="modal" class="modal hidden">
  <div class="modal-box">
    <h3 id="modalTitle"></h3>
    <div id="modalBody" class="modal-body"></div>
    <div id="modalError" class="modal-error hidden"></div>
    <div class="modal-actions">
      <button onclick="closeModal()">取消</button>
      <button id="modalOk" class="primary" onclick="submitModal()">确认</button>
    </div>
  </div>
</div>
<div id="toast" class="toast hidden"></div>
<script>
let refs = [];
let current = null;
let activeTab = 'browse';
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const api = async (path, opt) => { const r = await fetch(path, opt); if (!r.ok) throw new Error(await r.text()); return r.json(); };
const jsonOpt = body => ({method:'POST', headers:{'content-type':'application/json'}, body:JSON.stringify(body)});
const ICONS = {
  branch: '<svg viewBox="0 0 16 16"><path d="M5 3.5a2.5 2.5 0 1 1-3 2.45v4.1a2.5 2.5 0 1 1-2 0V4.5h-.5a.75.75 0 0 1 0-1.5H2A2.5 2.5 0 0 1 4.5 2h7A2.5 2.5 0 0 1 14 4.5v3.05a2.5 2.5 0 1 1-2 0V4.5a.5.5 0 0 0-.5-.5h-4a2.5 2.5 0 0 1-2.5-.5Z"/></svg>',
  tag: '<svg viewBox="0 0 16 16"><path d="M2 2h5.6c.4 0 .8.16 1.1.44l5 5a1.5 1.5 0 0 1 0 2.12l-4.94 4.94a1.5 1.5 0 0 1-2.12 0l-5-5A1.5 1.5 0 0 1 1.2 8.4V3.5A1.5 1.5 0 0 1 2.7 2H2Zm2.75 3.5a1.25 1.25 0 1 0 0-2.5 1.25 1.25 0 0 0 0 2.5Z"/></svg>',
  folder: '<svg viewBox="0 0 16 16"><path d="M1.75 3A1.75 1.75 0 0 1 3.5 1.25h2.38c.46 0 .9.18 1.23.5l.86.87c.14.14.33.22.53.22h4A1.75 1.75 0 0 1 14.25 4.6v7.65A1.75 1.75 0 0 1 12.5 14h-9a1.75 1.75 0 0 1-1.75-1.75V3Z"/></svg>'
};
const icon = name => `<span class="icon ${name}">${ICONS[name] || ''}</span>`;

async function loadAll() {
  refs = await api('/api/refs');
  const box = document.getElementById('refs');
  box.innerHTML = renderRefsTree();
  fillSelect('diffBase', current);
  fillSelect('diffCompare', current);
  fillSelect('replayRef', current);
  fillSelect('exportRef', current);
  if (!current && refs.length) await selectRef(refs[0].name);
  else if (current && !refs.some(r => r.name === current)) current = null;
}

function renderLeaf(r, depth = 0) {
  const active = current === r.name ? ' active' : '';
  return `<div class="tree-leaf${active}" style="margin-left:${depth * 12}px" data-name="${esc(r.name)}" onclick="selectRefFromEl(this)">${icon('tag')}<span class="tree-name">${esc(r.name)}</span><span class="tree-meta">${r.steps} steps · ${esc(r.tip.slice(0, 8))}</span></div>`;
}

function renderBranch(branch, branchByName, used) {
  if (used.has(branch.name)) return '';
  used.add(branch.name);
  const childBranches = refs.filter(r => r.kind === 'branch' && r.parent_ref === branch.name);
  const childMilestones = refs.filter(r => r.kind === 'milestone' && r.parent_ref === branch.name);
  const children = [
    ...childBranches.map(b => renderBranch(b, branchByName, used)),
    ...childMilestones.map(r => renderLeaf(r, 1)),
  ].join('');
  return `<details class="tree-folder" open><summary data-name="${esc(branch.name)}" onclick="event.preventDefault(); selectRefFromEl(this)">${icon('folder')}${icon('branch')}<span class="tree-name">${esc(branch.name)}</span><span class="tree-meta">${branch.steps} steps</span></summary>${children ? `<div class="tree-children">${children}</div>` : ''}</details>`;
}

function selectRefFromEl(el) {
  selectRef(el.dataset.name);
}

function renderRefsTree() {
  const branchByName = new Map(refs.filter(r => r.kind === 'branch').map(r => [r.name, r]));
  const used = new Set();
  const rootBranches = refs.filter(r => r.kind === 'branch' && (!r.parent_ref || !branchByName.has(r.parent_ref)));
  const rootMilestones = refs.filter(r => r.kind === 'milestone' && (!r.parent_ref || !branchByName.has(r.parent_ref)));
  const branchTree = rootBranches.map(b => renderBranch(b, branchByName, used)).join('');
  const leftovers = refs.filter(r => r.kind === 'branch' && !used.has(r.name)).map(b => renderBranch(b, branchByName, used)).join('');
  const milestones = rootMilestones.map(r => renderLeaf(r)).join('');
  return `<div class="muted" style="margin:6px 0">Branches</div>${branchTree || leftovers || '<div class="muted">无</div>'}<div class="muted" style="margin:12px 0 6px">Milestones</div>${milestones || '<div class="muted">无</div>'}`;
}

function fillSelect(id, preferred) {
  const s = document.getElementById(id);
  if (!s) return;
  const old = s.value;
  s.innerHTML = '';
  refs.forEach(r => { const o = document.createElement('option'); o.value = r.name; o.textContent = r.name; s.appendChild(o); });
  if (preferred && refs.some(r => r.name === preferred)) s.value = preferred;
  else if (old && refs.some(r => r.name === old)) s.value = old;
}

function showTab(tab) {
  activeTab = tab;
  document.querySelectorAll('.tab').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  document.querySelectorAll('.panel').forEach(p => p.classList.toggle('hidden', p.id !== 'panel-' + tab));
  if (tab === 'diff') renderDiff();
  if (tab === 'reflog') renderReflog();
  if (tab === 'replay') fillSelect('replayRef', current);
  if (tab === 'export') fillSelect('exportRef', current);
}

async function selectRef(name) {
  current = name;
  showTab('browse');
  const data = await api('/api/ref/' + encodeURIComponent(name));
  document.getElementById('title').textContent = data.ref.name;
  document.getElementById('meta').textContent = `${data.ref.kind} · ${data.ref.steps} steps · ${data.ref.updated_at}`;
  const c = document.getElementById('content');
  c.innerHTML = '';
  data.steps.forEach(s => {
    const d = document.createElement('div');
    d.className = 'step ' + esc(s.role || '');
    if (s.role === 'tool') {
      d.innerHTML = `<div class="role">tool</div><div class="toolname">${esc(s.tool_name || '')}</div><pre>${esc(JSON.stringify(s.tool_args ?? {}, null, 2))}</pre>${s.tool_result ? `<pre>${esc(JSON.stringify(s.tool_result, null, 2))}</pre>` : ''}`;
    } else {
      d.innerHTML = `<div class="role">${esc(s.role || '')}</div><div>${esc(s.content || '')}</div>`;
    }
    c.appendChild(d);
  });
  await loadAll();
}

async function renderDiff() {
  const left = document.getElementById('diffBase').value;
  const right = document.getElementById('diffCompare').value;
  if (!left || !right) return;
  const d = await api(`/api/diff?left=${encodeURIComponent(left)}&right=${encodeURIComponent(right)}`);
  const base = d.left_only.map(s => `<div class="diff-row del">- ${esc(s.tool_name || s.content || s.role)}</div>`).join('');
  const compare = d.right_only.map(s => `<div class="diff-row add">+ ${esc(s.tool_name || s.content || s.role)}</div>`).join('');
  document.getElementById('diffResult').innerHTML = `
    <h3>${esc(left)} ← ${esc(right)}</h3>
    <p class="muted">共同前缀 ${d.common_steps} 步 · base 独有 ${d.left_only_count} 步 · compare 独有 ${d.right_only_count} 步</p>
    <div class="diff-title">只在 base：${esc(left)}</div>${base || '<div class="muted">无</div>'}
    <div class="diff-title">只在 compare：${esc(right)}</div>${compare || '<div class="muted">无</div>'}`;
}

function swapDiff() {
  const a = document.getElementById('diffBase');
  const b = document.getElementById('diffCompare');
  [a.value, b.value] = [b.value, a.value];
  renderDiff();
}

async function renderReplay() {
  const name = document.getElementById('replayRef').value;
  if (!name) return;
  const plan = await api('/api/replay', jsonOpt({name}));
  document.getElementById('replayResult').innerHTML = `<pre>${esc(JSON.stringify(plan.actions, null, 2))}</pre>`;
}

async function renderReflog() {
  const log = await api('/api/reflog?limit=100');
  document.getElementById('reflogResult').innerHTML = `<pre>${esc(JSON.stringify(log, null, 2))}</pre>`;
}

async function renderExport() {
  const name = document.getElementById('exportRef').value;
  if (!name) return;
  const r = await fetch('/api/export?name=' + encodeURIComponent(name));
  document.getElementById('exportResult').textContent = await r.text();
}

let modalSubmit = null;
const optionsHtml = () => refs.map(r => `<option value="${esc(r.name)}">${esc(r.name)}</option>`).join('');

function openModal(title, bodyHtml, onSubmit) {
  document.getElementById('modalTitle').textContent = title;
  document.getElementById('modalBody').innerHTML = bodyHtml;
  document.getElementById('modalError').classList.add('hidden');
  document.getElementById('modal').classList.remove('hidden');
  modalSubmit = onSubmit;
}

function closeModal() {
  document.getElementById('modal').classList.add('hidden');
  modalSubmit = null;
}

async function submitModal() {
  if (!modalSubmit) return;
  const ok = document.getElementById('modalOk');
  ok.disabled = true;
  try {
    await modalSubmit();
    closeModal();
  } catch (e) {
    const el = document.getElementById('modalError');
    el.textContent = e.message || String(e);
    el.classList.remove('hidden');
  } finally {
    ok.disabled = false;
  }
}

function toast(message, isError = false) {
  const el = document.getElementById('toast');
  el.textContent = message;
  el.className = 'toast' + (isError ? ' error' : '');
  setTimeout(() => el.classList.add('hidden'), 4000);
}

function newCheckpoint() {
  openModal('新建 checkpoint', `
    <label>名称</label><input id="cpName" placeholder="例如：对账排查-第二版">
    <label>归属 branch（可选）</label><select id="cpParent"><option value="">无</option>${refs.filter(r => r.kind === 'branch').map(r => `<option value="${esc(r.name)}">${esc(r.name)}</option>`).join('')}</select>
    <label>Steps JSON</label><textarea id="cpSteps">[{"role":"user","content":"hello"}]</textarea>
  `, async () => {
    const name = document.getElementById('cpName').value.trim();
    if (!name) throw new Error('请输入 checkpoint 名称');
    const parent = document.getElementById('cpParent').value || null;
    let steps;
    try { steps = JSON.parse(document.getElementById('cpSteps').value); }
    catch (e) { throw new Error('Steps JSON 解析失败: ' + e.message); }
    await api('/api/checkpoint', jsonOpt({name, steps, parent_ref: parent}));
    await selectRef(name);
    toast(`checkpoint 已创建: ${name}`);
  });
}

function newBranch() {
  openModal('新建 branch', `
    <label>名称</label><input id="brName" placeholder="例如：HBase路线">
    <label>从哪个 ref 分叉</label><select id="brFrom">${optionsHtml()}</select>
  `, async () => {
    const name = document.getElementById('brName').value.trim();
    const from = document.getElementById('brFrom').value;
    if (!name || !from) throw new Error('请输入 branch 名称和起点');
    await api('/api/branch', jsonOpt({name, from_ref: from}));
    await selectRef(name);
    toast(`branch 已创建: ${name} ← ${from}`);
  });
}

function renameRef() {
  if (!current) return;
  openModal('重命名 ref', `
    <label>新名称</label><input id="rnName" value="${esc(current)}">
  `, async () => {
    const name = document.getElementById('rnName').value.trim();
    if (!name || name === current) throw new Error('请输入不同的新名称');
    await api('/api/rename', jsonOpt({old_name: current, new_name: name}));
    current = name;
    await selectRef(name);
    toast(`已重命名为: ${name}`);
  });
}

function deleteRef() {
  if (!current) return;
  const name = current;
  openModal('删除 ref', `<p>确认删除 <b>${esc(name)}</b>？</p><p class="muted">不会立刻删除 step，之后可以 GC。</p>`, async () => {
    await api('/api/delete', jsonOpt({name}));
    current = null;
    await loadAll();
    showTab('browse');
    toast(`已删除 ref: ${name}`);
  });
}

function rollbackRef() {
  if (!current) return;
  const name = current;
  openModal('回滚 ref', `
    <label>把 ${esc(name)} 回滚到</label><select id="rbTarget">${optionsHtml()}</select>
    <p class="muted">只移动 ref 指针，不删除历史 step。</p>
  `, async () => {
    const to = document.getElementById('rbTarget').value;
    const result = await api('/api/rollback', jsonOpt({name, to_ref: to}));
    await selectRef(name);
    toast(`已回滚 ${result.name}: ${result.from_tip.slice(0, 12)} → ${result.to_tip.slice(0, 12)}`);
  });
}

function undoLast() {
  if (!current) return;
  const name = current;
  openModal('撤回上一个操作', `<p>确认撤回 <b>${esc(name)}</b> 的上一个 checkpoint/rollback？</p>`, async () => {
    const result = await api('/api/undo', jsonOpt({name}));
    await selectRef(name);
    toast(`已撤回上一个 ${result.undid} 操作: ${result.from_tip.slice(0, 12)} → ${result.to_tip.slice(0, 12)}`);
  });
}

function moveToBranch() {
  if (!current) return;
  const name = current;
  openModal('移动到 branch 文件夹', `
    <label>归属 branch</label><select id="mvParent"><option value="">根目录</option>${refs.filter(r => r.kind === 'branch' && r.name !== name).map(r => `<option value="${esc(r.name)}">${esc(r.name)}</option>`).join('')}</select>
  `, async () => {
    const parent = document.getElementById('mvParent').value || null;
    await api('/api/set_parent', jsonOpt({name, parent_ref: parent}));
    await loadAll();
    toast(parent ? `已移动到 ${parent}` : '已移动到根目录');
  });
}

async function runGc() {
  const r = await api('/api/gc', jsonOpt({dry_run: true}));
  document.getElementById('reflogResult').innerHTML = `<pre>${esc(JSON.stringify(r, null, 2))}</pre>`;
}

loadAll().catch(e => toast(e.message || String(e), true));
</script>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    store: TrailStore
    server_version = "agent-milestone-ui/0.2"

    def _send(self, status: int, body: str, content_type: str = "application/json") -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, status: int, data) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False, default=str))

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw or "{}")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            if parsed.path in ("/", "/index.html"):
                return self._send(200, INDEX_HTML, "text/html")
            if parsed.path == "/favicon.ico":
                return self._send(204, "", "image/x-icon")
            if parsed.path == "/api/refs":
                return self._json(200, self.store.list_refs())
            if parsed.path.startswith("/api/ref/"):
                name = unquote(parsed.path.removeprefix("/api/ref/"))
                ref = next((r for r in self.store.list_refs() if r["name"] == name), None)
                if ref is None:
                    return self._json(404, {"error": f"ref not found: {name}"})
                return self._json(200, {"ref": ref, "steps": self.store.checkout(name)})
            if parsed.path == "/api/diff":
                return self._json(200, self.store.diff(query.get("left", [""])[0], query.get("right", [""])[0]))
            if parsed.path == "/api/reflog":
                name = query.get("name", [None])[0]
                limit = int(query.get("limit", ["50"])[0])
                return self._json(200, self.store.reflog(name=name, limit=limit))
            if parsed.path == "/api/export":
                name = query.get("name", [""])[0]
                return self._send(200, self.store.export(name), "text/plain")
            return self._json(404, {"error": "not found"})
        except KeyError as exc:
            return self._json(404, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            return self._json(400, {"error": str(exc)})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            data = self._body()
            if parsed.path == "/api/checkpoint":
                tip = self.store.checkpoint(data["name"], data["steps"], parent_ref=data.get("parent_ref"))
                return self._json(200, {"ok": True, "tip": tip})
            if parsed.path == "/api/branch":
                return self._json(200, self.store.branch(data["name"], data["from_ref"]))
            if parsed.path == "/api/rename":
                return self._json(200, self.store.rename(data["old_name"], data["new_name"]))
            if parsed.path == "/api/delete":
                return self._json(200, self.store.delete(data["name"]))
            if parsed.path == "/api/rollback":
                return self._json(200, self.store.rollback(data["name"], data["to_ref"]))
            if parsed.path == "/api/undo":
                return self._json(200, self.store.undo_last(data["name"]))
            if parsed.path == "/api/set_parent":
                return self._json(200, self.store.set_parent(data["name"], data.get("parent_ref")))
            if parsed.path == "/api/replay":
                return self._json(200, self.store.replay(data["name"]))
            if parsed.path == "/api/gc":
                return self._json(200, self.store.gc(dry_run=bool(data.get("dry_run", True))))
            if parsed.path == "/api/prune":
                return self._json(200, self.store.prune(
                    older_than_days=data.get("older_than_days"),
                    keep_last=data.get("keep_last"),
                    dry_run=bool(data.get("dry_run", True)),
                ))
            return self._json(404, {"error": "not found"})
        except KeyError as exc:
            return self._json(404, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            return self._json(400, {"error": str(exc)})


def make_server(host: str = "127.0.0.1", port: int = 8765, db_path: str = DEFAULT_DB_PATH) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"store": TrailStore(db_path)})
    return ThreadingHTTPServer((host, port), handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="agent-milestone local web console")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    args = parser.parse_args()
    server = make_server(args.host, args.port, args.db)
    print(f"agent-milestone UI: http://{args.host}:{args.port}")
    print(f"store: {args.db}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
