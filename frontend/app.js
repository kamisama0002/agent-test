const state = {
  system: 'codex',
  events: [],
  cursor: 0,
  playing: false,
  busy: false,
  nodes: [],
  lastRun: '',
  timer: null,
  messages: { codex: [], claude: [], hermes: [], deepseek: [] },
};
const els = {
  tabs: document.querySelectorAll('#systems button'),
  workspace: document.getElementById('workspace-label'),
  status: document.getElementById('run-status'),
  messages: document.getElementById('messages'),
  question: document.getElementById('question'),
  send: document.getElementById('send'),
  form: document.getElementById('chat-form'),
  reset: document.getElementById('reset'),
  iframe: document.getElementById('diagram'),
  title: document.getElementById('diagram-title'),
  activePill: document.getElementById('active-pill'),
  eventCount: document.getElementById('event-count'),
  runId: document.getElementById('run-id'),
  events: document.getElementById('events'),
  nodeView: document.getElementById('node-view'),
  plugins: document.getElementById('opt-plugins'),
  mcp: document.getElementById('opt-mcp'),
  multi: document.getElementById('opt-multi'),
  approval: document.getElementById('opt-approval'),
  permission: document.getElementById('opt-permission'),
  engine: document.getElementById('opt-engine'),
  fault: document.getElementById('opt-fault'),
  prev: document.getElementById('prev-step'),
  next: document.getElementById('next-step'),
  play: document.getElementById('play-toggle'),
  stepIndicator: document.getElementById('step-indicator'),
};

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function icon(role) { return role === 'user' ? '你' : 'M'; }
function setStatus(text, kind='') {
  els.status.textContent = text;
  els.status.className = 'status-dot ' + kind;
}
function appendMessage(role, text) {
  state.messages[state.system].push({ role, text });
  renderMessages();
}
function renderMessages() {
  const rows = state.messages[state.system];
  els.messages.innerHTML = '';
  if (!rows.length) {
    els.messages.innerHTML = `<div class="message agent"><div class="avatar">M</div><div class="bubble">选择一个系统，然后输入任务。示例：<br>“读取 README.md，用一句话总结，不要修改文件。”</div></div>`;
    return;
  }
  for (const row of rows) {
    const node = document.createElement('div');
    node.className = 'message ' + row.role;
    node.innerHTML = `<div class="avatar">${icon(row.role)}</div><div class="bubble">${esc(row.text)}</div>`;
    els.messages.appendChild(node);
  }
  els.messages.scrollTop = els.messages.scrollHeight;
}
async function fetchJSON(url, options) {
  const response = await fetch(url, { cache: 'no-store', ...options });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || ('HTTP ' + response.status));
  return data;
}
async function loadConfig() {
  const data = await fetchJSON('/api/config');
  const info = data.systems[state.system];
  els.workspace.textContent = info.workspace;
}
function options() {
  return {
    plugins: els.plugins.checked,
    mcp: els.mcp.checked,
    multi_agent: els.multi.checked,
    approval_mode: els.approval.value,
    permission_mode: els.permission.value,
    engine: els.engine.value,
    fault_mode: els.fault ? els.fault.value : 'none',
  };
}
async function sendQuestion(event) {
  event.preventDefault();
  if (state.busy) return;
  const text = els.question.value.trim();
  if (!text) return;
  state.busy = true;
  els.send.disabled = true;
  setStatus('running', 'running');
  appendMessage('user', text);
  els.question.value = '';
  try {
    const data = await fetchJSON('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ system: state.system, message: text, options: options() }),
    });
    appendMessage('agent', data.answer || '(empty answer)');
    setStatus(data.success ? 'done' : 'failed', data.success ? 'ok' : 'error');
    if (data.errors && data.errors.length) console.warn(data.errors);
  } catch (error) {
    appendMessage('agent', '运行失败：' + error.message);
    setStatus('error', 'error');
  } finally {
    state.busy = false;
    els.send.disabled = false;
    pollTrace();
  }
}
function switchSystem(system) {
  state.system = system;
  state.playing = false;
  state.events = [];
  state.cursor = 0;
  state.lastRun = '';
  state.nodes = [];
  document.body.dataset.system = system;
  els.tabs.forEach(tab => tab.classList.toggle('active', tab.dataset.system === system));
  const titles = {
    codex: 'Mini Codex：LangGraph 运行流',
    claude: 'Claude mini：queryLoop 运行流',
    hermes: 'Hermes mini：记忆与复盘运行流',
    deepseek: 'DeepSeek Harness：推理、重试与 checkpoint',
  };
  els.title.textContent = titles[system];
  els.iframe.src = '/diagram?system=' + encodeURIComponent(system) + '&theme=light&embed=1';
  els.activePill.textContent = '等待运行…';
  els.events.innerHTML = '<div class="empty">还没有事件。发送一个问题开始。</div>';
  els.nodeView.innerHTML = '<div class="empty">点击中间图里的节点<br>查看源码位置、设计边界和当前运行参数。</div>';
  els.eventCount.textContent = '0 events';
  els.runId.textContent = 'no run';
  renderMessages();
  setStatus(state.busy ? 'running' : 'idle', state.busy ? 'running' : '');
  renderPlayState();
  updateStepIndicator();
  loadConfig().catch(console.error);
  pollTrace();
}

function injectDiagramStyles() {
  const doc = els.iframe.contentDocument;
  if (!doc || !doc.head || doc.getElementById('studio-live-style')) return;
  const style = doc.createElement('style');
  style.id = 'studio-live-style';
  style.textContent = `
    [data-node-id].studio-active > rect:not(.c-mask) {
      stroke: #0284c7 !important;
      stroke-width: 4 !important;
      filter: drop-shadow(0 0 9px rgba(2,132,199,.55));
    }
    [data-node-id].studio-done > rect:not(.c-mask) {
      stroke: #059669 !important;
      stroke-width: 2.5 !important;
    }
  `;
  doc.head.appendChild(style);
}
function bindNodeClicks() {
  const doc = els.iframe.contentDocument;
  if (!doc) return;
  doc.querySelectorAll('[data-node-id]').forEach(node => {
    if (node.dataset.studioBound === '1') return;
    node.dataset.studioBound = '1';
    node.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();
      inspectNode(node.dataset.nodeId).catch(console.error);
    });
  });
}
function markNode(nodeId, doneBefore) {
  const doc = els.iframe.contentDocument;
  if (!doc) return;
  injectDiagramStyles();
  doc.querySelectorAll('[data-node-id]').forEach(node => node.classList.remove('studio-active'));
  if (doneBefore) {
    const previous = doc.querySelector(`[data-node-id="${CSS.escape(doneBefore)}"]`);
    if (previous) previous.classList.add('studio-done');
  }
  if (!nodeId) return;
  const active = doc.querySelector(`[data-node-id="${CSS.escape(nodeId)}"]`);
  if (!active) return;
  active.classList.add('studio-active');
  try { active.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'center' }); } catch (_) {}
}
function renderStructuredValue(value) {
  if (value === null || value === undefined) return '<p class="snapshot-empty">(empty)</p>';
  if (typeof value === 'string') return `<pre class="snapshot-text">${esc(value)}</pre>`;
  return `<pre class="snapshot-json">${esc(JSON.stringify(value, null, 2))}</pre>`;
}
function renderContextSnapshot(snapshot) {
  if (!snapshot || typeof snapshot !== 'object' || Array.isArray(snapshot)) return '';
  const entries = Object.entries(snapshot);
  if (!entries.length) return '';
  return `
    <details class="context-drawer" open>
      <summary>完整上下文快照 <span>${entries.length} 个分区</span></summary>
      <div class="context-intro">这里显示的是 Harness 在事件发生时实际读取/装配的内容。字符数只是索引，下面是正文。</div>
      ${entries.map(([name, value]) => `
        <details class="context-block" open>
          <summary>${esc(name)}</summary>
          ${renderStructuredValue(value)}
        </details>
      `).join('')}
    </details>
  `;
}
function renderMessages(messages) {
  if (!Array.isArray(messages) || !messages.length) return '';
  return `
    <details class="context-drawer" open>
      <summary>实际进入模型的消息 <span>${messages.length} 条</span></summary>
      <div class="message-snapshot">
        ${messages.map((message, index) => `
          <article class="snapshot-message">
            <div class="snapshot-message-head">#${index + 1} · ${esc(message.role || 'message')}${message.name ? ' · ' + esc(message.name) : ''}</div>
            ${renderStructuredValue(message.content)}
            ${message.tool_calls ? `<div class="snapshot-sub">tool_calls</div>${renderStructuredValue(message.tool_calls)}` : ''}
          </article>
        `).join('')}
      </div>
    </details>
  `;
}
function renderExplanation(explanation) {
  if (!explanation) return '';
  const rows = [
    ['why', '为什么需要这一步'],
    ['input', '输入'],
    ['output', '输出 / 观察'],
    ['design', '设计思路'],
    ['system_design', '这套 Harness 的取舍'],
    ['next', '下一步'],
  ];
  const sourceRefs = Array.isArray(explanation.source_refs) ? explanation.source_refs : [];
  return `
    <div class="explain-grid">
      ${rows.filter(([key]) => explanation[key]).map(([key, label]) => `
        <section class="explain-item explain-${key}">
          <div class="explain-label">${label}</div>
          <p>${esc(explanation[key])}</p>
        </section>
      `).join('')}
      ${sourceRefs.length ? `
        <section class="explain-item explain-source">
          <div class="explain-label">源码依据</div>
          <div class="source-ref-list">${sourceRefs.map(ref => `<code>${esc(ref)}</code>`).join('')}</div>
        </section>
      ` : ''}
    </div>
  `;
}
function renderRawData(data) {
  if (!data || typeof data !== 'object' || !Object.keys(data).length) return '';
  return `
    <details class="raw-data">
      <summary>原始事件参数</summary>
      <pre>${esc(JSON.stringify(data, null, 2))}</pre>
    </details>
  `;
}

async function inspectNode(nodeId, eventRow = null) {
  const eventCard = eventRow ? `
    <div class="event-card">
      <div class="event-card-head">
        <div>
          <span class="event-card-kicker">STEP EXPLAINER</span>
          <strong>${esc(eventRow.explanation?.title || eventRow.event || 'event')}</strong>
        </div>
        <span class="event-badge">${esc(eventRow.event || '')}</span>
      </div>
      <p class="event-location">${esc(eventRow.stage || '')} · ${esc(eventRow.node_label || eventRow.node || '')} · ${esc(eventRow.timestamp || '')}</p>
      ${renderExplanation(eventRow.explanation)}
      ${eventRow.data?.context_snapshot ? renderContextSnapshot(eventRow.data.context_snapshot) : ''}
      ${eventRow.data?.messages ? renderMessages(eventRow.data.messages) : ''}
      ${renderRawData(eventRow.data)}
    </div>
  ` : '';
  if (!nodeId) {
    els.nodeView.innerHTML = eventCard || '<div class="empty">这个事件没有对应节点。</div>';
    return;
  }
  try {
    const data = await fetchJSON(`/api/node?system=${encodeURIComponent(state.system)}&node=${encodeURIComponent(nodeId)}`);
    const node = data.node;
    const sources = (data.sources || []).map(source => `
      <div class="source">
        <div class="source-head"><span>${esc(source.path)}:${source.line}-${source.end_line}</span><span>${esc(source.label || '')}</span></div>
        <pre>${esc(source.code)}</pre>
      </div>
    `).join('');
    els.nodeView.innerHTML = `
      ${eventCard}
      <div class="node-card">
        <h3>${esc(node.label)}</h3>
        <p>${esc(node.sublabel || '')}</p>
        <span class="tag">${esc(node.type || '')} ${esc(node.tag || '')}</span>
      </div>
      ${sources || '<div class="empty">这个节点没有源码引用。</div>'}
    `;
  } catch (error) {
    els.nodeView.innerHTML = eventCard || `<div class="empty">${esc(error.message)}</div>`;
  }
}
function eventDataPreview(data) {
  if (!data || typeof data !== 'object') return '';
  const light = { ...data };
  delete light.context_snapshot;
  delete light.messages;
  if (light.plan) light.plan = Array.isArray(light.plan.items) ? `${light.plan.items.length} steps` : 'plan';
  const text = JSON.stringify(light, null, 2);
  return text.length > 520 ? text.slice(0, 520) + '\n…' : text;
}
function addEvent(row) {
  const previous = els.events.querySelector('.event.active');
  if (previous) previous.classList.remove('active');
  const item = document.createElement('div');
  item.className = 'event active';
  const label = row.node_label || row.node || 'unknown';
  const message = row.message || '';
  const params = eventDataPreview(row.data);
  const why = row.explanation?.why || '';
  item.innerHTML = `
    <div class="meta"><span class="kind">${esc(row.event || 'event')}</span><span>${esc(row.stage || '')}</span><span class="node">${esc(label)}</span></div>
    <div class="event-title">${esc(row.explanation?.title || row.event || '')}</div>
    <div class="msg">${esc(message)}</div>
    ${why ? `<div class="event-why">${esc(why)}</div>` : ''}
    ${params ? `<div class="params">${esc(params)}</div>` : ''}
    <div class="data">${row.tool ? 'tool=' + esc(row.tool) + ' · ' : ''}node=${esc(row.node || '-')}</div>
  `;
  item.addEventListener('click', () => {
    state.playing = false;
    renderPlayState();
    els.events.querySelectorAll('.event').forEach(node => node.classList.remove('active'));
    item.classList.add('active');
    els.activePill.textContent = `${row.explanation?.title || row.node_label || row.node} · ${row.event}`;
    inspectNode(row.node, row).catch(console.error);
  });
  els.events.prepend(item);
  while (els.events.querySelectorAll('.event').length > 90) els.events.lastElementChild.remove();
}
function stepOnce(force = false) {
  if ((!state.playing && !force) || state.cursor >= state.events.length) return;
  const row = state.events[state.cursor];
  const previous = state.cursor > 0 ? state.events[state.cursor - 1].node : '';
  markNode(row.node, previous);
  addEvent(row);
  els.activePill.textContent = `${row.explanation?.title || row.node_label || row.node} · ${row.event}`;
  els.eventCount.textContent = `${state.cursor + 1} / ${state.events.length} events`;
  inspectNode(row.node, row).catch(() => {});
  state.cursor += 1;
  updateStepIndicator();
}
async function pollTrace() {
  const requested = state.system;
  try {
    const data = await fetchJSON(`/api/trace?system=${encodeURIComponent(requested)}`);
    if (requested !== state.system) return;
    state.nodes = data.nodes || [];
    if (data.run_dir !== state.lastRun) {
      state.lastRun = data.run_dir || '';
      state.cursor = 0;
      els.events.innerHTML = '';
      els.runId.textContent = data.run_dir ? data.run_dir.split(/[\\/]/).pop() : 'no run';
    }
    if ((data.events || []).length < state.events.length) {
      state.cursor = 0;
      els.events.innerHTML = '';
    }
    state.events = data.events || [];
    if (!state.events.length) els.activePill.textContent = state.busy ? '运行中…' : '等待运行…';
    els.eventCount.textContent = `${state.cursor} / ${state.events.length} events`;
    updateStepIndicator();
  } catch (error) {
    console.warn(error);
  }
}
async function resetChat() {
  await fetchJSON('/api/reset', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ system: state.system }),
  });
  state.messages[state.system] = [];
  renderMessages();
  setStatus('idle');
  els.events.innerHTML = '<div class="empty">对话已重置。发送新问题开始新的 run。</div>';
}
function renderPlayState() {
  if (els.play) els.play.textContent = state.playing ? '❚❚' : '▶';
}
function updateStepIndicator() {
  if (els.stepIndicator) els.stepIndicator.textContent = `${state.cursor} / ${state.events.length}`;
  if (els.next) els.next.disabled = state.cursor >= state.events.length;
  if (els.prev) els.prev.disabled = state.cursor <= 0;
}
function clearDiagramMarks() {
  const doc = els.iframe.contentDocument;
  if (!doc) return;
  doc.querySelectorAll('[data-node-id]').forEach(node => node.classList.remove('studio-active', 'studio-done'));
}
function replayTo(target) {
  target = Math.max(0, Math.min(target, state.events.length));
  state.cursor = 0;
  els.events.innerHTML = '';
  clearDiagramMarks();
  const rows = state.events.slice(0, target);
  rows.forEach((row, index) => {
    markNode(row.node, index > 0 ? rows[index - 1].node : '');
    addEvent(row);
  });
  state.cursor = target;
  if (target > 0) {
    const last = rows[rows.length - 1];
    els.activePill.textContent = `${last.explanation?.title || last.node_label || last.node} · ${last.event}`;
    inspectNode(last.node, last).catch(() => {});
  }
  updateStepIndicator();
}
function prevStep() {
  state.playing = false;
  renderPlayState();
  replayTo(state.cursor - 1);
}
function nextStep() {
  state.playing = false;
  renderPlayState();
  stepOnce(true);
  updateStepIndicator();
}
function init() {
  els.tabs.forEach(tab => tab.addEventListener('click', () => switchSystem(tab.dataset.system)));
  els.form.addEventListener('submit', sendQuestion);
  els.question.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      sendQuestion(event);
    }
  });
  els.reset.addEventListener('click', () => resetChat().catch(error => setStatus('error: ' + error.message, 'error')));
  els.prev.addEventListener('click', prevStep);
  els.next.addEventListener('click', nextStep);
  els.play.addEventListener('click', () => { state.playing = !state.playing; renderPlayState(); });
  renderPlayState();
  els.iframe.addEventListener('load', () => { injectDiagramStyles(); bindNodeClicks(); });
  switchSystem('codex');
  state.timer = setInterval(stepOnce, 550);
  setInterval(pollTrace, 500);
  loadConfig().catch(console.error);
  pollTrace();
}
document.addEventListener('DOMContentLoaded', init);
