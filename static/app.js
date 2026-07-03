// URUK Trinity Console — Frontend Logic

// ═══════════ i18n ═══════════
const I18N = {
  yue: {
    'header-meta': '操作者: Cassiel_as · (53.8, -1.5, 0) · PHYSICAL_ORIGIN: 2019-06-12',
    'sidebar-title': 'Kairos',
    'tab-kairos': 'Kairos',
    'tab-vessel': 'Vessel',
    'tab-world': 'World',
    'tab-files': 'Files',
    'tab-timeline': '📜 時間線',
    'tab-skills': '🛠 Skills',
    'loading-sessions': '載入中⋯',
    'loading-kairos': '載入 Kairos⋯',
    'new-session-btn': '＋ 新對話',
    'input-placeholder': '輸入問題（可加 /firewall, /blackboxlab, /scr, /news, /sovereign trigger）...',
    'ref-summary': '📎 注入 Data Ref',
    'ref-placeholder': 'cau:010, experiment:011, theory:zuobiao...',
    'mode-summary': '🎯 Mode override',
    'mode-auto': '自動 (Dispatcher)',
    'label-placeholder': '標籤（選擇性）',
    'save-label': '儲存對話',
    'run-btn': '▶ 執行',
    'run-btn-running': '⋯ 執行中',
    'dispatch-label': '⟶ DISPATCH',
    'dispatch-mode': 'Mode:',
    'dispatch-rationale': 'Rationale:',
    'dispatch-refs': 'References:',
    'dispatch-cost': 'Cost:',
    'node-father': '聖父',
    'node-son': '聖子',
    'node-spirit': '聖靈',
    'node-council': '會議整合',
    'node-waiting': '等待中⋯',
    'council-waiting': '等待 3 節點先⋯',
    'status-ready': '就緒',
    'status-dispatching': 'Dispatcher 路由中⋯',
    'status-perspectives': '三節點並行思考中⋯',
    'status-council': '會議整合中⋯',
    'status-done': '完成',
    'status-error': '錯誤',
    'status-saved': '已儲存：',
    'no-input': '請先輸入問題',
  },
  en: {
    'header-meta': 'Operator: Cassiel_as · (53.8, -1.5, 0) · PHYSICAL_ORIGIN: 2019-06-12',
    'sidebar-title': 'Kairos',
    'tab-kairos': 'Kairos',
    'tab-vessel': 'Vessel',
    'tab-world': 'World',
    'tab-files': 'Files',
    'tab-timeline': '📜 Timeline',
    'tab-skills': '🛠 Skills',
    'loading-sessions': 'Loading⋯',
    'loading-kairos': 'Loading Kairos⋯',
    'new-session-btn': '＋ New session',
    'input-placeholder': 'Enter question (optionally with /firewall, /blackboxlab, /scr, /news, /sovereign trigger)...',
    'ref-summary': '📎 Inject data ref',
    'ref-placeholder': 'cau:010, experiment:011, theory:zuobiao...',
    'mode-summary': '🎯 Mode override',
    'mode-auto': 'Auto (Dispatcher)',
    'label-placeholder': 'Label (optional)',
    'save-label': 'Save conversation',
    'run-btn': '▶ Run',
    'run-btn-running': '⋯ Running',
    'dispatch-label': '⟶ DISPATCH',
    'dispatch-mode': 'Mode:',
    'dispatch-rationale': 'Rationale:',
    'dispatch-refs': 'References:',
    'dispatch-cost': 'Cost:',
    'node-father': 'Father',
    'node-son': 'Son',
    'node-spirit': 'Spirit',
    'node-council': 'Council',
    'node-waiting': 'Waiting⋯',
    'council-waiting': 'Waiting for 3 nodes⋯',
    'status-ready': 'Ready',
    'status-dispatching': 'Dispatcher routing⋯',
    'status-perspectives': 'Three nodes thinking in parallel⋯',
    'status-council': 'Council integrating⋯',
    'status-done': 'Done',
    'status-error': 'Error',
    'status-saved': 'Saved: ',
    'no-input': 'Please enter a question first',
  },
};

let currentLang = localStorage.getItem('uruk-lang') || 'yue';

function applyI18n() {
  const dict = I18N[currentLang];
  document.documentElement.lang = currentLang === 'yue' ? 'yue-HK' : 'en';

  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    if (dict[key]) el.textContent = dict[key];
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    const key = el.getAttribute('data-i18n-placeholder');
    if (dict[key]) el.placeholder = dict[key];
  });

  document.querySelectorAll('.lang-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.lang === currentLang);
  });
}

document.querySelectorAll('.lang-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    currentLang = btn.dataset.lang;
    localStorage.setItem('uruk-lang', currentLang);
    applyI18n();
  });
});

// ═══════════ State ═══════════
let activeRefs = new Set();
let availableRefs = {};
let nodeConfig = {};
let __lastKnowledgeHealth = null;
let __lastKnowledgeTrace = [];
// Coordinate-map viz: capture latest stage2/stage3 + input for the 3D map render
let __lastStage2 = null;
let __lastStage3 = null;
let __lastInputText = "";

// ═══════════ Init ═══════════
async function init() {
  applyI18n();
  await loadConfig();
  await loadKairosPanel();
  loadKnowledgeHealth();
  setupRefPicker();
  setupRunButton();
  // FT-2: file tree UI
  setupSidebarTabs();
  setupVesselPane();
  setupWorldPane();
  setupEditorPane();
  loadFileTree();
  // Phase 1: tool palette
  setupToolPalette();
  // Features 1-3: tool toolbar, live mode, learn pane
  setupToolToolbar();
  setupLearnPane();
}

async function loadConfig() {
  try {
    const r = await fetch('/api/config');
    const data = await r.json();
    nodeConfig = data.nodes;
    availableRefs = data.data_refs;

    // Populate node meta
    for (const [role, cfg] of Object.entries(data.nodes)) {
      const metaEl = document.getElementById(`meta-${role}`);
      if (metaEl) metaEl.textContent = `${cfg.provider}/${cfg.model}`;
    }
  } catch (e) {
    console.error('Failed to load config:', e);
  }
}

async function loadKnowledgeHealth() {
  try {
    const r = await fetch('/api/knowledge/health');
    if (!r.ok) throw new Error(`knowledge health ${r.status}`);
    const data = await r.json();
    renderKnowledgeHealth(data);
    document.getElementById('knowledge-panel')?.classList.add('hidden');
  } catch (e) {
    renderKnowledgeHealth({ clean: false, error: String(e) });
    document.getElementById('knowledge-panel')?.classList.add('hidden');
  }
}

function resetKnowledgePanel(options = {}) {
  const panel = document.getElementById('knowledge-panel');
  if (!panel) return;
  if (options.hide) panel.classList.add('hidden');
  else panel.classList.remove('hidden');
  const set = (id, text) => {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  };
  set('knowledge-status', 'checking');
  set('knowledge-rag-count', 'RAG --');
  set('knowledge-manifest', '--');
  set('knowledge-issues-count', '--');
  set('knowledge-cau', '--');
  set('knowledge-trace-count', '0');
  const issues = document.getElementById('knowledge-issues');
  if (issues) {
    issues.className = 'knowledge-issues';
    issues.textContent = '';
  }
  const trace = document.getElementById('knowledge-trace-list');
  if (trace) trace.innerHTML = '';
  __lastKnowledgeTrace = [];
}

function renderKnowledgeHealth(data) {
  __lastKnowledgeHealth = data || {};
  const panel = document.getElementById('knowledge-panel');
  if (!panel) return;
  panel.classList.remove('hidden');
  const health = __lastKnowledgeHealth;
  const clean = !!health.clean;
  const issues = (health.summary && health.summary.issues) || health.issues || {};
  const rag = health.rag || {};
  const cau = health.cau_structure || {};
  const issueTotal = ['P0', 'P1', 'P2', 'P3'].reduce((n, k) => n + Number(issues[k] || 0), 0);
  const set = (id, text) => {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  };
  set('knowledge-status', clean ? 'clean' : 'attention');
  set('knowledge-rag-count', `RAG ${rag.n_chunks ?? rag.chunks ?? '--'}`);
  set('knowledge-manifest', health.manifest_sha256 ? shortHash(health.manifest_sha256) : (health.error ? 'error' : 'loaded'));
  set('knowledge-issues-count', String(issueTotal));
  set('knowledge-cau', `${cau.passed ?? '--'} / ${cau.checked ?? '--'}`);
  set('knowledge-trace-count', String(__lastKnowledgeTrace.length || health.trace_count || 0));
  const issuesEl = document.getElementById('knowledge-issues');
  if (issuesEl) {
    issuesEl.className = `knowledge-issues ${clean ? 'clean' : (Number(issues.P0 || 0) ? 'fail' : 'warn')}`;
    if (health.error) {
      issuesEl.textContent = `health error: ${health.error}`;
    } else if (clean) {
      issuesEl.textContent = 'Manifest clean; RAG index and CAU structure are available.';
    } else {
      issuesEl.textContent = `Issues P0=${issues.P0 || 0}, P1=${issues.P1 || 0}, P2=${issues.P2 || 0}, P3=${issues.P3 || 0}`;
    }
  }
}

function renderKnowledgeTrace(trace) {
  __lastKnowledgeTrace = Array.isArray(trace) ? trace : [];
  const panel = document.getElementById('knowledge-panel');
  if (!panel) return;
  panel.classList.remove('hidden');
  const countEl = document.getElementById('knowledge-trace-count');
  if (countEl) countEl.textContent = String(__lastKnowledgeTrace.length);
  const list = document.getElementById('knowledge-trace-list');
  if (!list) return;
  if (__lastKnowledgeTrace.length === 0) {
    list.innerHTML = '<div class="knowledge-trace-item">No knowledge trace was used for this turn.</div>';
    return;
  }
  list.innerHTML = __lastKnowledgeTrace.slice(0, 8).map((item, idx) => {
    const source = escapeHtml(item.source || `trace_${idx + 1}`);
    const hits = Array.isArray(item.hits) ? item.hits : [];
    const docs = hits.slice(0, 5).map(h => h.doc_id || h.source_file || h.path || '').filter(Boolean);
    const docText = docs.length ? escapeHtml(docs.join(' · ')) : 'no document hits';
    return `<div class="knowledge-trace-item"><code>${source}</code><div class="knowledge-trace-docs">${docText}</div></div>`;
  }).join('');
}

function shortHash(value) {
  const s = String(value || '');
  return s.length > 12 ? s.slice(0, 12) : s;
}

// ── Sidebar list helpers (v2 redesign) ──────────────────────
function _fmtRelDate(dateStr) {
  if (!dateStr) return '';
  const today = new Date().toISOString().slice(0,10);
  const yest  = new Date(Date.now()-86400000).toISOString().slice(0,10);
  if (dateStr.startsWith(today)) return '今天 ' + (dateStr.slice(11,16) || '');
  if (dateStr.startsWith(yest))  return '昨天 ' + (dateStr.slice(11,16) || '');
  return dateStr.slice(0,10);
}
function _modeBadge(mode) {
  const M = {firewall:['m-firewall','防火牆'],blackboxlab:['m-blackbox','黑盒'],
    blackbox:['m-blackbox','黑盒'],scr:['m-scr','SCR'],news:['m-news','新聞'],
    sovereign:['m-sovereign','主權'],auto:['m-auto','自動']};
  const [c,l] = M[mode]||['m-auto',mode||'自動'];
  return `<span class="mode-badge ${c}">${l}</span>`;
}
function _verdictBadge(verdict, vetoType) {
  if (vetoType) return `<span class="verdict-badge v-veto">🚨 Veto</span>`;
  if (verdict==='consensus') return `<span class="verdict-badge v-consensus">共識</span>`;
  if (verdict==='interrupt') return `<span class="verdict-badge v-interrupt">中斷</span>`;
  if (verdict==='veto')      return `<span class="verdict-badge v-veto">🚨 Veto</span>`;
  return '';
}
function _skillCategory(name) {
  const n = (name||'').toLowerCase();
  if (/firewall|blackbox|scr|news|sovereign|kairos|uruk|relay/.test(n)) return 'protocol';
  if (/screenshot|ocr|audio|speak|listen|transcribe|clipboard|read_excel|watch|play_sound|wait_for|fetch|search|arxiv|reddit|^hn$|rss|webpage|pdf/.test(n)) return 'tool';
  if (/docx|xlsx|pptx|pdf_out/.test(n)) return 'output';
  return 'user';
}
const _skillDotClass = {protocol:'sd-protocol',tool:'sd-tool',output:'sd-output',user:'sd-user'};
const _skillGroupLabel = {protocol:'協議',tool:'工具',output:'輸出',user:'自定義'};

async function loadKairosPanel() {
  const list = document.getElementById('kairos-memory-list');
  if (!list) return;
  list.innerHTML = `<div class="empty">${I18N[currentLang]['loading-kairos'] || '載入 Kairos⋯'}</div>`;
  try {
    const r = await fetch('/api/files/tree');
    if (!r.ok) throw new Error(`tree fetch ${r.status}`);
    const tree = await r.json();
    const files = [];
    for (const layer of ['canonical', 'personal', 'config', 'prompts']) {
      const bucket = tree[layer];
      if (!bucket) continue;
      for (const f of bucket.files || []) files.push(f);
    }
    renderKairosPanel(files);
  } catch (e) {
    list.innerHTML = `<div class="empty error">Kairos 載入失敗：${escapeHtml(e.message)}</div>`;
  }
}

function renderKairosPanel(files) {
  const list = document.getElementById('kairos-memory-list');
  if (!list) return;

  const byPath = new Map(files.map(f => [f.path, f]));
  const required = [
    {
      path: 'data/core/KAIROS_CORE.md',
      title: 'Core Anchor',
      tag: 'always',
      desc: '不可自動改寫；物理錨點同 carrier boundary。',
    },
    {
      path: 'data/kairos/KAIROS_ACTIVE.md',
      title: 'Active Memory',
      tag: 'current',
      desc: '真正 Kairos current memory；短、高密度、operator-reviewed。',
    },
    {
      path: 'data/kairos/KAIROS_ARCHIVE_INDEX.md',
      title: 'Archive Index',
      tag: 'map',
      desc: '查長期 archive 前先讀；避免 preload 舊 log。',
    },
  ].map(item => ({ ...item, file: byPath.get(item.path) })).filter(item => item.file);

  const proposals = files
    .filter(f => f.path.startsWith('data/kairos/_proposed/') && f.path.endsWith('.md'))
    .sort((a, b) => String(b.mtime || '').localeCompare(String(a.mtime || '')));

  const archives = files
    .filter(f => /^data\/kairos\/KAIROS_LOG_.*\.md$/.test(f.path))
    .sort((a, b) => a.path.localeCompare(b.path));

  const docs = files
    .filter(f => f.path === 'data/kairos/README.md' || f.path === 'data/kairos/_rejected/README.md')
    .sort((a, b) => a.path.localeCompare(b.path));

  const parts = [];
  parts.push(`<div class="kairos-panel-note">Kairos = 因果壓縮記憶。普通對話喺「時間線」；呢度只放 active memory、proposal 同 archive。</div>`);
  parts.push(renderKairosGroup('Active', required, item => renderKairosCard({
    path: item.path,
    title: item.title,
    tag: item.tag,
    desc: item.desc,
    mtime: item.file.mtime,
    size: item.file.size,
  })));
  parts.push(renderKairosGroup('Proposals', proposals, f => renderKairosCard({
    path: f.path,
    title: f.path.split('/').pop(),
    tag: 'pending',
    desc: '自動 audit 候選；未經 operator review，唔係 canonical memory。',
    mtime: f.mtime,
    size: f.size,
  }), '暫時冇 pending Kairos proposal'));
  parts.push(renderKairosGroup('Archives', archives, f => renderKairosCard({
    path: f.path,
    title: f.path.split('/').pop(),
    tag: 'query-only',
    desc: '歷史 archive；需要 continuity 先查，唔預設載入。',
    mtime: f.mtime,
    size: f.size,
  })));
  if (docs.length) {
    parts.push(renderKairosGroup('Docs', docs, f => renderKairosCard({
      path: f.path,
      title: f.path.split('/').pop(),
      tag: 'doc',
      desc: 'Kairos 目錄規則說明。',
      mtime: f.mtime,
      size: f.size,
    })));
  }

  list.innerHTML = parts.join('');
  list.querySelectorAll('.kairos-card').forEach(card => {
    card.addEventListener('click', () => {
      list.querySelectorAll('.kairos-card.active').forEach(el => el.classList.remove('active'));
      card.classList.add('active');
      openFile(card.dataset.path, { keepTab: true });
    });
  });
}

function renderKairosGroup(title, items, renderItem, emptyText = '冇資料') {
  const body = items.length
    ? items.map(renderItem).join('')
    : `<div class="kairos-empty">${escapeHtml(emptyText)}</div>`;
  return `
    <section class="kairos-group">
      <div class="kairos-group-title">${escapeHtml(title)} <span>${items.length}</span></div>
      ${body}
    </section>
  `;
}

function renderKairosCard({ path, title, tag, desc, mtime, size }) {
  const sizeText = typeof size === 'number' ? `${Math.max(1, Math.round(size / 1024))}KB` : '';
  const dateText = mtime ? _fmtRelDate(mtime) : '';
  return `
    <div class="kairos-card" data-path="${escapeHtml(path)}" title="${escapeHtml(path)}">
      <div class="kairos-card-top">
        <span class="kairos-card-title">${escapeHtml(title)}</span>
        <span class="kairos-card-tag">${escapeHtml(tag)}</span>
      </div>
      <div class="kairos-card-desc">${escapeHtml(desc)}</div>
      <div class="kairos-card-meta">${escapeHtml([sizeText, dateText].filter(Boolean).join(' · '))}</div>
    </div>
  `;
}

async function loadSessions() {
  try {
    const r = await fetch('/api/sessions');
    const sessions = await r.json();
    const list = document.getElementById('session-list');
    if (!list) return;
    if (sessions.length === 0) {
      list.innerHTML = `<div class="empty">${I18N[currentLang]['loading-sessions'].replace('⋯', '')}</div>`;
      return;
    }
    list.innerHTML = sessions.map(s => {
      const mode = s.pipeline_mode || s.selected_modes?.[0] || 'auto';
      const epIcon = s.episode_available
        ? `<button class="si-btn episode-btn" data-filename="${escapeHtml(s.filename)}" title="Episode replay"><i class="ti ti-bolt"></i></button>`
        : '';
      return `
        <div class="session-item-v2" data-filename="${escapeHtml(s.filename)}">
          <div class="si-label">${escapeHtml(s.label || s.filename)}</div>
          <div class="si-row">
            ${_modeBadge(mode)}
            <span class="si-date">${_fmtRelDate(s.date || s.timestamp || '')}</span>
            <div class="si-actions">
              ${epIcon}
              <button class="si-btn resume-btn" data-filename="${escapeHtml(s.filename)}" title="繼續"><i class="ti ti-player-play"></i></button>
              <button class="si-btn trash-btn" data-filename="${escapeHtml(s.filename)}" title="刪除"><i class="ti ti-trash"></i></button>
            </div>
          </div>
        </div>
      `;
    }).join('');
    list.querySelectorAll('.session-item-v2').forEach(el => {
      el.addEventListener('click', () => loadSession(el.dataset.filename));
    });
    list.querySelectorAll('.resume-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        resumeFromArchivedFile(btn.dataset.filename, null);
      });
    });
    list.querySelectorAll('.episode-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        loadSession(btn.dataset.filename, { focusEpisode: true });
      });
    });
    list.querySelectorAll('.trash-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const fn = btn.dataset.filename;
        if (!confirm(`確定刪除呢條記錄？\n\n${fn}\n\n（會 move 去 data/_conversation_history_trash/，可回滾）`)) return;
        trashSession(fn, btn);
      });
    });
  } catch (e) {
    console.error('Failed to load sessions:', e);
  }
}

// ═══════════════════════════════════════════════════════════════
// v8.13 D5 — Unified timeline tab (all turns across all saved files)
// ═══════════════════════════════════════════════════════════════
let __timelineData = [];   // cached server response

async function loadTimeline() {
  const listEl = document.getElementById('timeline-list');
  if (!listEl) return;
  listEl.innerHTML = '<div class="empty">載入中⋯</div>';
  try {
    const r = await fetch('/api/threads/timeline');
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    __timelineData = await r.json();
    renderTimeline();
  } catch (e) {
    listEl.innerHTML = `<div class="empty">Error: ${escapeHtml(e.message)}</div>`;
  }
}

function renderTimeline() {
  const listEl = document.getElementById('timeline-list');
  if (!listEl) return;
  const search = (document.getElementById('timeline-search')?.value || '').toLowerCase().trim();
  const modeFilter = document.getElementById('timeline-filter-mode')?.value || '';
  const verdictFilter = document.getElementById('timeline-filter-verdict')?.value || '';

  const filtered = __timelineData.filter(t => {
    if (modeFilter && t.pipeline_mode !== modeFilter) return false;
    if (verdictFilter && t.verdict !== verdictFilter) return false;
    if (search) {
      const haystack = `${t.input_first_line} ${t.file_label}`.toLowerCase();
      if (!haystack.includes(search)) return false;
    }
    return true;
  });

  if (filtered.length === 0) {
    listEl.innerHTML = `<div class="empty">No turns match filter (${__timelineData.length} total)</div>`;
    return;
  }

  listEl.innerHTML = filtered.map(t => {
    return `
      <div class="timeline-item-v2" data-filename="${escapeHtml(t.filename)}" data-turn-id="${t.turn_id||''}">
        <div class="tl-meta">
          <span class="tl-ts">${_fmtRelDate(t.timestamp||'')}</span>
          <span class="tl-turn">T${t.turn_id||1}</span>
          ${_modeBadge(t.pipeline_mode||'auto')}
          ${_verdictBadge(t.verdict, t.veto_type)}
        </div>
        <div class="tl-input">${escapeHtml(t.input_first_line||'') || '<em class="dim">(no input parsed)</em>'}</div>
      </div>
    `;
  }).join('');

  // Wire clicks: open archived view + scroll to turn
  listEl.querySelectorAll('.timeline-item-v2').forEach(el => {
    el.addEventListener('click', () => {
      const filename = el.dataset.filename;
      const turnId = el.dataset.turnId;
      loadSession(filename).then(() => {
        setTimeout(() => {
          const target = document.querySelector(
            `#conv-thread article.conv-turn[data-turn-id="${turnId}"]`);
          if (target) {
            target.scrollIntoView({behavior: 'smooth', block: 'start'});
            target.classList.add('section-flash');
            setTimeout(() => target.classList.remove('section-flash'), 600);
          }
        }, 150);
      });
    });
  });
}

// Wire filter controls + refresh button on DOM ready
document.addEventListener('DOMContentLoaded', () => {
  ['timeline-search', 'timeline-filter-mode', 'timeline-filter-verdict'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('input', renderTimeline);
    if (el) el.addEventListener('change', renderTimeline);
  });
  const refresh = document.getElementById('timeline-refresh');
  if (refresh) refresh.addEventListener('click', loadTimeline);
  // Lazy-load on first tab activation
  const timelineTabBtn = document.querySelector('[data-tab="timeline"]');
  if (timelineTabBtn) {
    timelineTabBtn.addEventListener('click', () => {
      if (__timelineData.length === 0) loadTimeline();
    });
  }
});

// ═══════════════════════════════════════════════════════════════
// v8.13 D1 — Parser for saved session .md files
// ═══════════════════════════════════════════════════════════════
// Handles two formats:
//   v8.11+: ## Turn N (timestamp) + **你**: + ### 聖父/聖子/聖靈/會議整合
//   Legacy: ## 原始問題 + ## 聖父/聖子/聖靈/會議整合 (single turn)
// Fallback: no recognized turn markers → entire body wrapped as 1 raw turn.

function parseSavedFileToTurns(content) {
  const result = {
    header: {},
    dispatch: {},
    node_config: {},
    turns: [],
    raw: content,
    parse_error: null,
  };
  if (!content || typeof content !== 'string') {
    result.parse_error = 'empty_content';
    return result;
  }

  // Normalize CRLF → LF (Windows-saved session files use CRLF, regex depends on LF).
  content = content.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  result.raw = content;

  // Split at FIRST `\n---\n` to separate header+dispatch from body
  const firstSep = content.indexOf('\n---\n');
  const headerBlock = firstSep >= 0 ? content.slice(0, firstSep) : content;
  const body = firstSep >= 0 ? content.slice(firstSep + 5) : '';

  // ── Parse header k:v pairs ──
  const headerLines = headerBlock.split('\n');
  let inNodeConfig = false;
  let inDispatch = false;
  let inPerModeLLMs = false;
  for (const rawLine of headerLines) {
    const line = rawLine.trimEnd();
    if (line === '') {
      inNodeConfig = inDispatch = inPerModeLLMs = false;
      continue;
    }
    // Block headers
    if (line === 'NODE_CONFIG:') { inNodeConfig = true; inDispatch = false; inPerModeLLMs = false; continue; }
    if (line === 'DISPATCH:')    { inDispatch = true;   inNodeConfig = false; inPerModeLLMs = false; continue; }
    if (line === 'PER_MODE_LLMS:') { inPerModeLLMs = true; inDispatch = false; inNodeConfig = false; continue; }
    // Indented entries
    if ((inNodeConfig || inDispatch || inPerModeLLMs) && (line.startsWith('  ') || line.startsWith('\t'))) {
      const kv = line.trim();
      const colonIdx = kv.indexOf(':');
      if (colonIdx > 0) {
        const k = kv.slice(0, colonIdx).trim();
        const v = kv.slice(colonIdx + 1).trim();
        if (inNodeConfig) result.node_config[k] = v;
        else if (inDispatch) result.dispatch[k] = v;
        else if (inPerModeLLMs) {
          result.header.per_mode_llms = result.header.per_mode_llms || {};
          result.header.per_mode_llms[k] = v;
        }
      }
      continue;
    }
    // Top-level header k:v
    if (line.startsWith('# KAIROS_TRINITY_RECORD:')) {
      result.header.label = line.replace('# KAIROS_TRINITY_RECORD:', '').trim();
      continue;
    }
    const colonIdx = line.indexOf(':');
    if (colonIdx > 0) {
      const k = line.slice(0, colonIdx).trim();
      const v = line.slice(colonIdx + 1).trim();
      // Skip SPIRIT_INTERRUPT_HISTORY block lines (start with [N])
      if (k.startsWith('  [') || k.startsWith('[')) continue;
      result.header[k] = v;
    }
  }

  // ── Parse body turns ──
  // v8.11+: split at "## Turn N"
  // Legacy: split at "## 原始問題"
  const v811Pattern = /^## Turn (\d+)(?:\s*\(([^)]+)\))?\s*$/gm;
  const v811Matches = [...body.matchAll(v811Pattern)];

  if (v811Matches.length > 0) {
    // v8.11+ multi-turn or single-turn-v8.11 (TURN_COUNT >= 1)
    for (let i = 0; i < v811Matches.length; i++) {
      const m = v811Matches[i];
      const turnStart = m.index + m[0].length;
      const turnEnd = (i + 1 < v811Matches.length) ? v811Matches[i + 1].index : body.length;
      const turnBody = body.slice(turnStart, turnEnd).trim();
      const turn_id = parseInt(m[1], 10);
      const timestamp_or_marker = (m[2] || '').trim();   // e.g. "2026-05-18 14:30" or "current"
      result.turns.push(_extractTurnSections(turnBody, turn_id, timestamp_or_marker));
    }
  } else {
    // Legacy single-turn — look for "## 原始問題" then 4 voice sections
    const legacyMatch = body.match(/^## 原始問題\s*\n([\s\S]*?)(?=\n## |$)/m);
    if (legacyMatch) {
      const input = legacyMatch[1].trim();
      const turn = _extractTurnSections(body, 1, '', /* legacy */ true);
      turn.input = input;
      result.turns.push(turn);
    } else {
      // Total fallback: 1 raw turn containing the entire body
      result.turns.push({
        turn_id: 1,
        timestamp: result.header.DATE || '',
        timestamp_label: '',
        input: '(raw)',
        father: '',
        son: '',
        spirit: '',
        council: body.trim(),
        raw_body: body.trim(),
      });
      result.parse_error = 'no_turn_markers';
    }
  }
  return result;
}

function _extractTurnSections(turnBody, turn_id, timestamp_label, legacyMode = false) {
  // Extract input + 4 voice sections from a single turn's body.
  // Sub-section heading: "### 聖父" (v8.11) OR "## 聖父" (legacy)
  const headingRegex = legacyMode
    ? /^## (聖父|聖子|聖靈|會議整合|原始問題)(?:[（(][^)）]*[)）])?\s*\n/gm
    : /^### (聖父|聖子|聖靈|會議整合|會議)(?:[（(][^)）]*[)）])?\s*\n/gm;

  // Input: "**你**: ..." (v8.11) — captured before first sub-heading
  let input = '';
  const inputMatch = turnBody.match(/^\*\*你\*\*:\s*(.+?)(?=\n###|\n## |$)/ms);
  if (inputMatch) input = inputMatch[1].trim();

  const headingMatches = [...turnBody.matchAll(headingRegex)];
  const sections = { father: '', son: '', spirit: '', council: '' };
  for (let i = 0; i < headingMatches.length; i++) {
    const hm = headingMatches[i];
    const name = hm[1];
    const start = hm.index + hm[0].length;
    const end = (i + 1 < headingMatches.length) ? headingMatches[i + 1].index : turnBody.length;
    let secText = turnBody.slice(start, end).trim();
    // Strip trailing "*(0,0,0).*" marker
    secText = secText.replace(/\*\(0,0,0\)\.\*\s*$/, '').trim();
    // Strip trailing horizontal rule "---"
    secText = secText.replace(/\n---\s*$/, '').trim();
    if (name === '聖父') sections.father = secText;
    else if (name === '聖子') sections.son = secText;
    else if (name === '聖靈') sections.spirit = secText;
    else if (name === '會議整合' || name === '會議') sections.council = secText;
  }

  return {
    turn_id,
    timestamp: timestamp_label === 'current' ? '' : timestamp_label,
    timestamp_label,
    input,
    ...sections,
  };
}

async function loadSession(filename, options = {}) {
  try {
    // v8.21 UX — commit pending snapshot before swapping main view to
    // archived render (otherwise the workspace turn would be lost).
    if (window.__pendingSnapshot) _commitPendingSnapshot();
    const r = await fetch(`/api/session/${encodeURIComponent(filename)}`);
    if (!r.ok) {
      console.error(`session fetch failed ${r.status} for ${filename}`);
      return;
    }
    const data = await r.json();
    // v8.13 D2 — render archived file as thread (replaces raw dump into council panel)
    renderArchivedAsThread(filename, data.content);
    loadEpisodeReplay(filename, options);
    // v8.33 — full-pane overlay mode so archived view covers entire main-column
    document.getElementById('main-column')?.classList.add('archived-open');
    document.querySelectorAll('.session-item-v2').forEach(el => el.classList.remove('active'));
    document.querySelector(`[data-filename="${filename}"]`)?.classList.add('active');
  } catch (e) {
    console.error('Failed to load session:', e);
  }
}

// v8.33 — soft-delete session (move to trash). On success, remove DOM card.
async function trashSession(filename, btnEl) {
  try {
    const r = await fetch(`/api/session/${encodeURIComponent(filename)}/trash`, {method: 'POST'});
    if (!r.ok) {
      const errText = await r.text().catch(() => `HTTP ${r.status}`);
      alert(`刪除失敗: ${errText}`);
      return;
    }
    // If currently viewing this session, close the archived view
    const main = document.getElementById('main-column');
    if (main?.classList.contains('archived-open')) {
      const active = document.querySelector(`.session-item-v2.active[data-filename="${CSS.escape(filename)}"]`);
      if (active) closeArchivedView();
    }
    // Remove card from sidebar
    const card = btnEl?.closest('.session-item-v2');
    if (card) card.remove();
    // If list now empty, show placeholder
    const list = document.getElementById('session-list');
    if (list && !list.querySelector('.session-item-v2')) {
      list.innerHTML = '<div class="empty">冇對話記錄</div>';
    }
  } catch (e) {
    alert(`刪除錯誤: ${e.message}`);
  }
}

// v8.33 — close archived viewer + return to live workspace
function closeArchivedView() {
  const main = document.getElementById('main-column');
  if (!main) return;
  main.classList.remove('archived-open');
  const thread = document.getElementById('conv-thread');
  if (thread) thread.innerHTML = '';
  // Re-show live workspace shell (grid/dispatch were hidden by renderArchivedAsThread)
  const grid = document.getElementById('nodes-grid');
  if (grid) grid.classList.remove('archived-view', 'single-stage-output', 'multi-mode-hidden');
  document.getElementById('dispatch-row')?.classList.remove('multi-mode-hidden');
  document.querySelectorAll('.session-item-v2').forEach(el => el.classList.remove('active'));
}

// ═══════════════════════════════════════════════════════════════
// v8.13 D2 — Archived view: render saved session file as #conv-thread
// ═══════════════════════════════════════════════════════════════

function renderArchivedAsThread(filename, content) {
  destroyTabs();
  // Reset main DOM to neutral state (no archived-view class, no live workspace)
  const grid = document.getElementById('nodes-grid');
  grid.classList.remove('archived-view', 'single-stage-output');
  grid.classList.add('multi-mode-hidden');   // hide the live 4-panel grid in archived view
  document.getElementById('dispatch-row').classList.add('hidden', 'multi-mode-hidden');
  const echo = document.getElementById('workspace-input-echo');
  if (echo) { echo.innerHTML = ''; echo.classList.add('hidden'); }

  const parsed = parseSavedFileToTurns(content);

  // Clear conv-thread + reset history so the archived turns own the thread
  const thread = document.getElementById('conv-thread');
  if (!thread) return;
  thread.innerHTML = '';

  // v8.33 — sticky close-bar at top of fullscreen archived viewer
  const closeBar = document.createElement('div');
  closeBar.className = 'archived-close-bar';
  closeBar.innerHTML =
      `<span class="archived-close-label">📂 ${escapeHtml(filename)}</span>`
    + `<button class="archived-close-btn" type="button" title="返回工作區 (close archived view)">× 關閉</button>`;
  closeBar.querySelector('.archived-close-btn').addEventListener('click', closeArchivedView);
  thread.appendChild(closeBar);

  // Add archived-view banner
  const banner = document.createElement('div');
  banner.className = 'conv-thread-banner archived-banner';
  const label = parsed.header.label || filename;
  const pipelineMode = parsed.header.PIPELINE_MODE || 'auto';
  const verdict = (parsed.header.COUNCIL_VERDICT || '').toLowerCase();
  const turnCount = parsed.turns.length;
  banner.innerHTML =
      `<span class="conv-banner-icon">📂</span>`
    + `<span class="conv-banner-text">Archived: <b>${escapeHtml(label)}</b> · `
    +   `<code>${escapeHtml(pipelineMode)}</code> · ${turnCount} turn(s)`
    + (verdict ? ` · <span class="conv-turn-verdict verdict-${escapeHtml(verdict)}">${escapeHtml(verdict)}</span>` : '')
    +   `</span>`
    + `<span class="conv-banner-spacer"></span>`
    + `<button class="conv-banner-btn" data-action="resume" data-filename="${escapeHtml(filename)}" title="Continue this conversation in current session">▶ 繼續</button>`;
  banner.querySelector('[data-action="resume"]').addEventListener('click', (e) => {
    e.stopPropagation();
    resumeFromArchivedFile(filename, parsed);
  });
  thread.appendChild(banner);

  const episodePanel = document.createElement('details');
  episodePanel.id = 'episode-replay-panel';
  episodePanel.className = 'episode-replay-panel';
  episodePanel.open = true;
  episodePanel.innerHTML = '<summary>Episode Replay</summary><div class="episode-replay-body">Loading episode package...</div>';
  thread.appendChild(episodePanel);

  // Render each turn as a collapsed article (same shape as in-session thread)
  parsed.turns.forEach(turn => _renderArchivedTurn(thread, turn, parsed));

  // Auto-scroll thread top into view
  const mainCol = document.getElementById('main-column');
  if (mainCol) mainCol.scrollTop = 0;
  setStatus(`📂 Archived: ${label} · ${turnCount} turn(s)`);
}

async function loadEpisodeReplay(filename, options = {}) {
  const panel = document.getElementById('episode-replay-panel');
  if (!panel) return;
  try {
    const r = await fetch(`/api/session/${encodeURIComponent(filename)}/episode`);
    if (r.status === 404) {
      panel.innerHTML = '<summary>Episode Replay</summary><div class="episode-replay-body">No harness episode package found for this session.</div>';
      return;
    }
    if (!r.ok) throw new Error(`episode fetch ${r.status}`);
    const data = await r.json();
    renderEpisodeReplay(data, options);
  } catch (e) {
    panel.innerHTML = `<summary>Episode Replay</summary><div class="episode-replay-body">Episode load failed: ${escapeHtml(String(e))}</div>`;
  }
}

function renderEpisodeReplay(data, options = {}) {
  const panel = document.getElementById('episode-replay-panel');
  if (!panel) return;
  const ep = data.episode || {};
  const run = ep.run || {};
  const knowledge = ((ep.context || {}).knowledge || {});
  const health = knowledge.health || {};
  const trace = Array.isArray(knowledge.trace) ? knowledge.trace : [];
  const validators = ep.validators || {};
  const voices = ep.voices || {};
  const outputAudit = validators.output_density_audit || validators.density_audit || {};
  const coordOutputEval = validators.coordinate_output_eval || validators.coordinate_eval || {};
  const councilDecision = validators.council_decision || {};
  const modeValue = run.pipeline_mode || (Array.isArray(run.selected_modes) ? run.selected_modes.join('+') : '--');
  const grid = [
    ['Episode', ep.episode_id || '(unknown)'],
    ['Schema', ep.schema_version || '--'],
    ['Mode', modeValue || '--'],
    ['Knowledge', health.clean === false ? 'attention' : 'clean'],
    ['Manifest', shortHash(knowledge.manifest_sha256 || '') || '--'],
    ['RAG', shortHash(knowledge.rag_manifest_sha256 || '') || '--'],
    ['Trace', String(trace.length)],
    ['Output Audit', outputAudit.density || (outputAudit.audit_ran ? 'ran' : '--')],
    ['Coord Output', coordOutputEval.active ? (coordOutputEval.score ?? 'active') : '--'],
  ].map(([label, value]) =>
    `<div class="episode-replay-metric"><span>${escapeHtml(label)}</span><strong title="${escapeHtml(String(value))}">${escapeHtml(String(value))}</strong></div>`
  ).join('');
  const traceRows = trace.slice(0, 8).map((item, idx) => {
    const hits = Array.isArray(item.hits) ? item.hits : [];
    const docs = hits.slice(0, 4).map(h => h.doc_id || h.source_file || '').filter(Boolean).join(' · ');
    return `<div class="episode-replay-row">${idx + 1}. ${escapeHtml(item.source || 'trace')} → ${escapeHtml(docs || 'no docs')}</div>`;
  }).join('') || '<div class="episode-replay-row">No knowledge trace recorded.</div>';
  const voiceRows = ['father', 'son', 'spirit', 'council'].map(role => {
    const v = voices[role] || {};
    return `<div class="episode-replay-row">${role}: ${escapeHtml(shortHash(v.sha256 || ''))}</div>`;
  }).join('');
  panel.innerHTML = `
    <summary>Episode Replay · ${escapeHtml(ep.episode_id || data.filename || '')}</summary>
    <div class="episode-replay-body">
      <div class="episode-replay-grid">${grid}</div>
      <div class="episode-replay-section">
        <h4>Run</h4>
        <div class="episode-replay-row">created_at: ${escapeHtml(ep.created_at || '')}</div>
        <div class="episode-replay-row">input_sha256: ${escapeHtml(shortHash(run.input_sha256 || ''))}</div>
        <div class="episode-replay-row">verdict: ${escapeHtml(councilDecision.verdict || '--')}</div>
      </div>
      <div class="episode-replay-section">
        <h4>Knowledge Trace</h4>
        <div class="episode-replay-list">${traceRows}</div>
      </div>
      <div class="episode-replay-section">
        <h4>Voice Hashes</h4>
        <div class="episode-replay-list">${voiceRows}</div>
      </div>
    </div>`;
  panel.open = true;
  if (options.focusEpisode) {
    setTimeout(() => panel.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50);
  }
}

function _renderArchivedTurn(thread, turn, parsed) {
  const article = document.createElement('article');
  article.className = 'conv-turn conv-turn-archived';
  article.dataset.turnId = String(turn.turn_id);

  // Pull header-level chips for the LATEST turn (v8.11 only writes them once globally)
  const isLatest = turn === parsed.turns[parsed.turns.length - 1];
  const header = document.createElement('header');
  header.className = 'conv-turn-header';

  let verdictBadge = '';
  let veto = '';
  let spiritChip = '';
  if (isLatest && parsed.header) {
    const verdict = (parsed.header.COUNCIL_VERDICT || '').toLowerCase();
    if (verdict) {
      verdictBadge = `<span class="conv-turn-verdict verdict-${escapeHtml(verdict)}">${escapeHtml(verdict)}</span>`;
    }
    const vetoType = parsed.header.SON_VETO_TYPE;
    if (vetoType && vetoType !== 'none') {
      veto = `<span class="conv-turn-verdict verdict-veto">🚨 ${escapeHtml(vetoType)}</span>`;
    }
    const spiritMode = parsed.header.SPIRIT_TRIGGER_MODE;
    if (spiritMode && spiritMode !== 'NONE') {
      spiritChip = `<span class="conv-turn-verdict">⚡ ${escapeHtml(spiritMode)}</span>`;
    }
  }

  const ts = turn.timestamp_label || turn.timestamp || '';
  header.innerHTML =
      `<span class="conv-turn-num">Turn ${turn.turn_id}</span>`
    + (ts ? `<span class="conv-turn-ts">${escapeHtml(ts)}</span>` : '')
    + verdictBadge + veto + spiritChip
    + `<span class="conv-turn-spacer"></span>`
    + `<button class="conv-turn-toggle" data-action="toggle" title="Expand / collapse">▶</button>`;
  header.querySelector('[data-action="toggle"]').addEventListener('click', () => {
    article.classList.toggle('collapsed');
    const btn = header.querySelector('[data-action="toggle"]');
    if (btn) btn.textContent = article.classList.contains('collapsed') ? '▶' : '▼';
  });
  article.appendChild(header);

  if (turn.input) {
    const inputDiv = document.createElement('div');
    inputDiv.className = 'conv-turn-input';
    inputDiv.textContent = `你: ${turn.input}`;
    article.appendChild(inputDiv);
  }

  const body = document.createElement('div');
  body.className = 'conv-turn-body conv-turn-body-archived';
  // 4-panel grid render for the turn's voices
  if (turn.father || turn.son || turn.spirit || turn.council) {
    body.appendChild(_makeArchivedPanel('聖父', turn.father));
    body.appendChild(_makeArchivedPanel('聖子', turn.son));
    body.appendChild(_makeArchivedPanel('聖靈', turn.spirit));
    body.appendChild(_makeArchivedPanel('會議整合', turn.council));
  } else if (turn.raw_body) {
    const pre = document.createElement('pre');
    pre.className = 'conv-turn-raw';
    pre.textContent = turn.raw_body;
    body.appendChild(pre);
  }
  article.appendChild(body);
  article.classList.add('collapsed');
  thread.appendChild(article);
}

function _makeArchivedPanel(name, text) {
  const panel = document.createElement('div');
  panel.className = `archived-panel archived-panel-${escapeHtml(name)}`;
  panel.innerHTML = `<div class="archived-panel-header">${escapeHtml(name)}</div>`;
  const out = document.createElement('div');
  out.className = 'archived-panel-output';
  out.textContent = text || '(empty)';
  panel.appendChild(out);
  return panel;
}

// ═══════════════════════════════════════════════════════════════
// v8.13 D3/D4 — Resume conversation from archived file
// ═══════════════════════════════════════════════════════════════
// State: window.__resumeMode = { filename, original_header } | null

window.__resumeMode = null;

function resumeFromArchivedFile(filename, parsed) {
  // Re-parse if not given (for direct sidebar button invocation)
  if (!parsed) {
    fetch(`/api/session/${filename}`).then(r => r.json()).then(data => {
      resumeFromArchivedFile(filename, parseSavedFileToTurns(data.content));
    });
    return;
  }
  // Populate __convHistory with parsed turns (compressed shape)
  __convHistory.turns = parsed.turns.map(t => ({
    turn_id: t.turn_id,
    timestamp: t.timestamp || parsed.header.DATE || new Date().toISOString(),
    input: t.input,
    modes: {
      _default: {
        council: t.council || '',
        verdict: (parsed.header.COUNCIL_VERDICT || 'consensus').toLowerCase(),
        veto_type: parsed.header.SON_VETO_TYPE || 'none',
      },
    },
  }));
  __convHistory.truncation_count = 0;
  __currentTurn = null;

  // Mark resume mode
  window.__resumeMode = {
    filename,
    label: parsed.header.label || filename,
    original_header: parsed.header,
  };

  // Re-render thread (same view, but now turns are live history not just archived)
  const thread = document.getElementById('conv-thread');
  if (thread) {
    thread.innerHTML = '';
    // Banner: resume mode (replaces archived banner)
    const banner = document.createElement('div');
    banner.className = 'conv-thread-banner resume-banner';
    banner.innerHTML =
        `<span class="conv-banner-icon">📂</span>`
      + `<span class="conv-banner-text">繼續對話: <b>${escapeHtml(window.__resumeMode.label)}</b> · `
      +   `${parsed.turns.length} prior turn(s) · 新 turn 會 append + save 返同一 file</span>`
      + `<span class="conv-banner-spacer"></span>`
      + `<button class="conv-banner-btn" data-action="exit-resume">退出 resume</button>`;
    banner.querySelector('[data-action="exit-resume"]').addEventListener('click', () => {
      window.__resumeMode = null;
      clearConvHistory();
      thread.innerHTML = '';
      setStatus('Exited resume mode. Fresh session.');
    });
    thread.appendChild(banner);
    parsed.turns.forEach(turn => _renderArchivedTurn(thread, turn, parsed));
  }
  // Show legacy main DOM so new turn can stream into it
  document.getElementById('nodes-grid').classList.remove('multi-mode-hidden');
  document.getElementById('dispatch-row').classList.remove('multi-mode-hidden');
  // Don't unhide dispatch-row (it stays hidden until next runTrinity)
  document.getElementById('dispatch-row').classList.add('hidden');

  setStatus(`📂 Resume mode: ${window.__resumeMode.label} · ${parsed.turns.length} prior turn(s) loaded`);
  document.getElementById('user-input')?.focus();
}

document.getElementById('new-session-btn').addEventListener('click', () => {
  // v8.21 UX — commit pending snapshot before tearing down the workspace
  // so the last turn lands in #conv-thread (or in the now-cleared thread
  // if "+ 新對話" is also clearing history below).
  if (window.__pendingSnapshot) _commitPendingSnapshot();
  // Clear all panels
  ['father', 'son', 'spirit', 'council'].forEach(role => {
    const out = document.getElementById(`output-${role}`);
    out.innerHTML = `<div class="placeholder">${I18N[currentLang][role === 'council' ? 'council-waiting' : 'node-waiting']}</div>`;
    out.classList.remove('streaming', 'error');
  });
  document.getElementById('dispatch-row').classList.add('hidden');
  // Restore 4-panel Trinity layout (clear archived-view + multi-mode-hidden modifiers)
  const grid = document.getElementById('nodes-grid');
  grid.classList.remove('archived-view', 'multi-mode-hidden');
  document.getElementById('dispatch-row').classList.remove('multi-mode-hidden');
  document.getElementById('user-input').value = '';
  document.getElementById('user-input').focus();
  document.querySelectorAll('.session-item-v2').forEach(el => el.classList.remove('active'));
  // v8.11 — P4: also clear in-session conversation history + thread DOM
  clearConvHistory();
  // Hide workspace input echo
  const echo = document.getElementById('workspace-input-echo');
  if (echo) { echo.innerHTML = ''; echo.classList.add('hidden'); }
  // v8.13 D4: exit resume mode if active
  window.__resumeMode = null;
});

// ═══════════ Ref picker ═══════════
function setupRefPicker() {
  const input = document.getElementById('ref-input');
  const suggestions = document.getElementById('ref-suggestions');

  input.addEventListener('input', () => {
    const q = input.value.toLowerCase().trim();
    if (!q) {
      suggestions.innerHTML = '';
      return;
    }
    // Build suggestion list
    const all = [];
    for (const [folder, files] of Object.entries(availableRefs)) {
      const ns = folderToNamespace(folder);
      for (const f of files) {
        const name = simplifyFilename(f, folder);
        all.push({ ref: `${ns}:${name}`, file: f });
      }
    }
    const matches = all.filter(s => s.ref.toLowerCase().includes(q)).slice(0, 20);
    suggestions.innerHTML = matches.map(s => `<span class="ref-suggestion" data-ref="${s.ref}">${s.ref}</span>`).join('');
    suggestions.querySelectorAll('.ref-suggestion').forEach(el => {
      el.addEventListener('click', () => {
        addRef(el.dataset.ref);
        input.value = '';
        suggestions.innerHTML = '';
      });
    });
  });

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && input.value.trim()) {
      e.preventDefault();
      addRef(input.value.trim());
      input.value = '';
      suggestions.innerHTML = '';
    }
  });
}

function folderToNamespace(folder) {
  return {
    causal_db: 'cau',
    experiments: 'experiment',
    kairos: 'kairos',
    theory: 'theory',
    protocol: 'protocol',
    scr_examples: 'scr',
    blackbox_templates: 'blackbox',
    sovereign_tools: 'sovereign',
    prompts_archive: 'prompts',
    reference_implementations: 'impl',
    index: 'index',
  }[folder] || folder;
}

function simplifyFilename(filename, folder) {
  if (folder === 'causal_db') {
    const m = filename.match(/CAU-(\d+)/);
    return m ? m[1] : filename.replace(/\.md$/, '');
  }
  if (folder === 'experiments') {
    const m = filename.match(/EXPERIMENT_([\w-]+)/);
    return m ? m[1] : filename.replace(/\.md$/, '').replace(/_FULL$/, '');
  }
  return filename.replace(/\.md$/, '').replace(/\.txt$/, '').toLowerCase().split('_')[0];
}

function addRef(ref) {
  if (activeRefs.has(ref)) return;
  activeRefs.add(ref);
  renderActiveRefs();
}

function removeRef(ref) {
  activeRefs.delete(ref);
  renderActiveRefs();
}

function renderActiveRefs() {
  const container = document.getElementById('active-refs');
  container.innerHTML = [...activeRefs].map(r => `
    <span class="ref-tag">${r}<span class="remove" data-ref="${r}">×</span></span>
  `).join('');
  container.querySelectorAll('.remove').forEach(el => {
    el.addEventListener('click', () => removeRef(el.dataset.ref));
  });
}

// ═══════════ Smart Auto mutual exclusion ═══════════
function _setupSmartAutoExclusion() {
  const saChk = document.getElementById('smart-auto-mode-chk');
  if (!saChk) return;

  const agentChk = document.getElementById('agent-chat-mode-chk');
  const exclusiveChks = [saChk, agentChk].filter(Boolean);

  // When smart_auto or agent_chat checked → uncheck all other modes
  exclusiveChks.forEach(excl => {
    excl.addEventListener('change', () => {
      if (excl.checked) {
        document.querySelectorAll('input[name="mode"]').forEach(chk => {
          if (chk !== excl) chk.checked = false;
        });
      }
    });
  });

  // When any other mode is checked → uncheck exclusive modes
  document.querySelectorAll('input[name="mode"]').forEach(chk => {
    if (exclusiveChks.includes(chk)) return;
    chk.addEventListener('change', () => {
      if (chk.checked) exclusiveChks.forEach(e => { e.checked = false; });
    });
  });
}

// ═══════════ Run ═══════════
function setupRunButton() {
  const btn = document.getElementById('run-btn');
  const input = document.getElementById('user-input');

  _setupSmartAutoExclusion();

  btn.addEventListener('click', runTrinity);
  input.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault();
      runTrinity();
    }
  });
  // v8.21 UX — first keystroke after `done` commits the pending snapshot
  // so the previous turn slides into #conv-thread + workspace clears for the
  // new query. Idempotent — subsequent keystrokes are no-ops.
  input.addEventListener('input', () => {
    if (window.__pendingSnapshot) _commitPendingSnapshot();
    _updateSmartAutoBadge(input.value);
  });
}

// ── Smart Auto badge: client-side routing preview (no backend call) ──
function _updateSmartAutoBadge(text) {
  const badge = document.getElementById('smart-auto-badge');
  if (!badge) return;
  const chk = document.getElementById('smart-auto-mode-chk');
  if (!chk || !chk.checked) return;

  const lower = (text || '').toLowerCase();
  const n = text.length;

  const URUK_KW = ['uruk','firewall','blackbox','trinity','kairos','八律','座標','主權','聖父','聖子','聖靈','sovereign','scr'];
  const CODE_KW = ['def ','class ','import ','function','async ','bug','debug','代碼','程式','python','javascript','sql'];

  let backend, cls;
  if (URUK_KW.some(k => lower.includes(k))) {
    backend = 'URUK protocol carrier relay'; cls = 'desktop';
  } else if (CODE_KW.some(k => lower.includes(k))) {
    backend = '💻 ollama'; cls = 'ollama';
  } else if (n < 120) {
    backend = '💻 ollama'; cls = 'ollama';
  } else if (n >= 350) {
    backend = 'URUK protocol carrier relay'; cls = 'desktop';
  } else {
    backend = '💻 ollama'; cls = 'ollama';
  }

  badge.textContent = backend + (n ? ` (${n}字)` : '');
  badge.className = 'sa-badge ' + cls;
}

// ═══════════════════════════════════════════════════════════════
// v8.11 — In-Session Conversation History tracker
// ═══════════════════════════════════════════════════════════════
// Client-driven thread state. Refresh wipes the history. No localStorage —
// ═══════════ Agent Chat (direct Planner-Executor from conversation) ═══════════

async function _runAgentChat(intent) {
  const panel  = document.getElementById('agent-chat-panel');
  const steps  = document.getElementById('agent-chat-steps');
  const status = document.getElementById('agent-chat-status');
  const btn    = document.getElementById('run-btn');

  if (panel)  panel.classList.remove('hidden');
  if (steps)  steps.innerHTML = '';
  if (status) status.textContent = '規劃中…';
  if (btn)    { btn.disabled = true; btn.textContent = '⋯ 執行中'; }

  window.__runTrinityActive = true;

  // Add user intent display
  _appendAgentStep(steps, 'plan', '🗣', intent, '用戶指令', null);

  try {
    const resp = await fetch('/api/agent/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        intent,
        planner_model: 'gemini-2.5-flash',
        planner_provider: 'gemini',
        include_screenshot: false,
        dry_run: false,
      }),
    });

    const reader = resp.body.getReader();
    const dec    = new TextDecoder();
    let buf = '';
    let planEl = null;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop();

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        let ev;
        try { ev = JSON.parse(line.slice(6)); } catch(e) { continue; }
        _handleAgentEvent(ev, steps, status);
      }
    }

    if (status) status.textContent = '✓ 完成';
  } catch (e) {
    _appendAgentStep(steps, 'fail', '✗', 'Network / Server 錯誤', e.message, null);
    if (status) status.textContent = '錯誤';
  } finally {
    window.__runTrinityActive = false;
    if (btn) { btn.disabled = false; btn.textContent = '▶ 執行'; }
  }
}

function _handleAgentEvent(ev, steps, status) {
  switch (ev.event_type) {
    case 'plan':
      _appendAgentStep(steps, 'plan', '📋',
        `計劃：${ev.goal}（${ev.step_count} 步）`,
        ev.plan?.planner_reasoning?.replace(/^\[cats:[^\]]+\]\s*/, '').slice(0, 120) || '',
        null);
      if (status) status.textContent = `執行中 (0/${ev.step_count})…`;
      break;

    case 'step_start':
      // Add a "running" step card (will be updated on step_done)
      const el = _appendAgentStep(steps, 'running', '⟳',
        ev.tool, ev.purpose?.slice(0, 80) || '', null);
      el.dataset.step = ev.step;
      break;

    case 'step_done': {
      // Find and update the running card for this step
      const running = steps.querySelector(`.agent-step.running[data-step="${ev.step}"]`);
      if (running) {
        running.classList.remove('running');
        running.classList.add(ev.ok ? 'ok' : 'fail');
        running.querySelector('.agent-step-icon').textContent = ev.ok ? '✓' : '✗';
        if (!ev.ok && ev.error) {
          const r = running.querySelector('.agent-step-result');
          if (r) r.textContent = ev.error;
        } else if (ev.ok && ev.output) {
          const preview = _agentOutputPreview(ev.tool, ev.output);
          if (preview) {
            const r = running.querySelector('.agent-step-result');
            if (r) r.textContent = preview;
          }
        }
      }
      if (status) {
        const total = steps.querySelectorAll('.agent-step[data-step]').length;
        const done  = steps.querySelectorAll('.agent-step.ok, .agent-step.fail').length;
        status.textContent = `執行中 (${done}/${total})…`;
      }
      break;
    }

    case 'done':
      if (status) status.textContent = `✓ 完成 (${ev.total_steps} 步)`;
      break;

    case 'error':
      _appendAgentStep(steps, 'fail', '✗', '執行錯誤', ev.message || '', null);
      break;
  }
}

function _appendAgentStep(container, cls, icon, tool, purpose, result) {
  if (!container) return null;
  const div = document.createElement('div');
  div.className = `agent-step ${cls}`;
  div.innerHTML = `
    <span class="agent-step-icon">${icon}</span>
    <div class="agent-step-body">
      <div class="agent-step-tool">${_esc(tool)}</div>
      ${purpose ? `<div class="agent-step-purpose">${_esc(purpose)}</div>` : ''}
      <div class="agent-step-result">${result ? _esc(result) : ''}</div>
    </div>`;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return div;
}

function _agentOutputPreview(tool, output) {
  if (!output) return null;
  if (tool === 'screenshot') return output.screenshot_b64 ? `截圖已拍 (${Math.round(output.screenshot_b64.length/1024)}KB)` : null;
  if (tool === 'read_screen_text') return output.text?.slice(0, 120);
  if (tool === 'read_file') return `已讀 ${output.path} (${output.content?.length || 0} chars)`;
  if (tool === 'write_clipboard') return `已寫入剪貼板 (${output.chars} chars)`;
  if (tool === 'read_clipboard') return output.content?.slice(0, 100);
  if (tool === 'type_text') return `已輸入: "${output.typed}"`;
  if (tool === 'press_key') return `按鍵: ${output.pressed}`;
  if (tool === 'wait') return `等待 ${output.waited_seconds}s`;
  return JSON.stringify(output).slice(0, 100);
}

function _esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// session is the lifetime of the page. Sent on every /api/stream POST as
// `in_session_history` (compressed: council text + verdict tag per mode).
//
// Truncation: when turns.length > n_turns, drop oldest; surface truncation_count
// to UI for warning chip.

window.__convHistory = {
  enabled: true,                  // false = bypass injection (Settings toggle)
  n_turns: 5,                     // ring buffer cap
  turns: [],                      // list of {turn_id, timestamp, input, modes:{...}}
  truncation_count: 0,            // turns dropped this session
};

// Current turn buffer — populated as SSE events stream; flushed to history on `done`.
window.__currentTurn = null;

function _startNewTurnBuffer(input, selectedModes, executionStrategy) {
  const turn_id = (__convHistory.turns[__convHistory.turns.length - 1]?.turn_id || 0) + 1
                 + __convHistory.truncation_count;
  __currentTurn = {
    turn_id,
    timestamp: new Date().toISOString(),
    input,
    selected_modes: selectedModes.map(s => s.mode),
    execution_strategy: executionStrategy,
    modes: {},
    knowledge_health: null,
    knowledge_trace: [],
    // Internal — used by UI thread render; not sent to server
    _ui_dom_snapshot: null,
  };
  return __currentTurn;
}

function _recordTurnEvent(eventType, data) {
  if (!__currentTurn) return;
  const mid = (data && data._mode_id) || '_default';
  if (!__currentTurn.modes[mid]) {
    __currentTurn.modes[mid] = {council: '', verdict: null, veto_type: null};
  }
  if (eventType === 'node' && data.role === 'council') {
    __currentTurn.modes[mid].council = data.output || '';
  } else if (eventType === 'council_decision') {
    __currentTurn.modes[mid].verdict = data.verdict || null;
  } else if (eventType === 'son_veto_metadata') {
    __currentTurn.modes[mid].veto_type = data.veto_type || null;
  } else if (eventType === 'direct_response') {
    // plain_llm mode lands result in council slot
    __currentTurn.modes[mid].council = data.text || '';
  } else if (eventType === 'delabel_only_done') {
    __currentTurn.modes[mid].council = JSON.stringify(data.result || {}, null, 2);
  } else if (eventType === 'meta_response') {
    __currentTurn.modes[mid].council = data.text || '';
  } else if (eventType === 'knowledge_health') {
    __currentTurn.knowledge_health = data;
  } else if (eventType === 'knowledge_trace') {
    __currentTurn.knowledge_trace = data.trace || [];
  }
}

function _finalizeTurn() {
  // v8.21 UX — Defer the DOM snapshot + workspace reset until the user starts
  // typing the NEXT query. The done event still appends to __convHistory.turns
  // (so the next /api/stream POST sees this turn in `in_session_history`), but
  // the workspace area stays visible. _commitPendingSnapshot() runs on the
  // first keystroke / new-session click / archived-view click / mode-picker
  // change / next runTrinity entry.
  if (!__currentTurn) return;
  const turnPayload = {
    turn_id: __currentTurn.turn_id,
    timestamp: __currentTurn.timestamp,
    input: __currentTurn.input,
    modes: __currentTurn.modes,
    knowledge_health: __currentTurn.knowledge_health || null,
    knowledge_trace: __currentTurn.knowledge_trace || [],
  };
  const firstModeKey = Object.keys(turnPayload.modes)[0];
  const verdict = firstModeKey ? (turnPayload.modes[firstModeKey].verdict || null) : null;
  const vetoType = firstModeKey ? (turnPayload.modes[firstModeKey].veto_type || null) : null;

  __convHistory.turns.push(turnPayload);
  while (__convHistory.turns.length > __convHistory.n_turns) {
    __convHistory.turns.shift();
    __convHistory.truncation_count++;
  }

  // Park the snapshot — workspace stays visible until commit triggers fire.
  window.__pendingSnapshot = { turnPayload, verdict, vetoType };

  __currentTurn = null;
  _updateTruncationWarning();
}

// v8.21 UX — Idempotent: safe to call repeatedly; no-op if no pending snapshot.
function _commitPendingSnapshot() {
  const pending = window.__pendingSnapshot;
  if (!pending) return false;
  window.__pendingSnapshot = null;
  try {
    _snapshotWorkspaceIntoThread(pending.turnPayload, pending.verdict, pending.vetoType);
  } catch (e) {
    console.warn('snapshot failed:', e);
  }
  _resetWorkspace();
  return true;
}

function _snapshotWorkspaceIntoThread(turnPayload, verdict, vetoType) {
  const thread = document.getElementById('conv-thread');
  if (!thread) return;
  const article = document.createElement('article');
  article.className = 'conv-turn';
  article.dataset.turnId = String(turnPayload.turn_id);

  // Header: turn # + timestamp + verdict chip + expand toggle
  const ts = (turnPayload.timestamp || '').replace('T', ' ').slice(0, 16);
  const verdictBadge = _verdictBadge(verdict, vetoType);
  const header = document.createElement('header');
  header.className = 'conv-turn-header';
  header.innerHTML =
      `<span class="conv-turn-num">Turn ${turnPayload.turn_id}</span>`
    + `<span class="conv-turn-ts">${escapeHtml(ts)}</span>`
    + verdictBadge
    + `<span class="conv-turn-spacer"></span>`
    + `<button class="conv-turn-toggle" data-action="toggle" title="Expand / collapse">▶</button>`;
  header.querySelector('[data-action="toggle"]').addEventListener('click', () => {
    article.classList.toggle('collapsed');
    const btn = header.querySelector('[data-action="toggle"]');
    if (btn) btn.textContent = article.classList.contains('collapsed') ? '▶' : '▼';
  });
  article.appendChild(header);

  // Input echo
  const inputDiv = document.createElement('div');
  inputDiv.className = 'conv-turn-input';
  inputDiv.textContent = `你: ${turnPayload.input}`;
  article.appendChild(inputDiv);

  // Body: clone workspace DOM (dispatch-row + nodes-grid + multi-mode-stack snapshots)
  const body = document.createElement('div');
  body.className = 'conv-turn-body';
  // Snapshot each workspace piece (strip IDs to avoid duplicates)
  ['dispatch-row', 'knowledge-panel', 'nodes-grid', 'multi-mode-stack'].forEach(srcId => {
    const src = document.getElementById(srcId);
    if (!src) return;
    // Skip empty multi-mode-stack
    if (srcId === 'multi-mode-stack' && src.children.length === 0) return;
    // Skip hidden dispatch-row that never received an event
    if (srcId === 'dispatch-row' && src.classList.contains('hidden')) return;
    // Skip nodes-grid if it's hidden by multi-mode
    if (srcId === 'nodes-grid' && src.classList.contains('multi-mode-hidden')) return;
    const clone = src.cloneNode(true);
    clone.removeAttribute('id');
    clone.querySelectorAll('[id]').forEach(el => el.removeAttribute('id'));
    // Strip streaming/transient classes
    clone.classList.remove('multi-mode-hidden', 'multi-mode-active', 'tab-inactive');
    clone.querySelectorAll('.streaming').forEach(el => el.classList.remove('streaming'));
    body.appendChild(clone);
  });
  article.appendChild(body);

  // Default: collapsed (just header + input echo visible)
  article.classList.add('collapsed');

  thread.appendChild(article);
  // Auto-scroll thread to keep new entry visible
  const mainCol = document.getElementById('main-column');
  if (mainCol) mainCol.scrollTop = mainCol.scrollHeight;
}

function _verdictBadge(verdict, vetoType) {
  if (!verdict || verdict === 'consensus') {
    if (vetoType && vetoType !== 'none') {
      return `<span class="conv-turn-verdict verdict-veto">🚨 ${escapeHtml(vetoType)}</span>`;
    }
    return `<span class="conv-turn-verdict verdict-consensus">🤝 consensus</span>`;
  }
  if (verdict === 'veto') return `<span class="conv-turn-verdict verdict-veto">⚖ veto</span>`;
  if (verdict === 'interrupt') return `<span class="conv-turn-verdict verdict-interrupt">⚡ interrupt</span>`;
  return `<span class="conv-turn-verdict">${escapeHtml(verdict)}</span>`;
}

function _resetWorkspace() {
  // Clear workspace for next query (does NOT clear thread)
  const echo = document.getElementById('workspace-input-echo');
  if (echo) {
    echo.innerHTML = '';
    echo.classList.add('hidden');
  }
  const dispatch = document.getElementById('dispatch-row');
  if (dispatch) {
    dispatch.classList.add('hidden');
    dispatch.querySelectorAll('[data-base-id]').forEach(el => {
      if (el.tagName === 'SPAN') el.textContent = '—';
    });
  }
  ['father', 'son', 'spirit', 'council'].forEach(role => {
    const out = document.getElementById(`output-${role}`);
    if (out) {
      out.innerHTML = `<div class="placeholder">${escapeHtml(I18N[currentLang][role === 'council' ? 'council-waiting' : 'node-waiting'] || '...')}</div>`;
      out.classList.remove('streaming', 'error', 'father-paused');
    }
  });
  resetKnowledgePanel({ hide: true });
  const toolBar = document.getElementById('tool-results-bar');
  if (toolBar) { toolBar.innerHTML = ''; toolBar.style.display = 'none'; }
  // Tear down multi-mode stack for next run (handled by next runTrinity's createSectionsForModes)
  destroySections();
}

function _buildHistoryPayload(selectedModes) {
  // v8.11 P7 — Multi-mode per-section history (Option A): each mode sees ONLY
  // turns where it was selected. Caller passes current selectedModes; we filter.
  if (!__convHistory.enabled) return [];
  if (__convHistory.turns.length === 0) return [];
  return __convHistory.turns.map(t => {
    // Mode filter happens in P7 — for P1 just pass turn as-is
    return {
      turn_id: t.turn_id,
      timestamp: t.timestamp,
      input: t.input,
      modes: t.modes,
    };
  });
}

function _updateTruncationWarning() {
  const el = document.getElementById('conv-truncation-warning');
  if (!el) return;
  if (__convHistory.truncation_count > 0) {
    el.textContent = `⚠ ${__convHistory.truncation_count} 個 turn 已 truncate（>${__convHistory.n_turns} cap）`;
    el.classList.remove('hidden');
  } else {
    el.classList.add('hidden');
  }
}

function clearConvHistory() {
  __convHistory.turns = [];
  __convHistory.truncation_count = 0;
  __currentTurn = null;
  _updateTruncationWarning();
  const thread = document.getElementById('conv-thread');
  if (thread) thread.innerHTML = '';
}

// ═══════════════════════════════════════════════════════════════
// v8.10 — Multi-Mode Unified Stack Manager (replaces v8.8 tabs)
// ═══════════════════════════════════════════════════════════════
// When 2+ modes selected, ALL modes get cloned sections stacked vertically
// inside #multi-mode-stack. Legacy main DOM (#dispatch-row + #nodes-grid) is
// hidden in multi-mode. Each section has a labelled header + collapse toggle.
//
// API:
//   createSectionsForModes(modes) - build N stacked sections
//   destroySections()             - tear down; restore single-mode legacy DOM
//   getModeElement(modeId, baseId) - section-scoped DOM lookup
//   _scrollToSection(modeId)       - smooth scroll into view (Alt+N shortcut)
//
// Backward-compat: tabState renamed to sectionState; function signatures
// preserved for legacy callsites — createTabsForModes / destroyTabs are
// aliased to the new section APIs.
//
// modeId conventions:
//   '_default' / null / undefined → main DOM (single-mode legacy path)
//   '_combined' → first section in stack OR legacy DOM in degenerate case
//   '<mode_name>' → that mode's cloned section

const sectionState = {
  sections: {},           // mode_id → section DOM element
  modeOrder: [],          // mode_ids in selection order
  llmLabels: {},          // mode_id → "provider/model" or "default"
  collapsed: new Set(),   // mode_ids currently collapsed
};
// Backward-compat alias (R3-era code paths read these)
const tabState = sectionState;

function getModeElement(modeId, baseId) {
  // Legacy / shared / unknown → main DOM
  if (!modeId || modeId === '_default' || modeId === '_combined') {
    return document.getElementById(baseId);
  }
  const section = sectionState.sections[modeId];
  if (!section) return document.getElementById(baseId);   // fallback to legacy
  return section.querySelector(`[data-base-id="${baseId}"]`);
}

function _createSectionForMode(sel, idx) {
  // Clone #dispatch-row + #nodes-grid into a section wrapper with header.
  // Strip IDs to avoid duplicates; data-base-id attrs already in place.
  const dispatchSrc = document.getElementById('dispatch-row');
  const gridSrc = document.getElementById('nodes-grid');
  if (!dispatchSrc || !gridSrc) return null;

  const modeId = sel.mode;
  const llmLabel = sel.llm_override
    ? `${sel.llm_override.provider}/${sel.llm_override.model}`
    : 'default';
  sectionState.llmLabels[modeId] = llmLabel;

  const section = document.createElement('section');
  section.className = 'mode-section';
  section.dataset.modeId = modeId;

  // Header: mode badge + LLM label + Alt+N hint + collapse toggle
  const header = document.createElement('header');
  header.className = 'mode-section-header';
  header.innerHTML =
      `<span class="mode-section-divider">━━━</span>`
    + `<span class="mode-section-badge">/${escapeHtml(modeId)}</span>`
    + `<span class="mode-section-llm">${escapeHtml(llmLabel)}</span>`
    + `<span class="mode-section-hint">Alt+${idx + 1}</span>`
    + `<button class="mode-section-toggle" data-action="toggle" title="Collapse / expand this section">▼</button>`
    + `<span class="mode-section-divider mode-section-divider-end">━━━</span>`;
  header.querySelector('[data-action="toggle"]').addEventListener('click', () => {
    _toggleSectionCollapse(modeId);
  });
  section.appendChild(header);

  // Body: wrap dispatch + stage2 + grid clones
  const body = document.createElement('div');
  body.className = 'mode-section-body';
  const dispatchClone = dispatchSrc.cloneNode(true);
  dispatchClone.removeAttribute('id');
  dispatchClone.querySelectorAll('[id]').forEach(el => el.removeAttribute('id'));
  dispatchClone.classList.add('hidden');
  body.appendChild(dispatchClone);

  // v8.26 UX-Collapse-2 — also clone stage1-section
  const stage1Src = document.getElementById('stage1-section');
  if (stage1Src) {
    const stage1Clone = stage1Src.cloneNode(true);
    stage1Clone.removeAttribute('id');
    stage1Clone.querySelectorAll('[id]').forEach(el => el.removeAttribute('id'));
    stage1Clone.classList.add('hidden');
    body.appendChild(stage1Clone);
  }

  // v8.14 Q1 — also clone stage2-section if present in main DOM
  const stage2Src = document.getElementById('stage2-section');
  if (stage2Src) {
    const stage2Clone = stage2Src.cloneNode(true);
    stage2Clone.removeAttribute('id');
    stage2Clone.querySelectorAll('[id]').forEach(el => el.removeAttribute('id'));
    stage2Clone.classList.add('hidden');
    body.appendChild(stage2Clone);
  }

  // v8.14 BN — clone browser-audit-section if present
  const bnSrc = document.getElementById('browser-audit-section');
  if (bnSrc) {
    const bnClone = bnSrc.cloneNode(true);
    bnClone.removeAttribute('id');
    bnClone.querySelectorAll('[id]').forEach(el => el.removeAttribute('id'));
    bnClone.classList.add('hidden');
    body.appendChild(bnClone);
  }

  const gridClone = gridSrc.cloneNode(true);
  gridClone.removeAttribute('id');
  gridClone.querySelectorAll('[id]').forEach(el => el.removeAttribute('id'));
  body.appendChild(gridClone);
  section.appendChild(body);

  return section;
}

function _toggleSectionCollapse(modeId) {
  const section = sectionState.sections[modeId];
  if (!section) return;
  const collapsed = section.classList.toggle('collapsed');
  const btn = section.querySelector('.mode-section-toggle');
  if (btn) btn.textContent = collapsed ? '▶' : '▼';
  if (collapsed) sectionState.collapsed.add(modeId);
  else sectionState.collapsed.delete(modeId);
}

function _scrollToSection(modeId) {
  const section = sectionState.sections[modeId];
  if (!section) return;
  section.scrollIntoView({behavior: 'smooth', block: 'start'});
  // Brief highlight pulse
  section.classList.add('section-flash');
  setTimeout(() => section.classList.remove('section-flash'), 600);
}

function createSectionsForModes(selectedModes) {
  destroySections();
  if (!selectedModes || selectedModes.length <= 1) {
    return;   // single mode → no sections, legacy DOM stays
  }
  const stack = document.getElementById('multi-mode-stack');
  if (!stack) return;
  stack.innerHTML = '';

  // Hide legacy main DOM in multi-mode
  document.getElementById('dispatch-row')?.classList.add('multi-mode-hidden');
  document.getElementById('nodes-grid')?.classList.add('multi-mode-hidden');

  selectedModes.forEach((sel, idx) => {
    const modeId = sel.mode;
    sectionState.modeOrder.push(modeId);
    const section = _createSectionForMode(sel, idx);
    if (section) {
      stack.appendChild(section);
      sectionState.sections[modeId] = section;
    }
  });
  stack.classList.add('multi-mode-active');
}

function destroySections() {
  const stack = document.getElementById('multi-mode-stack');
  if (stack) {
    stack.innerHTML = '';
    stack.classList.remove('multi-mode-active');
  }
  // Restore legacy main DOM
  document.getElementById('dispatch-row')?.classList.remove('multi-mode-hidden');
  document.getElementById('nodes-grid')?.classList.remove('multi-mode-hidden');
  sectionState.sections = {};
  sectionState.modeOrder = [];
  sectionState.llmLabels = {};
  sectionState.collapsed.clear();
}

// Backward-compat aliases for legacy callsites
function createTabsForModes(selectedModes) { return createSectionsForModes(selectedModes); }
function destroyTabs() { return destroySections(); }
function activateTab(modeId) { return _scrollToSection(modeId); }

// Alt+1..9 — scroll the Nth section into view (Q7 reimagined for stack)
document.addEventListener('keydown', (e) => {
  if (!e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
  const n = parseInt(e.key, 10);
  if (!n || n < 1 || n > 9) return;
  const target = sectionState.modeOrder[n - 1];
  if (target) {
    e.preventDefault();
    _scrollToSection(target);
  }
});

// Modes removed from the UI picker; fall back to "firewall" if somehow received.
const _REMOVED_MODES = new Set(['plain_llm', 'trinity_only', 'delabel_only']);

// v8.8 — Build selected_modes payload from multi-checkbox UI.
// Returns: { selected_modes: [...], execution_strategy, combined_executor }
function collectMultiModePayload() {
  const checked = Array.from(document.querySelectorAll('input[name="mode"]:checked'));
  const selected = checked.map(cb => {
    const rawMode = cb.value;
    const mode = _REMOVED_MODES.has(rawMode) ? 'firewall' : rawMode;
    const pickEl = document.querySelector(`.mode-llm-pick[data-mode="${rawMode}"]`);
    const val = pickEl ? pickEl.value : 'default';
    const llm_override = (val && val !== 'default') ? _parseLLMPickValue(val) : null;
    return { mode, llm_override };
  });
  const strat = document.querySelector('input[name="exec_strategy"]:checked')?.value || 'parallel';
  let combined_executor = null;
  if (strat === 'combined') {
    const ce = document.getElementById('combined-executor-pick')?.value || 'default';
    if (ce !== 'default') combined_executor = _parseLLMPickValue(ce);
  }
  return { selected_modes: selected, execution_strategy: strat, combined_executor };
}

// Picker values are "<profile>" strings; on apply they translate to LLMOverride.
// We resolve via window.__apiProfiles loaded at page init (filled by initLLMPickers).
function _parseLLMPickValue(profileKey) {
  const profiles = window.__apiProfiles || {};
  const p = profiles[profileKey];
  if (!p) return null;
  return { provider: p.provider, model: p.model, api_profile: profileKey };
}

// v8.8 — Validate multi-mode selection before submit.
// Shows inline warning if violations; returns true if OK to proceed.
function validateMultiModeSelection(payload) {
  const warnEl = document.getElementById('mode-warning');
  if (warnEl) warnEl.classList.add('hidden');
  if (!payload.selected_modes.length) {
    if (warnEl) {
      warnEl.textContent = '⚠ 至少揀一個 mode';
      warnEl.classList.remove('hidden');
    }
    return false;
  }
  // Q2: combined incompatible with plain_llm/delabel_only
  if (payload.execution_strategy === 'combined') {
    const incompat = payload.selected_modes.filter(s =>
      ['plain_llm', 'delabel_only'].includes(s.mode)
    ).map(s => s.mode);
    if (incompat.length) {
      if (warnEl) {
        warnEl.textContent = `⚠ Combined strategy 唔可以同 ${incompat.join(', ')} 一齊用 — 揀 Parallel 或者移除呢啲 mode`;
        warnEl.classList.remove('hidden');
      }
      return false;
    }
  }
  // Q8: soft cap warning at 5
  if (payload.selected_modes.length > 5) {
    if (warnEl) {
      warnEl.textContent = `⚠ 揀咗 ${payload.selected_modes.length} 個 mode（soft cap 5）— UI 可能擠擁，但會繼續執行`;
      warnEl.classList.remove('hidden');
    }
    // Soft cap = warn but allow
  }
  return true;
}

// v8.8 — Populate <select.mode-llm-pick> dropdowns with available api_profiles.
async function initLLMPickers() {
  try {
    const r = await fetch('/api/nodes/config');
    if (!r.ok) return;
    const data = await r.json();
    const profiles = data.api_profiles || {};
    window.__apiProfiles = profiles;
    const optionHtml = ['<option value="default">default LLM</option>'];
    Object.entries(profiles).forEach(([key, p]) => {
      if (p.enabled === false) return;
      const label = `${p.provider}/${p.model}`;
      optionHtml.push(`<option value="${escapeHtml(key)}">${escapeHtml(label)}</option>`);
    });
    const html = optionHtml.join('');
    document.querySelectorAll('.mode-llm-pick').forEach(sel => { sel.innerHTML = html; });
    const ce = document.getElementById('combined-executor-pick');
    if (ce) ce.innerHTML = html;
  } catch (e) {
    console.warn('initLLMPickers failed', e);
  }
}

// v8.8 — show/hide combined_executor row + warning re-validate on radio change
document.addEventListener('DOMContentLoaded', () => {
  initLLMPickers();
  document.querySelectorAll('input[name="exec_strategy"]').forEach(r => {
    r.addEventListener('change', () => {
      const row = document.getElementById('combined-executor-row');
      if (row) row.classList.toggle('hidden', r.value !== 'combined' || !r.checked);
      const live = collectMultiModePayload();
      validateMultiModeSelection(live);
    });
  });
  document.querySelectorAll('input[name="mode"]').forEach(cb => {
    cb.addEventListener('change', () => {
      const live = collectMultiModePayload();
      validateMultiModeSelection(live);
    });
  });
});

// ─────────────────────────────────────────────────────────────────
// Coordinate visualization + Civilizational Clock simulator
// ─────────────────────────────────────────────────────────────────

async function renderCoordinateMap() {
  const container = document.getElementById('coord-map-container');
  if (!container) return;
  // Need at least stage3 (law scores) to render a meaningful map
  if (!__lastStage2 && !__lastStage3) return;
  try {
    const r = await fetch('/api/simulation/coordinate-map', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        stage2_output: __lastStage2 ? JSON.stringify(__lastStage2) : '',
        stage3_output: __lastStage3 ? JSON.stringify(__lastStage3) : '',
        input_text: __lastInputText || '',
        output_format: 'html',
      }),
    });
    const data = await r.json();
    if (data.ok && data.html) {
      container.innerHTML = data.html;
      // Plotly HTML includes <script> tags that innerHTML won't execute —
      // re-inject them so the CDN loader + figure render actually run.
      container.querySelectorAll('script').forEach(old => {
        const s = document.createElement('script');
        if (old.src) s.src = old.src;
        else s.textContent = old.textContent;
        old.parentNode.replaceChild(s, old);
      });
    } else {
      const hint = data.install_hint ? ` (${data.install_hint})` : '';
      container.innerHTML = `<div class="viz-placeholder">座標圖無法渲染：${escapeHtml(data.error || 'unknown')}${escapeHtml(hint)}</div>`;
    }
  } catch (e) {
    container.innerHTML = `<div class="viz-placeholder">座標圖請求失敗：${escapeHtml(String(e))}</div>`;
  }
}

async function runClockSimulation() {
  const resultsEl = document.getElementById('clock-results');
  if (!resultsEl) return;
  const speed = document.getElementById('clock-speed')?.value || '0.3';
  const lie = document.getElementById('clock-lie')?.value || '5.85';
  resultsEl.innerHTML = '<div class="viz-placeholder">模擬中⋯</div>';
  try {
    const r = await fetch(`/api/simulation/clock?speed=${encodeURIComponent(speed)}&lie_cost=${encodeURIComponent(lie)}`);
    const d = await r.json();
    if (!d.ok) {
      resultsEl.innerHTML = `<div class="viz-placeholder">模擬失敗：${escapeHtml(d.error || 'unknown')}</div>`;
      return;
    }
    const eq = d.equations || {};
    const interp = d.interpretation || {};
    const urgencyColor = interp.urgency_level === 'critical' ? '#E24B4A'
      : (interp.urgency_level === 'high' ? '#D08A3E' : '#1D9E75');
    const rows = [
      ['Eq1 部署延遲 (年)', eq.eq1_deployment_delay_years],
      ['Eq2 窗口緊迫度', eq.eq2_window_urgency],
      ['Eq3 LIE 累積', eq.eq3_lie_accumulation],
      ['Eq4 自由損失/單位', eq.eq4_freedom_loss_per_unit],
      ['Eq5 存活機率', eq.eq5_survival_probability],
    ].map(([k, v]) => `<tr><td>${escapeHtml(k)}</td><td>${escapeHtml(String(v))}</td></tr>`).join('');
    const anchorRows = (d.historical_anchors || []).map(a =>
      `<tr><td>${a.year}</td><td>${escapeHtml(a.event)}</td><td>${a.model_fit}</td></tr>`
    ).join('');
    resultsEl.innerHTML = `
      <div class="clock-summary" style="border-left:3px solid ${urgencyColor};padding-left:8px;margin:8px 0">
        <strong>${escapeHtml(interp.urgency_level || '')}</strong> · ${escapeHtml(interp.summary || '')}
        <div>剩餘 ${interp.years_remaining} 年 · 部署可行：${interp.deployment_feasible ? '✓' : '✗'}</div>
      </div>
      <table class="clock-table"><thead><tr><th>方程式</th><th>值</th></tr></thead><tbody>${rows}</tbody></table>
      <details class="clock-anchors"><summary>歷史校準錨點 (${(d.historical_anchors||[]).length})</summary>
        <table class="clock-table"><thead><tr><th>年</th><th>事件</th><th>擬合度</th></tr></thead><tbody>${anchorRows}</tbody></table>
      </details>`;
  } catch (e) {
    resultsEl.innerHTML = `<div class="viz-placeholder">模擬請求失敗：${escapeHtml(String(e))}</div>`;
  }
}

document.addEventListener('DOMContentLoaded', () => {
  // Tab switching between coordinate map and clock panes
  document.querySelectorAll('.viz-tab').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      const tab = btn.dataset.tab;
      document.querySelectorAll('.viz-tab').forEach(b => b.classList.toggle('active', b === btn));
      const coordPane = document.getElementById('viz-coord-pane');
      const clockPane = document.getElementById('viz-clock-pane');
      if (coordPane) coordPane.style.display = (tab === 'coord') ? 'block' : 'none';
      if (clockPane) clockPane.style.display = (tab === 'clock') ? 'block' : 'none';
    });
  });
  // Clock slider live labels
  const speedSlider = document.getElementById('clock-speed');
  const speedVal = document.getElementById('clock-speed-val');
  if (speedSlider && speedVal) speedSlider.addEventListener('input', () => { speedVal.textContent = speedSlider.value; });
  const lieSlider = document.getElementById('clock-lie');
  const lieVal = document.getElementById('clock-lie-val');
  if (lieSlider && lieVal) lieSlider.addEventListener('input', () => { lieVal.textContent = lieSlider.value; });
  // Run button
  const runBtn = document.getElementById('clock-run-btn');
  if (runBtn) runBtn.addEventListener('click', runClockSimulation);
});

async function runTrinity() {
  if (window.__runTrinityActive) {
    setStatus('⚠ 上一個 query 仲未完，請等 streaming 完先');
    return;
  }
  if (window.__pendingSnapshot) _commitPendingSnapshot();
  const inputEl = document.getElementById('user-input');
  const input = inputEl.value.trim();
  if (!input) {
    setStatus(I18N[currentLang]['no-input']);
    return;
  }

  const worldAdvice = await worldRouteAdvice(input);
  if (worldAdvice.intercept_chat || worldAdvice.explicit) {
    await handleWorldCommand(input, inputEl);
    return;
  }

  // ── Agent Chat mode: bypass Trinity, send to /api/agent/run ───
  const agentChk = document.getElementById('agent-chat-mode-chk');
  if (agentChk && agentChk.checked) {
    inputEl.value = '';
    await _runAgentChat(input);
    return;
  }

  // v8.8 — collect multi-mode payload + validate
  const multi = collectMultiModePayload();
  if (!validateMultiModeSelection(multi)) {
    setStatus('⚠ mode selection 有問題，check 提示');
    return;
  }

  // Bug 3 fix: mark active + disable button IMMEDIATELY after validation passes.
  // Done here (vs at line ~877) so re-entry is blocked before any DOM mutation.
  window.__runTrinityActive = true;
  const runBtnEarly = document.getElementById('run-btn');
  if (runBtnEarly) {
    runBtnEarly.disabled = true;
    runBtnEarly.textContent = I18N[currentLang]['run-btn-running'];
  }

  // Bug 2 fix: clear textarea immediately on submit (ChatGPT-style UX).
  // Echoed in workspace-input-echo + later in conv-thread, so input value is not lost.
  inputEl.value = '';
  // v8.25 UX — reset the council answer bubble. The compact status chips show
  // progress; detailed internal panels stay hidden unless developer mode is on.
  _resetCouncilBubble();
  const selectedModes = multi.selected_modes;
  const executionStrategy = multi.execution_strategy;
  const combinedExecutor = multi.combined_executor;

  // Legacy pipeline_mode field for backward compat when single mode + no overrides
  const singleMode = selectedModes.length === 1 ? selectedModes[0].mode : null;
  const pipelineMode = singleMode === 'auto' ? null : singleMode;

  // v8.10 — set up stacked sections (no-op if singleMode)
  createSectionsForModes(selectedModes);

  // Reset panels — both legacy main DOM and any tab clones
  const resetRoles = ['father', 'son', 'spirit', 'council'];
  resetRoles.forEach(role => {
    const out = document.getElementById(`output-${role}`);
    if (out) {
      out.innerHTML = '';
      out.classList.add('streaming');
      out.classList.remove('error');
    }
  });
  // Reset cloned section panels too (v8.10 — multi-mode-stack)
  document.querySelectorAll('#multi-mode-stack .node-output').forEach(out => {
    out.innerHTML = '';
    out.classList.add('streaming');
    out.classList.remove('error');
  });
  document.getElementById('dispatch-row').classList.add('hidden');
  document.querySelectorAll('#multi-mode-stack [data-base-id="dispatch-row"]').forEach(el => el.classList.add('hidden'));
  // v8.14 Q1 — reset stage2 surface on new run
  const stage2Main = document.getElementById('stage2-section');
  if (stage2Main) {
    stage2Main.classList.add('hidden');
    stage2Main.querySelectorAll('.stage2-cell-output').forEach(p => { p.textContent = ''; });
  }
  document.querySelectorAll('#multi-mode-stack [data-base-id="stage2-section"]').forEach(el => {
    el.classList.add('hidden');
    el.querySelectorAll('.stage2-cell-output').forEach(p => { p.textContent = ''; });
  });
  // v8.26 UX-Collapse-2 — reset stage1 surface on new run
  const stage1Main = document.getElementById('stage1-section');
  if (stage1Main) {
    stage1Main.classList.add('hidden');
    stage1Main.querySelectorAll('.stage1-cell-output').forEach(p => { p.textContent = ''; });
  }
  document.querySelectorAll('#multi-mode-stack [data-base-id="stage1-section"]').forEach(el => {
    el.classList.add('hidden');
    el.querySelectorAll('.stage1-cell-output').forEach(p => { p.textContent = ''; });
  });
  // v8.14 BN — reset browser-audit surface on new run
  const bnMain = document.getElementById('browser-audit-section');
  if (bnMain) {
    bnMain.classList.add('hidden');
    bnMain.open = false;
    const bnList = bnMain.querySelector('[data-base-id="browser-audit-list"]');
    if (bnList) bnList.innerHTML = '';
    const bnSum = bnMain.querySelector('[data-base-id="browser-audit-summary"]');
    if (bnSum) bnSum.innerHTML = '';
    const bnCnt = bnMain.querySelector('[data-base-id="browser-audit-counter"]');
    if (bnCnt) bnCnt.textContent = '0 sources';
  }
  document.querySelectorAll('#multi-mode-stack [data-base-id="browser-audit-section"]').forEach(el => {
    el.classList.add('hidden');
    el.open = false;
    el.querySelectorAll('[data-base-id="browser-audit-list"]').forEach(x => x.innerHTML = '');
    el.querySelectorAll('[data-base-id="browser-audit-summary"]').forEach(x => x.innerHTML = '');
    el.querySelectorAll('[data-base-id="browser-audit-counter"]').forEach(x => x.textContent = '0 sources');
  });
  resetKnowledgePanel();
  resetInferencePanel();
  // Restore 4-panel layout in case user opened an archived session previously
  const grid = document.getElementById('nodes-grid');
  grid.classList.remove('archived-view');
  // v8.6 — single-panel layout when single mode is plain_llm or delabel_only
  if (singleMode === 'plain_llm' || singleMode === 'delabel_only') {
    grid.classList.add('single-stage-output');
  } else {
    grid.classList.remove('single-stage-output');
  }

  // Run button already disabled by Bug 3 fix earlier; alias for finally restore
  const runBtn = runBtnEarly || document.getElementById('run-btn');
  const save = document.getElementById('save-checkbox').checked;
  const label = document.getElementById('label-input').value.trim();

  const autoTools = document.getElementById('auto-tools-checkbox')?.checked || false;
  const inferenceBudget = document.getElementById('inference-budget-select')?.value || 'auto';
  // v8.4 — one-shot detach: clear flag immediately after consuming
  const detachHistory = window.__detachNextQuery === true;
  window.__detachNextQuery = false;
  // v8.11 — Start buffering current turn for in-session history
  _startNewTurnBuffer(input, selectedModes, executionStrategy);

  // v8.11 — Show workspace input echo (user's current query)
  const echo = document.getElementById('workspace-input-echo');
  if (echo) {
    const turnNum = (__convHistory.turns.length + 1) + __convHistory.truncation_count;
    echo.innerHTML = `<span class="workspace-input-label">Turn ${turnNum}</span>`
                   + `<span class="workspace-input-text">你: ${escapeHtml(input)}</span>`;
    echo.classList.remove('hidden');
    requestAnimationFrame(() => {
      const mainCol = document.getElementById('main-column');
      if (mainCol) mainCol.scrollTop = mainCol.scrollHeight;
    });
  }

  const payload = {
    input: input,
    refs: [...activeRefs],
    pipeline_mode: pipelineMode,
    selected_modes: selectedModes,
    execution_strategy: executionStrategy,
    combined_executor: combinedExecutor,
    save: save,
    label: label,
    auto_tools: autoTools,
    inference_budget: inferenceBudget,
    detach_history: detachHistory,
    // v8.11 — in-session conversation history
    in_session_history: _buildHistoryPayload(selectedModes),
    in_session_enabled: !!__convHistory.enabled,
    // v8.13 D3 — when in resume mode, save back to the original file (overwrite)
    resume_filename: window.__resumeMode ? window.__resumeMode.filename : null,
    // v8.47b — app_relay target (empty = auto)
    app_relay_target: document.getElementById('app-relay-target-select')?.value || null,
  };
  // Hide stale banner from a previous run; it will re-appear if server emits
  // cross_session_attached for THIS run.
  document.getElementById('cross-session-banner')?.classList.add('hidden');

  try {
    const response = await fetch('/api/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // Parse SSE events
      const events = buffer.split('\n\n');
      buffer = events.pop() || ''; // Keep incomplete

      for (const evt of events) {
        if (!evt.trim()) continue;
        const lines = evt.split('\n');
        let eventType = 'message';
        let dataStr = '';
        for (const line of lines) {
          if (line.startsWith('event:')) eventType = line.slice(6).trim();
          else if (line.startsWith('data:')) dataStr += line.slice(5).trim();
        }
        if (dataStr) {
          try {
            const data = JSON.parse(dataStr);
            handleEvent(eventType, data);
          } catch (e) {
            console.error('Failed to parse event:', dataStr, e);
          }
        }
      }
    }
  } catch (e) {
    console.error('Run failed:', e);
    setStatus(`${I18N[currentLang]['status-error']}: ${e.message}`, true);
  } finally {
    if (runBtn) {
      runBtn.disabled = false;
      runBtn.textContent = I18N[currentLang]['run-btn'];
    }
    document.querySelectorAll('.node-output').forEach(el => el.classList.remove('streaming'));
    // Bug 3 fix: clear re-entry guard
    window.__runTrinityActive = false;
  }
}

function formatDispatchCost(data) {
  const metrics = (data && data.cost_metrics) || {};
  const budget = (data && data.context_budget) || {};
  const costClass = metrics.estimated_cost_class || metrics.cost_class || 'unknown';
  const calls = metrics.planned_model_calls ?? metrics.estimated_model_calls ?? metrics.model_calls ?? '?';
  const limit = metrics.model_call_budget ?? '?';
  const apiCalls = metrics.estimated_api_model_calls ?? metrics.api_model_calls ?? '?';
  const tokens = metrics.estimated_context_tokens
    ?? budget.estimated_total_tokens
    ?? budget.estimated_input_tokens
    ?? '?';
  const tier = data.model_tier || metrics.tier || 'tier?';
  const cache = metrics.cache_hit === true ? ' · cache hit' : '';
  return `${costClass} · planned ${calls} / limit ${limit} · api ${apiCalls} · ctx ${tokens} tok · ${tier}${cache}`;
}

function resetInferencePanel() {
  const panel = document.getElementById('inference-panel');
  if (panel) panel.classList.add('hidden');
  ['inference-planned', 'inference-limit'].forEach(id => {
    const el = document.getElementById(id); if (el) el.textContent = '--';
  });
  ['inference-actual', 'inference-unique'].forEach(id => {
    const el = document.getElementById(id); if (el) el.textContent = '0';
  });
  const summary = document.getElementById('inference-summary');
  if (summary) summary.textContent = '等待路由';
  const reason = document.getElementById('inference-reason');
  if (reason) reason.textContent = '';
  const list = document.getElementById('inference-call-list');
  if (list) list.innerHTML = '';
  document.querySelectorAll('.inference-usage-chip').forEach(el => el.remove());
}

function renderInferenceBudget(data) {
  const policy = (data && data.policy) || {};
  const panel = document.getElementById('inference-panel');
  if (panel) panel.classList.remove('hidden');
  const planned = document.getElementById('inference-planned');
  const limit = document.getElementById('inference-limit');
  const summary = document.getElementById('inference-summary');
  const reason = document.getElementById('inference-reason');
  if (planned) planned.textContent = policy.planned_calls ?? '--';
  if (limit) limit.textContent = policy.hard_max_calls ?? '--';
  if (summary) summary.textContent = `${policy.preference || 'auto'} · 計劃 ${policy.planned_calls ?? '--'} / 上限 ${policy.hard_max_calls ?? '--'}`;
  if (reason) reason.textContent = `${policy.route_kind || 'unknown'} · ${policy.pipeline_mode || 'auto'} · ${policy.reason || ''}`;
}

function renderInferenceUsage(data, modeId) {
  window.__lastInferenceUsage = data || {};
  renderInferenceBudget({policy: data.policy || {}});
  const actual = document.getElementById('inference-actual');
  const unique = document.getElementById('inference-unique');
  const summary = document.getElementById('inference-summary');
  if (actual) actual.textContent = `${data.actual_requests ?? 0} (${data.successful_requests ?? 0} 成功 / ${data.failed_requests ?? 0} 失敗)`;
  if (unique) unique.textContent = data.unique_model_count ?? 0;
  if (summary) {
    summary.textContent = `實際 ${data.actual_requests ?? 0} / 上限 ${data.policy?.hard_max_calls ?? '--'} · ${data.unique_model_count ?? 0} 個模型`;
  }
  const list = document.getElementById('inference-call-list');
  if (list) {
    list.innerHTML = (data.calls || []).map(call => `
      <div class="inference-call-row">
        <span>${escapeHtml(call.role || 'unscoped')}</span>
        <span>${escapeHtml(`${call.provider || '?'}/${call.model || '?'}`)}</span>
        <span class="${call.status === 'success' ? 'ok' : 'failed'}">${escapeHtml(call.status || '?')}</span>
        <span>${Number(call.latency_ms || 0).toFixed(0)}ms</span>
      </div>`).join('');
  }
  const council = getModeElement(modeId || '_default', 'output-council');
  if (council) {
    council.querySelectorAll('.inference-usage-chip').forEach(el => el.remove());
    const chip = document.createElement('span');
    chip.className = 'inference-usage-chip';
    chip.textContent = `模型調用 ${data.actual_requests ?? 0}/${data.policy?.hard_max_calls ?? '--'} · ${data.unique_model_count ?? 0} models`;
    council.prepend(chip);
  }
}

function handleEvent(type, data) {
  // v8.8 — pull mode_id off every event for tab-scoped DOM routing
  const _mid = (data && data._mode_id) || '_default';
  // v8.11 — record turn data for in-session history (no-op if currentTurn null)
  _recordTurnEvent(type, data);
  // Coordinate-map viz: capture stage2/stage3 payloads for the 3D map render on `done`
  if (type === 'stage1' && data) __lastInputText = data.delabeled_input || __lastInputText;
  if (type === 'stage2') __lastStage2 = data;
  if (type === 'stage3') __lastStage3 = data;
  if (type === 'knowledge_health') {
    renderKnowledgeHealth(data);
  }
  else if (type === 'inference_budget') {
    renderInferenceBudget(data);
  }
  else if (type === 'inference_usage') {
    renderInferenceUsage(data, _mid);
  }
  else if (type === 'knowledge_trace') {
    renderKnowledgeTrace(data.trace || []);
  }
  else if (type === 'status') {
    const map = {
      dispatch: 'status-dispatching',
      perspectives: 'status-perspectives',
      council: 'status-council',
    };
    setStatus(I18N[currentLang][map[data.phase]] || data.message, false, true);
  }
  else if (type === 'dispatch') {
    const dm = getModeElement(_mid, 'dispatch-mode');
    const dr = getModeElement(_mid, 'dispatch-rationale');
    const drf = getModeElement(_mid, 'dispatch-refs');
    const dc = getModeElement(_mid, 'dispatch-cost');
    const drow = getModeElement(_mid, 'dispatch-row');
    if (dm) dm.textContent = data.mode || '?';
    if (dr) dr.textContent = data.mode_rationale || '';
    if (drf) drf.textContent = (data.references || []).join(', ');
    if (dc) dc.textContent = formatDispatchCost(data);
    if (drow) drow.classList.remove('hidden');
  }
  else if (type === 'node') {
    const out = getModeElement(_mid, `output-${data.role}`);
    if (out) {
      out.textContent = data.output;
      out.classList.remove('streaming');
      if (data.error) out.classList.add('error');
    }
  }
  // v8.14 BN — BrowserNode per-source audit chip
  else if (type === 'source_audited') {
    renderSourceAudit(data);
  }
  // v8.14 BN — BrowserNode aggregate summary (spec compliance check)
  else if (type === 'browser_audit_summary') {
    renderBrowserAuditSummary(data);
  }
  // v8.15 MS-3 — emit per-engine row to a transient status line; full list
  // is also folded into the browser_audit_summary above for persistence.
  else if (type === 'search_engine_used') {
    const _mid = (data && data._mode_id) || '_default';
    const statusEl = getModeElement(_mid, 'workspace-status') || document.getElementById('workspace-status');
    if (statusEl) {
      const reason = data.reason || '';
      const eng = data.engine || '?';
      statusEl.textContent = `🔍 search · ${eng} · ${reason} · ${data.results_count ?? 0} result(s)`;
    }
  }
  // v8.26 UX-Collapse-2 — Stage 1 去標籤化 streaming surface
  else if (type === 'stage1') {
    const section = getModeElement(_mid, 'stage1-section');
    const delabeled = getModeElement(_mid, 'stage1-delabeled');
    const labels    = getModeElement(_mid, 'stage1-labels');
    const flags     = getModeElement(_mid, 'stage1-flags');
    if (delabeled) delabeled.textContent = data.delabeled_input || '(empty)';
    if (labels) {
      // v8.30 p12 — distinguish "real (none)" from "Stage 1 structural failure".
      // When _structural_failure is set, Stage 1 LLM never produced parseable
      // output even after failover walk — surface this loudly instead of
      // silently showing (none) as if the input had no labels.
      const structFail = data._structural_failure;
      const detected = data.detected_labels || [];
      if (detected.length) {
        labels.textContent = detected
          .map(l => `• ${l.label || l} → ${l.physical_param || ''}`)
          .join('\n');
      } else if (structFail) {
        const label = {
          all_providers_empty_content: '⚠ Stage 1 結構性失敗：所有 provider 都返回空殼/garbage（failover chain 已 walk）',
          parse_retry_exhausted:        '⚠ Stage 1 結構性失敗：JSON parser 嘅 3 次 retry 都失敗',
          call_exception:               '⚠ Stage 1 結構性失敗：LLM call exception',
        }[structFail] || `⚠ Stage 1 結構性失敗 (${structFail})`;
        labels.textContent = label;
      } else {
        labels.textContent = '(none)';
      }
    }
    if (flags) {
      const parts = [];
      if (data.veto_detected === 'yes') parts.push(`🚨 veto: ${data.veto_type || '?'}`);
      if (data.interrupt_detected === 'yes') parts.push(`⚡ interrupt: ${data.interrupt_type || '?'}`);
      if (data.abort_signal === 'yes') parts.push(`⛔ abort → council`);
      if (data._structural_failure) parts.push(`⚠ stage1: ${data._structural_failure}`);
      flags.textContent = parts.length ? parts.join(' / ') : 'clean (no veto / interrupt)';
    }
    if (section) {
      section.classList.remove('hidden');
      section.open = true;   // auto-expand during streaming
    }
  }
  // v8.14 Q1 / v8.26 UX-Collapse-2 / v8.30 p6 — Stage 2 解釋層 UI surface.
  // Canonical 4 laws + 貫穿律 哲學 (per EXPLANATION_LAYER.md v7.2):
  //   律一 地理 / 律二 宗教 / 律三 心理 / 律四 歷史 / 貫穿律 哲學
  // Pre-v8.30 the UI was missing 律三 (psychology_analysis) and 律四
  // (history_analysis) slots entirely, and used 八律 numbering (律六/七/八)
  // by mistake — those have been corrected in index.html as well.
  else if (type === 'stage2') {
    const section = getModeElement(_mid, 'stage2-section');
    const geo = getModeElement(_mid, 'stage2-geography');
    const rel = getModeElement(_mid, 'stage2-religion');
    const psy = getModeElement(_mid, 'stage2-psychology');
    const his = getModeElement(_mid, 'stage2-history');
    const phi = getModeElement(_mid, 'stage2-philosophy');
    const cau = getModeElement(_mid, 'stage2-causal');
    if (geo) geo.textContent = data.geography_analysis || '(empty)';
    if (rel) rel.textContent = data.religion_analysis || data.temporal_analysis || '(empty)';
    if (psy) psy.textContent = data.psychology_analysis || '(empty)';
    if (his) his.textContent = data.history_analysis || '(empty)';
    if (phi) phi.textContent = data.philosophy_dispatch || '(empty)';
    if (cau) cau.textContent = data.causal_summary || '(empty)';
    if (section) {
      section.classList.remove('hidden');
      section.open = true;   // v8.26 — auto-expand during streaming
    }
  }
  else if (type === 'auto_tool_decisions') {
    const summary = [];
    if (data.search?.needed) summary.push(`🔍 search: "${data.search.query}"`);
    if (data.fetch?.needed)  summary.push(`🌐 fetch: ${data.fetch.url}`);
    if (data.calendar?.needed) summary.push(`📅 calendar: ${data.calendar.from} → ${data.calendar.to}`);
    setStatus(`🤖 自動工具決定：${summary.length ? summary.join(' / ') : '冇 tool 需要'}`);
  }
  else if (type === 'auto_tool_results') {
    const preview = (data.text || '').slice(0, 100).replace(/\n/g, ' ');
    setStatus(`🤖 自動工具結果已注入 pipeline（${data.text?.length || 0} 字）`);
  }
  else if (type === 'tool_result') {
    const bar = document.getElementById('tool-results-bar');
    if (bar) {
      const chip = document.createElement('div');
      chip.className = 'tool-result-chip ' + (data.ok ? 'ok' : 'err');
      chip.innerHTML = '<i class="ti ti-' + (data.ok ? 'check' : 'x') + '"></i> '
        + (data.tool_name || '') + ': ' + (data.summary || data.error || '');
      bar.appendChild(chip);
      bar.style.display = 'flex';
    }
  }
  else if (type === 'meta_response') {
    // Meta command reply — render directly in council output area as immediate answer
    const councilOut = getModeElement(_mid, 'output-council');
    if (councilOut) {
      councilOut.innerHTML = '';
      const pre = document.createElement('pre');
      pre.style.whiteSpace = 'pre-wrap';
      pre.style.fontFamily = 'var(--mono, monospace)';
      pre.style.fontSize = '13px';
      pre.style.padding = '12px';
      pre.textContent = data.text || '(empty meta reply)';
      councilOut.appendChild(pre);
    }
    setStatus(`🧩 Meta: ${data.command}`);
  }
  else if (type === 'skill_matched') {
    setStatus(`🧩 Skill matched: ${(data.skills || []).join(', ')}`);
  }
  else if (type === 'skill_applied') {
    const tc = data.tool_calls || [];
    const tcInfo = tc.length ? ` (${tc.length} tool calls)` : '';
    setStatus(`🧩 Skill applied: ${data.name} [${data.type}]${tcInfo}`);
  }
  else if (type === 'saved') {
    setStatus(`${I18N[currentLang]['status-saved']}${data.filename}`);
    if (__timelineData.length) loadTimeline();
  }
  else if (type === 'cross_session_attached') {
    renderCrossSessionBanner(data);
  }
  // v8.7 — Trinity v7.2 Spirit interrupt (rescan fired, meeting re-opening)
  else if (type === 'spirit_interrupt') {
    renderSpiritInterrupt(data);
  }
  // v8.7 — Trinity v7.2 Spirit metadata (always emitted at end of scan loop)
  else if (type === 'spirit_metadata') {
    renderSpiritMetadata(data);
  }
  // v8.9 Phase B — Father pause event (Son veto enforcement)
  else if (type === 'father_paused') {
    renderFatherPaused(data);
  }
  // v8.9 Phase B — Son veto metadata (always emitted; dev-mode chip)
  else if (type === 'son_veto_metadata') {
    renderSonVetoMetadata(data);
  }
  // v8.9 Phase A — Council 4b decision (verdict + weights)
  else if (type === 'council_decision') {
    renderCouncilDecision(data);
  }
  // v8.14 Module N — alignment resonance detection (positive signal)
  else if (type === 'alignment_resonance') {
    renderAlignmentResonance(data);
  }
  // Pre-Gate classification result
  else if (type === 'pre_gate_result') {
    const icon = { simple: '⚡', tool: '🛠', search: '🔍', complex: '🧠' }[data.type] || '?';
    setStatus(`${icon} Pre-Gate: ${data.type} (${data.source}, conf ${(data.confidence*100).toFixed(0)}%) — ${data.reason}`);
  }
  // Pre-Gate suggestion chip
  else if (type === 'pre_gate_suggest') {
    const chip = document.createElement('div');
    chip.className = 'pre-gate-suggest';
    chip.textContent = data.message;
    const workspace = document.querySelector('#workspace-input-echo, .workspace-echo, #conv-thread');
    if (workspace) workspace.prepend(chip);
  }
  // Trinity→Tool Bridge + Agent Chat: agent step events
  else if (type === 'agent') {
    const panel = document.getElementById('agent-chat-panel');
    const steps = document.getElementById('agent-chat-steps');
    const status = document.getElementById('agent-chat-status');
    if (panel) panel.classList.remove('hidden');
    _handleAgentEvent(data, steps, status);
  }
  // v8.6 — plain_llm mode result lands in council panel (single-stage-output layout)
  else if (type === 'direct_response') {
    const out = getModeElement(_mid, 'output-council');
    if (out) {
      out.textContent = data.text || '(no response)';
      out.classList.remove('streaming');
    }
    const modeLabel = data.mode === 'tool_workshop'
      ? '🔧 Tool Workshop'
      : data.mode === 'app_relay'
        ? `🖥 App 中繼 → ${data.model || ''}`
        : data.mode === 'smart_auto'
          ? `🧭 智能路由 → ${data.routing ? data.routing.backend : (data.provider || '?')}`
          : '💬 Plain LLM';
    const meta = (data.mode === 'app_relay' || data.mode === 'smart_auto')
      ? `${data.latency_ms}ms`
      : `${data.provider}/${data.model} · ${data.latency_ms}ms`;
    setStatus(`${modeLabel}: ${meta}`);

    // Update smart_auto badge if visible
    if (data.mode === 'smart_auto' && data.routing) {
      const badge = document.getElementById('smart-auto-badge');
      if (badge) {
        const be = data.routing.backend || '';
        const displayBackend = be === 'claude_desktop' ? 'uruk_protocol_carrier_relay' : be;
        badge.textContent = `${displayBackend} — ${data.routing.reason || ''}`;
        badge.className = 'sa-badge ' + (
          be === 'claude_desktop' ? 'desktop' :
          be === 'copilot_desktop' ? 'desktop' :
          be === 'ollama' ? 'ollama' : 'api'
        );
      }
    }
    _stopTrinityStatusBar();
  }
  // v8.45 — tool_install_proposal: render inline install card in council panel
  else if (type === 'tool_install_proposal') {
    const out = getModeElement(_mid, 'output-council');
    if (out) {
      _renderToolInstallCard(out, data);
    }
  }
  // v8.6 — delabel_only result: pretty-print Stage 1 JSON in council panel
  else if (type === 'delabel_only_done') {
    const out = getModeElement(_mid, 'output-council');
    if (out) {
      out.textContent = JSON.stringify(data.result || {}, null, 2);
      out.classList.remove('streaming');
    }
    setStatus('🏷 De-labeling complete');
  }
  else if (type === 'density_audit') {
    // §4.6 output self-audit result — show output density + candidate count
    const d = data.density || '?';
    const n = data.candidate_count || 0;
    const accepted = (data.accepted_candidates || []).length;
    const ran = data.audit_ran;
    const errs = data.errors || [];
    let icon = ran ? (d === 'HIGH' ? '🟠' : '🟢') : '🔴';
    let msg = `${icon} 系統輸出自查: ${ran ? d : 'VIOLATION'}`;
    if (ran && n > 0) msg += ` · ${accepted}/${n} candidate(s) accepted`;
    if (data.proposed_path) msg += ` · ${data.proposed_path.split('/').pop()}`;
    if (errs.length) msg += ` · err: ${errs[0].slice(0, 80)}`;
    setStatus(msg, !ran || errs.length > 0);
    // Optional: render full audit detail into status (or a sidebar). Keep it simple.
    window.__lastAudit = data;   // expose for power users / debugging
  }
  else if (type === 'physics_compute') {
    // v8.37 — render dev-only physics compute line on top of council body.
    // Strictly informational. Does NOT feed eight-law / council fusion.
    window.__lastPhysics = data;
    renderPhysicsLine(_mid, data);
  }
  else if (type === 'done') {
    const ps = data.protocol_status;
    const oa = ps && ps.output_audit ? ps.output_audit : null;
    const auditRan = oa ? oa.ran : (ps && ps.audit_ran);
    const auditDensity = oa ? oa.density : (ps && ps.density);
    const auditCount = oa ? oa.candidate_count : (ps && ps.candidate_count);
    const auditPath = oa ? oa.proposed_path : (ps && ps.proposed_path);
    if (ps && auditRan === false) {
      setStatus(`🔴 ${I18N[currentLang]['status-done']} — 系統輸出自查未執行`, true);
    } else if (ps && auditDensity === 'HIGH') {
      const file = auditPath ? auditPath.split('/').pop() : '(unsaved)';
      setStatus(`${I18N[currentLang]['status-done']} · 🟠 系統輸出自查提出 ${auditCount} entries → ${file}`);
    } else {
      setStatus(I18N[currentLang]['status-done']);
    }
    // v8.25 UX — collapse 4-panel grid into single council answer bubble
    _stopTrinityStatusBar();
    _collapseTrinityIntoBubble(data && data._mode_id);
    // v8.11 — finalize current turn into __convHistory (after all events captured)
    _finalizeTurn();
    // Coordinate-map viz: render 3D map from captured stage2/stage3
    renderCoordinateMap();
    // Live mode: signal done so loop can proceed
    document.dispatchEvent(new Event('_trinityDone'));
  }
  else if (type === 'error') {
    setStatus(`${I18N[currentLang]['status-error']}: ${data.message}`, true);
  }
}

// v8.37 — render the dev-only physics compute line on top of council body.
// Mounts BEFORE the council #output-council so the line is visible at a glance.
// Honesty contract:
//   - Label "物理計算 dev-only · 唔影響 LLM 判斷" always visible (server-provided string)
//   - Expanding shows 5 COMPUTED + Landauer + 2 ANALOGY metrics
//   - ANALOGY caveats are NEVER collapsed away — shown inline on expand
function renderPhysicsLine(modeId, data) {
  const council = getModeElement(modeId, 'output-council');
  if (!council) return;
  // Find or create wrapper above council body
  const parent = council.parentElement;
  if (!parent) return;
  let wrap = parent.querySelector('.physics-compute-line[data-mode-id="' + (modeId || '_default') + '"]');
  if (wrap) wrap.remove();   // refresh on new event
  wrap = document.createElement('details');
  wrap.className = 'physics-compute-line';
  wrap.dataset.modeId = modeId || '_default';
  const label = data.display_label || '物理計算 dev-only · 唔影響 LLM 判斷';
  const metrics = Array.isArray(data.metrics) ? data.metrics : [];
  const rows = metrics.map(m => {
    const lbl = escapeHtml(m.label || '');
    const labelClass = ({
      'COMPUTED':     'physics-tag-computed',
      'PHYSICAL_LAW': 'physics-tag-law',
      'CALIBRATION':  'physics-tag-cal',
      'ANALOGY':      'physics-tag-analogy',
    })[m.label] || '';
    const valDisplay = (typeof m.value === 'number' && Math.abs(m.value) < 1e-10 && m.value !== 0)
      ? m.value.toExponential(3)
      : escapeHtml(String(m.value));
    const caveat = m.caveat
      ? `<div class="physics-caveat">⚠ ${escapeHtml(m.caveat)}</div>`
      : '';
    return `
      <div class="physics-row">
        <span class="physics-tag ${labelClass}">${lbl}</span>
        <span class="physics-name">${escapeHtml(m.name)}</span>
        <span class="physics-value">${valDisplay}</span>
        <span class="physics-unit">${escapeHtml(m.unit || '')}</span>
        <div class="physics-method">${escapeHtml(m.method || '')}</div>
        ${caveat}
      </div>
    `;
  }).join('');
  wrap.innerHTML = `
    <summary class="physics-summary">🧮 ${escapeHtml(label)}</summary>
    <div class="physics-body">${rows}</div>
  `;
  // Insert right BEFORE council body, so user sees this line on top of council
  parent.insertBefore(wrap, council);
}

function setStatus(text, isError = false, spinning = false) {
  const el = document.getElementById('status-text');
  el.textContent = text;
  el.style.color = isError ? 'var(--son)' : '';
  document.getElementById('status-spinner').classList.toggle('hidden', !spinning);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
}

// ═══════════════════════════════════════════════════════════════
// FT-2: File tree + CodeMirror 6 editor
// ═══════════════════════════════════════════════════════════════

const LAYER_LABELS = {
  canonical: { label: '📂 Canonical', cls: 'layer-canonical', readonly_note: '🔒 唯讀' },
  prompts:   { label: '📂 Prompts',   cls: 'layer-prompts',   readonly_note: '⚠ 受審計' },
  personal:  { label: '📂 Personal Memory', cls: 'layer-personal', readonly_note: '✓ 個人區' },
  config:    { label: '📂 Config',    cls: 'layer-config',    readonly_note: '⚠ 受審計' },
};

let editorView = null;       // CodeMirror EditorView instance
let editorCurrent = null;    // { path, originalContent, info }
let editorDirty = false;

function setupSidebarTabs() {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const tab = btn.dataset.tab;
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b === btn));
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.toggle('active', p.id === `tab-${tab}`));
      // v8.31 — lazy-load skills on first activation
      if (tab === 'skills' && !__skillsLoaded) {
        __skillsLoaded = true;
        loadSkills();
      }
      if (tab === 'vessel' && !__vesselLoaded) {
        __vesselLoaded = true;
        loadVesselPane();
      }
      if (tab === 'world' && !__worldLoaded) {
        __worldLoaded = true;
        loadWorldPane();
      }
    });
  });
}

// v8.6x — Vessel state tab: hardware identity + location + calendar + notes.
let __vesselLoaded = false;
let __lastVesselPayload = null;

function setupVesselPane() {
  document.getElementById('vessel-refresh')?.addEventListener('click', () => loadVesselPane());
  document.getElementById('vessel-use-browser-location')?.addEventListener('click', handleUseBrowserLocation);
  document.getElementById('vessel-save-location')?.addEventListener('click', handleSaveVesselLocation);
  document.getElementById('vessel-add-note')?.addEventListener('click', handleAddVesselNote);
  document.getElementById('vessel-add-event')?.addEventListener('click', handleAddVesselEvent);
}

async function vesselFetch(url, options = {}) {
  const headers = Object.assign({ 'Content-Type': 'application/json' }, options.headers || {});
  const response = await fetch(url, Object.assign({}, options, { headers }));
  const text = await response.text();
  let data = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch (_e) {
      data = { detail: text };
    }
  }
  if (!response.ok || data.ok === false) {
    throw new Error(data.detail || data.error || `HTTP ${response.status}`);
  }
  return data;
}

async function loadVesselPane(options = {}) {
  const quiet = options.quiet === true;
  if (!quiet) setVesselStatus('載入載具狀態⋯');
  try {
    const data = await vesselFetch('/api/vessel/state');
    __lastVesselPayload = data;
    renderVesselPane(data);
    setVesselStatus('');
  } catch (e) {
    __vesselLoaded = false;
    setVesselStatus(`載入失敗：${String(e.message || e)}`, true);
    const eventsEl = document.getElementById('vessel-events');
    if (eventsEl) eventsEl.innerHTML = '<div class="vessel-empty">後端未提供 /api/vessel/state。</div>';
  }
}

function renderVesselPane(payload) {
  const state = payload.state || {};
  const profile = payload.profile || {};
  const gaps = Array.isArray(payload.hardware_gaps) ? payload.hardware_gaps : [];
  const capabilities = Array.isArray(profile.capabilities) ? profile.capabilities : [];
  const summaryEl = document.getElementById('vessel-summary');
  if (summaryEl) {
    const counts = profile.device_counts || {};
    const deviceCount = Array.isArray(profile.devices)
      ? profile.devices.length
      : Object.values(counts).reduce((sum, value) => sum + (Number(value) || 0), 0);
    summaryEl.textContent = `${capabilities.length} capabilities · ${deviceCount} devices · ${gaps.length} hardware gaps`;
  }

  renderVesselMap(state.location || null);
  renderVesselEvents(Array.isArray(state.calendar_events) ? state.calendar_events : []);
  renderVesselNotes(Array.isArray(state.notes) ? state.notes : []);
}

function renderVesselMap(location) {
  const mapEl = document.getElementById('vessel-map');
  if (!mapEl) return;
  if (!location || typeof location.lat !== 'number' || typeof location.lon !== 'number') {
    mapEl.innerHTML = '<div class="vessel-map-empty">未設定位置</div>';
    return;
  }

  const lat = Number(location.lat);
  const lon = Number(location.lon);
  const delta = 0.01;
  const bbox = [
    (lon - delta).toFixed(6),
    (lat - delta).toFixed(6),
    (lon + delta).toFixed(6),
    (lat + delta).toFixed(6),
  ].join('%2C');
  const marker = `${lat.toFixed(6)}%2C${lon.toFixed(6)}`;
  const src = `https://www.openstreetmap.org/export/embed.html?bbox=${bbox}&layer=mapnik&marker=${marker}`;
  const label = location.label || 'current vessel location';
  const source = location.source || 'manual';
  const updated = location.updated_at ? formatVesselDateTime(location.updated_at) : '';
  mapEl.innerHTML = `
    <iframe class="vessel-map-frame" src="${src}" loading="lazy" referrerpolicy="no-referrer-when-downgrade" title="Vessel map"></iframe>
    <div class="vessel-map-meta">
      <span>${escapeHtml(label)}</span>
      <a href="https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=15/${lat}/${lon}" target="_blank" rel="noreferrer">OpenStreetMap</a>
    </div>
    <div class="vessel-map-meta muted">${lat.toFixed(6)}, ${lon.toFixed(6)} · ${escapeHtml(source)}${updated ? ` · ${escapeHtml(updated)}` : ''}</div>
  `;

  const latInput = document.getElementById('vessel-lat');
  const lonInput = document.getElementById('vessel-lon');
  const labelInput = document.getElementById('vessel-place-label');
  if (latInput) latInput.value = lat.toFixed(6);
  if (lonInput) lonInput.value = lon.toFixed(6);
  if (labelInput && location.label) labelInput.value = location.label;
}

function renderVesselEvents(events) {
  const list = document.getElementById('vessel-events');
  if (!list) return;
  if (!events.length) {
    list.innerHTML = '<div class="vessel-empty">未有行事曆承諾</div>';
    return;
  }
  list.innerHTML = events.slice(0, 20).map(event => {
    const title = event.title || '(untitled)';
    const start = event.start ? formatVesselDateTime(event.start) : '未定時間';
    const source = event.source || 'manual';
    return `
      <div class="vessel-item">
        <div class="vessel-item-title">${escapeHtml(title)}</div>
        <div class="vessel-item-meta">${escapeHtml(start)} · ${escapeHtml(source)}</div>
        ${event.description ? `<div class="vessel-item-body">${escapeHtml(event.description)}</div>` : ''}
      </div>
    `;
  }).join('');
}

function renderVesselNotes(notes) {
  const list = document.getElementById('vessel-notes');
  if (!list) return;
  if (!notes.length) {
    list.innerHTML = '<div class="vessel-empty">未有系統筆記</div>';
    return;
  }
  list.innerHTML = notes.slice(0, 20).map(note => {
    const title = note.title || '(untitled)';
    const updated = note.updated_at || note.created_at || '';
    const noteId = note.id || '';
    return `
      <div class="vessel-item" data-note-id="${escapeAttr(noteId)}">
        <div class="vessel-item-row">
          <div class="vessel-item-title">${escapeHtml(title)}</div>
          <button class="vessel-icon-btn" type="button" data-delete-note="${escapeAttr(noteId)}" title="刪除筆記">×</button>
        </div>
        <div class="vessel-item-meta">${escapeHtml(formatVesselDateTime(updated))}</div>
        ${note.body ? `<div class="vessel-item-body">${escapeHtml(note.body)}</div>` : ''}
      </div>
    `;
  }).join('');
  list.querySelectorAll('[data-delete-note]').forEach(btn => {
    btn.addEventListener('click', () => handleDeleteVesselNote(btn.dataset.deleteNote || ''));
  });
}

function setVesselStatus(message, isError = false) {
  const status = document.getElementById('vessel-location-status');
  if (!status) return;
  status.textContent = message || '';
  status.classList.toggle('error', Boolean(isError));
}

function handleUseBrowserLocation() {
  if (!navigator.geolocation) {
    setVesselStatus('瀏覽器未提供定位能力。', true);
    return;
  }
  setVesselStatus('等待瀏覽器定位授權⋯');
  navigator.geolocation.getCurrentPosition(
    position => {
      const coords = position.coords || {};
      const latInput = document.getElementById('vessel-lat');
      const lonInput = document.getElementById('vessel-lon');
      const labelInput = document.getElementById('vessel-place-label');
      if (latInput) latInput.value = Number(coords.latitude).toFixed(6);
      if (lonInput) lonInput.value = Number(coords.longitude).toFixed(6);
      if (labelInput && !labelInput.value.trim()) labelInput.value = 'browser location';
      setVesselStatus('已填入瀏覽器定位；按「保存位置」先會寫入系統。');
    },
    error => setVesselStatus(`定位失敗：${error.message || error.code}`, true),
    { enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 }
  );
}

async function handleSaveVesselLocation() {
  const lat = Number(document.getElementById('vessel-lat')?.value);
  const lon = Number(document.getElementById('vessel-lon')?.value);
  const label = document.getElementById('vessel-place-label')?.value.trim() || '';
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    setVesselStatus('請輸入有效 lat / lon。', true);
    return;
  }
  setVesselStatus('保存位置中⋯');
  try {
    await vesselFetch('/api/vessel/location', {
      method: 'POST',
      body: JSON.stringify({ lat, lon, label, source: 'manual_ui' }),
    });
    await loadVesselPane({ quiet: true });
    setVesselStatus('位置已保存，之後 pipeline context 會見到呢個位置。');
  } catch (e) {
    setVesselStatus(`保存失敗：${String(e.message || e)}`, true);
  }
}

async function handleAddVesselNote() {
  const titleEl = document.getElementById('vessel-note-title');
  const bodyEl = document.getElementById('vessel-note-body');
  const title = titleEl?.value.trim() || '';
  const body = bodyEl?.value.trim() || '';
  if (!title && !body) {
    setVesselStatus('筆記需要標題或內容。', true);
    return;
  }
  setVesselStatus('新增筆記中⋯');
  try {
    await vesselFetch('/api/vessel/notes', {
      method: 'POST',
      body: JSON.stringify({ title, body, source: 'manual_ui' }),
    });
    if (titleEl) titleEl.value = '';
    if (bodyEl) bodyEl.value = '';
    await loadVesselPane({ quiet: true });
    setVesselStatus('筆記已加入。');
  } catch (e) {
    setVesselStatus(`新增筆記失敗：${String(e.message || e)}`, true);
  }
}

async function handleDeleteVesselNote(noteId) {
  if (!noteId) return;
  setVesselStatus('刪除筆記中⋯');
  try {
    await vesselFetch(`/api/vessel/notes/${encodeURIComponent(noteId)}`, { method: 'DELETE' });
    await loadVesselPane({ quiet: true });
    setVesselStatus('筆記已刪除。');
  } catch (e) {
    setVesselStatus(`刪除筆記失敗：${String(e.message || e)}`, true);
  }
}

async function handleAddVesselEvent() {
  const titleEl = document.getElementById('vessel-event-title');
  const startEl = document.getElementById('vessel-event-start');
  const title = titleEl?.value.trim() || '';
  const start = startEl?.value || '';
  if (!title || !start) {
    setVesselStatus('行事曆需要事件同開始時間。', true);
    return;
  }
  setVesselStatus('加入行事曆中⋯');
  try {
    await vesselFetch('/api/vessel/calendar/events', {
      method: 'POST',
      body: JSON.stringify({ title, start, source: 'manual_ui' }),
    });
    if (titleEl) titleEl.value = '';
    if (startEl) startEl.value = '';
    await loadVesselPane({ quiet: true });
    setVesselStatus('行事曆承諾已加入。');
  } catch (e) {
    setVesselStatus(`加入行事曆失敗：${String(e.message || e)}`, true);
  }
}

function formatVesselDateTime(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString([], {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

// v8.31 — Skills tab loader + renderer
// World simulation tab: deterministic graph + scenario compare.
let __worldLoaded = false;
let __lastWorldPayload = null;

function setupWorldPane() {
  window.WorldAtlas?.setup();
  document.getElementById('world-refresh')?.addEventListener('click', () => loadWorldPane());
  document.getElementById('world-run')?.addEventListener('click', () => runWorldSimulationFromPane());
  document.getElementById('world-forecast')?.addEventListener('click', () => runWorldForecastFromPane());
  document.getElementById('world-geotimeline')?.addEventListener('click', () => runWorldGeoTimelineFromPane());
  document.getElementById('world-live-news')?.addEventListener('click', () => runWorldGeoTimelineFromPane({ autoNews: true }));
  document.getElementById('world-open-atlas')?.addEventListener('click', async () => {
    if (!window.WorldAtlas?.hasPayload()) {
      try {
        await runWorldGeoTimelineFromPane();
      } catch (_e) {
        return;
      }
    }
    window.WorldAtlas?.open();
  });
  document.getElementById('world-use-chat')?.addEventListener('click', () => {
    const chat = document.getElementById('user-input')?.value.trim() || '';
    const input = document.getElementById('world-input');
    if (input && chat) input.value = chat;
  });
}

function activateSidebarTab(tab) {
  const safeTab = window.CSS && CSS.escape ? CSS.escape(tab) : String(tab).replace(/"/g, '\\"');
  const btn = document.querySelector(`.tab-btn[data-tab="${safeTab}"]`);
  if (btn) {
    btn.click();
    return;
  }
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.toggle('active', p.id === `tab-${tab}`));
}

function isExplicitWorldCommand(input) {
  return /^\/(world|simulate|map|scenario|coordinate|forecast|geotimeline|timeline)\b/i.test(String(input || '').trim());
}

function stripWorldCommand(input) {
  const raw = String(input || '').trim();
  return raw.replace(/^\/(world|simulate|map|scenario|coordinate|forecast|geotimeline|timeline)\b\s*/i, '').trim() || raw;
}

function isExplicitForecastCommand(input) {
  return /^\/forecast\b/i.test(String(input || '').trim());
}

function isExplicitGeoTimelineCommand(input) {
  return /^\/(geotimeline|timeline)\b/i.test(String(input || '').trim());
}

async function worldRouteAdvice(input) {
  if (isExplicitWorldCommand(input)) return { should_trigger: true, explicit: true };
  try {
    const data = await vesselFetch(`/api/world/trigger?query=${encodeURIComponent(input)}`);
    return data.trigger || {};
  } catch (_e) {
    return { should_trigger: false };
  }
}

async function loadWorldPane(options = {}) {
  const quiet = options.quiet === true;
  const query = document.getElementById('world-input')?.value.trim() || '';
  if (!quiet) setWorldStatus('Loading world state...');
  try {
    const data = await vesselFetch(`/api/world/state?query=${encodeURIComponent(query)}`);
    __lastWorldPayload = data;
    renderWorldPane(data);
    setWorldStatus('');
  } catch (e) {
    __worldLoaded = false;
    setWorldStatus(`World state failed: ${String(e.message || e)}`, true);
  }
}

async function runWorldSimulationFromPane() {
  const text = document.getElementById('world-input')?.value.trim() || '';
  await runWorldSimulation(text, { showStatus: true });
}

async function runWorldSimulation(inputText, options = {}) {
  const text = stripWorldCommand(inputText || '');
  if (options.showStatus !== false) setWorldStatus('Simulating world state...');
  const data = await vesselFetch('/api/world/simulate', {
    method: 'POST',
    body: JSON.stringify({ input_text: text, horizon: 'short' }),
  });
  __lastWorldPayload = data;
  renderWorldPane(data);
  setWorldStatus('Simulation ready.');
  return data;
}

async function runWorldForecastFromPane() {
  const text = document.getElementById('world-input')?.value.trim() || '';
  await runWorldForecast(text, { showStatus: true });
}

function parseWorldNewsSources() {
  const raw = document.getElementById('world-news-sources')?.value.trim() || '';
  if (!raw) return [];
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (e) {
    throw new Error(`News sources JSON invalid: ${String(e.message || e)}`);
  }
  if (Array.isArray(parsed)) return parsed;
  if (Array.isArray(parsed.news_sources)) return parsed.news_sources;
  if (Array.isArray(parsed.sources)) return parsed.sources;
  throw new Error('News sources must be an array, or an object with sources/news_sources.');
}

async function runWorldForecast(inputText, options = {}) {
  const text = stripWorldCommand(inputText || '');
  const newsSources = parseWorldNewsSources();
  if (options.showStatus !== false) setWorldStatus('Calculating forecast scenarios...');
  const data = await vesselFetch('/api/world/forecast', {
    method: 'POST',
    body: JSON.stringify({ input_text: text, horizon: 'medium', news_sources: newsSources }),
  });
  __lastWorldPayload = data;
  renderWorldForecastPane(data);
  setWorldStatus('Forecast ready.');
  return data;
}

async function runWorldGeoTimelineFromPane(options = {}) {
  const text = document.getElementById('world-input')?.value.trim() || '';
  const button = document.getElementById(options.autoNews ? 'world-live-news' : 'world-geotimeline');
  if (button) button.disabled = true;
  try {
    return await runWorldGeoTimeline(text, { showStatus: true, ...options });
  } finally {
    if (button) button.disabled = false;
  }
}

async function runWorldGeoTimeline(inputText, options = {}) {
  const text = stripWorldCommand(inputText || '');
  const newsSources = parseWorldNewsSources();
  const autoNews = options.autoNews === true;
  if (options.showStatus !== false) {
    setWorldStatus(autoNews ? 'Fetching audited news and revising forecast...' : 'Building real-coordinate timeline...');
  }
  const data = await vesselFetch('/api/world/geotimeline', {
    method: 'POST',
    body: JSON.stringify({
      input_text: text,
      horizon: 'medium',
      news_sources: newsSources,
      auto_news: autoNews,
      max_news: 6,
      persist_revision: true,
    }),
  });
  __lastWorldPayload = data;
  renderWorldGeoTimelinePane(data);
  const liveCount = Number(data.live_news?.fetched_count) || 0;
  setWorldStatus(autoNews ? `Live correction ready · ${liveCount} sources fetched.` : 'Geo timeline ready.');
  return data;
}

async function handleWorldCommand(input, inputEl) {
  const text = stripWorldCommand(input);
  const worldInput = document.getElementById('world-input');
  if (worldInput) worldInput.value = text;
  __worldLoaded = true;
  activateSidebarTab('world');

  window.__runTrinityActive = true;
  const runBtn = document.getElementById('run-btn');
  if (runBtn) {
    runBtn.disabled = true;
    runBtn.textContent = I18N[currentLang]['run-btn-running'];
  }
  if (inputEl) inputEl.value = '';

  try {
    _resetCouncilBubble();
    const data = isExplicitGeoTimelineCommand(input)
      ? await runWorldGeoTimeline(text, { showStatus: true })
      : isExplicitForecastCommand(input)
        ? await runWorldForecast(text, { showStatus: true })
        : await runWorldSimulation(text, { showStatus: true });
    if (isExplicitGeoTimelineCommand(input)) {
      renderWorldGeoTimelineAnswer(text, data);
      setStatus('World geo timeline complete.');
    } else if (isExplicitForecastCommand(input)) {
      renderWorldForecastAnswer(text, data);
      setStatus('World forecast complete.');
    } else {
      renderWorldAnswer(text, data);
      setStatus('World simulation complete.');
    }
  } catch (e) {
    const label = isExplicitGeoTimelineCommand(input)
      ? 'World geo timeline'
      : isExplicitForecastCommand(input)
        ? 'World forecast'
        : 'World simulation';
    setWorldStatus(`${label} failed: ${String(e.message || e)}`, true);
    setStatus(`${label} failed: ${String(e.message || e)}`, true);
  } finally {
    if (runBtn) {
      runBtn.disabled = false;
      runBtn.textContent = I18N[currentLang]['run-btn'];
    }
    window.__runTrinityActive = false;
  }
}

function renderWorldPane(payload) {
  window.WorldAtlas?.showSimulation();
  const world = payload.world || {};
  const entities = Array.isArray(world.entities) ? world.entities : [];
  const relations = Array.isArray(world.relations) ? world.relations : [];
  const forces = Array.isArray(world.forces) ? world.forces : [];
  const scenarios = Array.isArray(payload.scenarios) ? payload.scenarios : [];
  const evaluation = payload.evaluation || {};
  const summary = document.getElementById('world-summary');
  if (summary) {
    const rec = evaluation.recommended_scenario ? ` · rec ${evaluation.recommended_scenario}` : '';
    summary.textContent = `${entities.length} entities · ${relations.length} relations · ${forces.length} forces${rec}`;
  }

  drawWorldCanvas(world);
  renderWorldLegend(entities);
  renderWorldScenarios(scenarios, evaluation, forces);

  const raw = document.getElementById('world-raw');
  if (raw) raw.textContent = JSON.stringify(payload, null, 2);
}

function renderWorldForecastPane(payload) {
  window.WorldAtlas?.showSimulation();
  const counts = payload.evidence_counts || {};
  const forecast = payload.forecast || {};
  const newsFilter = payload.news_filter || {};
  const scenarios = Array.isArray(payload.scenarios) ? payload.scenarios : [];
  const summary = document.getElementById('world-summary');
  if (summary) {
    const uncertainty = Math.round((Number(forecast.uncertainty) || 0) * 100);
    const primary = forecast.primary_scenario || 'none';
    summary.textContent = `${counts.total ?? 0} evidence · ${primary} · uncertainty ${uncertainty}%`;
  }
  renderWorldForecastScenarios(scenarios, forecast, payload.signals || {}, newsFilter, payload.warnings || []);

  const raw = document.getElementById('world-raw');
  if (raw) raw.textContent = JSON.stringify(payload, null, 2);
}

function renderWorldGeoTimelinePane(payload) {
  const events = Array.isArray(payload.events) ? payload.events : [];
  const links = Array.isArray(payload.links) ? payload.links : [];
  const correction = payload.forecast_correction || {};
  const corrected = correction.corrected || {};
  const summary = document.getElementById('world-summary');
  if (summary) {
    summary.textContent = `${events.length} geo events · ${links.length} links · ${corrected.primary_scenario || 'no forecast'}`;
  }
  const interactiveRendered = window.WorldAtlas?.render(payload) === true;
  if (!interactiveRendered) {
    window.WorldAtlas?.showSimulation();
    drawWorldGeoMap(events, links);
  }
  renderWorldGeoLegend(events);
  renderWorldGeoTimelineList(payload);

  const raw = document.getElementById('world-raw');
  if (raw) raw.textContent = JSON.stringify(payload, null, 2);
}

function renderWorldLegend(entities) {
  const legend = document.getElementById('world-legend');
  if (!legend) return;
  const kinds = Array.from(new Set((entities || []).map(e => e.kind || 'entity'))).slice(0, 8);
  legend.innerHTML = kinds.map(kind => {
    const color = worldColorForKind(kind);
    return `<span class="world-chip"><span class="world-dot" style="background:${color}"></span>${escapeHtml(kind)}</span>`;
  }).join('');
}

function renderWorldGeoLegend(events) {
  const legend = document.getElementById('world-legend');
  if (!legend) return;
  const types = Array.from(new Set((events || []).map(e => e.type || 'event'))).slice(0, 8);
  legend.innerHTML = types.map(type => {
    const color = worldGeoColorForType(type);
    return `<span class="world-chip"><span class="world-dot" style="background:${color}"></span>${escapeHtml(type)}</span>`;
  }).join('');
}

function renderWorldScenarios(scenarios, evaluation, forces) {
  const list = document.getElementById('world-scenarios');
  if (!list) return;
  const forceHtml = (forces || []).map(force => {
    const value = Math.max(0, Math.min(1, Number(force.value) || 0));
    return `
      <div class="world-force">
        <span>${escapeHtml(force.label || force.id || 'force')}</span>
        <span class="world-force-bar"><span class="world-force-fill" style="width:${Math.round(value * 100)}%"></span></span>
        <span>${Math.round(value * 100)}%</span>
      </div>
    `;
  }).join('');

  const scenarioHtml = (scenarios || []).map(scenario => {
    const recommended = scenario.id === evaluation.recommended_scenario;
    const delta = scenario.delta || {};
    const deltas = Object.entries(delta).map(([key, value]) => {
      const num = Number(value) || 0;
      const sign = num > 0 ? '+' : '';
      return `<span class="world-delta">${escapeHtml(key)} ${sign}${escapeHtml(num.toFixed ? num.toFixed(2) : String(value))}</span>`;
    }).join('');
    return `
      <div class="world-scenario ${recommended ? 'recommended' : ''}">
        <div class="world-scenario-head">
          <div class="world-scenario-title">${escapeHtml(scenario.label || scenario.id || 'scenario')}</div>
          <span class="world-risk">${recommended ? 'recommended · ' : ''}${escapeHtml(scenario.risk || 'risk?')}</span>
        </div>
        <div class="world-scenario-body">${escapeHtml(scenario.summary || '')}</div>
        <div class="world-deltas">${deltas}</div>
      </div>
    `;
  }).join('');

  list.innerHTML = forceHtml + (scenarioHtml || '<div class="vessel-empty">Run simulation to compare scenarios.</div>');
}

function renderWorldGeoTimelineList(payload) {
  const list = document.getElementById('world-scenarios');
  if (!list) return;
  const events = Array.isArray(payload.events) ? payload.events : [];
  const links = Array.isArray(payload.links) ? payload.links : [];
  const correction = payload.forecast_correction || {};
  const baseline = correction.baseline || {};
  const corrected = correction.corrected || {};
  const deltas = correction.scenario_deltas || {};
  const newsFilter = payload.news_filter || {};
  const deltaHtml = Object.entries(deltas).map(([key, value]) => {
    const num = Number(value) || 0;
    const sign = num > 0 ? '+' : '';
    const cls = Math.abs(num) >= 0.02 ? 'world-delta warn' : 'world-delta';
    return `<span class="${cls}">${escapeHtml(key)} ${sign}${escapeHtml(num.toFixed(3))}</span>`;
  }).join('');
  const correctionHtml = `
    <div class="world-scenario recommended">
      <div class="world-scenario-head">
        <div class="world-scenario-title">Forecast correction</div>
        <span class="world-risk">${escapeHtml(correction.correction_strength || 'weak')} · ${newsFilter.source_count ?? 0} news · ${newsFilter.coordinate_count ?? 0} coords</span>
      </div>
      <div class="world-scenario-meta">${escapeHtml(baseline.primary_scenario || 'none')} → ${escapeHtml(corrected.primary_scenario || 'none')} · max shift ${Number(correction.max_absolute_shift || 0).toFixed(4)}</div>
      <div class="world-scenario-body">${escapeHtml(corrected.interpretation || 'No corrected forecast available.')}</div>
      <div class="world-deltas">${deltaHtml || '<span class="world-delta">no scenario shift</span>'}</div>
    </div>
  `;

  const timelineHtml = events.map(event => {
    const projected = event.projected ? 'projected · ' : '';
    const refs = (links || []).filter(link => link.source === event.id || link.target === event.id).length;
    return `
      <div class="world-scenario world-event-card ${event.projected ? 'recommended' : ''}" data-event-id="${escapeHtml(event.id || '')}" role="button" tabindex="0">
        <div class="world-scenario-head">
          <div class="world-scenario-title">${escapeHtml(event.date || '')} · ${escapeHtml(event.title || event.id)}</div>
          <span class="world-risk">${projected}${escapeHtml(event.type || 'event')}</span>
        </div>
        <div class="world-scenario-body">${escapeHtml(event.summary || event.location || '')}</div>
        <div class="world-scenario-meta">${escapeHtml(event.location || '')} · ${Number(event.lat).toFixed(2)}, ${Number(event.lon).toFixed(2)} · ${refs} links</div>
      </div>
    `;
  }).join('');
  list.innerHTML = correctionHtml + (timelineHtml || '<div class="vessel-empty">No geo events for this query.</div>');
  list.querySelectorAll('.world-event-card[data-event-id]').forEach(card => {
    const select = () => window.WorldAtlas?.selectEvent(card.dataset.eventId, { pan: true });
    card.addEventListener('click', select);
    card.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        select();
      }
    });
  });
}

function renderWorldForecastScenarios(scenarios, forecast, signals, newsFilter, warnings) {
  const list = document.getElementById('world-scenarios');
  if (!list) return;
  const signalHtml = Object.entries(signals || {}).map(([key, value]) => {
    const pct = Math.max(0, Math.min(100, Math.round((Number(value) || 0) * 100)));
    return `
      <div class="world-force">
        <span>${escapeHtml(key)}</span>
        <span class="world-force-bar"><span class="world-force-fill" style="width:${pct}%"></span></span>
        <span>${pct}%</span>
      </div>
    `;
  }).join('');

  const scenarioHtml = (scenarios || []).map(scenario => {
    const primary = scenario.id === forecast.primary_scenario;
    const pct = Math.round((Number(scenario.relative_weight) || 0) * 100);
    const drivers = (scenario.drivers || []).map(d => `<span class="world-delta">${escapeHtml(d)}</span>`).join('');
    return `
      <div class="world-scenario ${primary ? 'recommended' : ''}">
        <div class="world-scenario-head">
          <div class="world-scenario-title">${escapeHtml(scenario.label || scenario.id || 'scenario')}</div>
          <span class="world-risk">${primary ? 'primary · ' : ''}${escapeHtml(scenario.band || 'band?')} · ${pct}%</span>
        </div>
        <div class="world-scenario-body">${escapeHtml((primary ? forecast.interpretation : '') || 'Scenario weight from filtered evidence.')}</div>
        <div class="world-deltas">${drivers || '<span class="world-delta">no strong driver</span>'}</div>
      </div>
    `;
  }).join('');

  const newsFlags = (newsFilter.flags || []).map(flag => `<span class="world-delta warn">${escapeHtml(flag)}</span>`).join('');
  const warningHtml = (warnings || []).map(flag => `<span class="world-delta warn">${escapeHtml(flag)}</span>`).join('');
  const filterHtml = `
    <div class="world-scenario">
      <div class="world-scenario-head">
        <div class="world-scenario-title">Evidence filter</div>
        <span class="world-risk">${newsFilter.source_count ?? 0} news · ${newsFilter.coordinate_count ?? 0} coords</span>
      </div>
      <div class="world-deltas">${newsFlags || '<span class="world-delta">news filter clear</span>'}${warningHtml}</div>
    </div>
  `;

  list.innerHTML = signalHtml + filterHtml + (scenarioHtml || '<div class="vessel-empty">Run forecast to calculate scenario weights.</div>');
}

function drawWorldCanvas(world) {
  const canvas = document.getElementById('world-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  const rect = canvas.getBoundingClientRect();
  const width = Math.max(280, Math.floor(rect.width || canvas.clientWidth || 320));
  const height = Math.max(220, Math.floor(rect.height || 240));
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.floor(width * dpr);
  canvas.height = Math.floor(height * dpr);
  canvas.style.height = `${height}px`;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);

  ctx.fillStyle = '#070a0f';
  ctx.fillRect(0, 0, width, height);
  drawWorldGrid(ctx, width, height);

  const entities = Array.isArray(world.entities) ? world.entities : [];
  const relations = Array.isArray(world.relations) ? world.relations : [];
  const byId = new Map(entities.map(entity => [entity.id, entity]));
  const project = entity => {
    const p = entity.position || {};
    const x = Number(p.x) || 0;
    const y = Number(p.y) || 0;
    const z = Number(p.z) || 0;
    const perspective = 1 / (1 + Math.max(-4, z + 7) * 0.045);
    return {
      x: width / 2 + x * 22 * perspective,
      y: height / 2 - y * 22 * perspective - z * 6,
      z,
      size: Math.max(4, Math.min(14, (Number(entity.weight) || 1) * 4 * perspective)),
    };
  };

  ctx.lineWidth = 1;
  relations.forEach(rel => {
    const src = byId.get(rel.source);
    const dst = byId.get(rel.target);
    if (!src || !dst) return;
    const a = project(src);
    const b = project(dst);
    const alpha = Math.max(0.18, Math.min(0.65, Number(rel.weight) || 0.3));
    ctx.strokeStyle = `rgba(145,160,185,${alpha})`;
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
  });

  entities.slice().sort((a, b) => {
    const az = Number((a.position || {}).z) || 0;
    const bz = Number((b.position || {}).z) || 0;
    return az - bz;
  }).forEach(entity => {
    const p = project(entity);
    const color = worldColorForKind(entity.kind);
    ctx.fillStyle = color;
    ctx.strokeStyle = 'rgba(255,255,255,.65)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = 'rgba(236,240,248,.88)';
    ctx.font = '10px ui-monospace, SFMono-Regular, Consolas, monospace';
    const label = String(entity.label || entity.id || '').slice(0, 18);
    ctx.fillText(label, p.x + p.size + 4, p.y + 3);
  });
}

function drawWorldGeoMap(events, links) {
  const canvas = document.getElementById('world-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  const rect = canvas.getBoundingClientRect();
  const width = Math.max(280, Math.floor(rect.width || canvas.clientWidth || 320));
  const height = Math.max(220, Math.floor(rect.height || 240));
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.floor(width * dpr);
  canvas.height = Math.floor(height * dpr);
  canvas.style.height = `${height}px`;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);

  ctx.fillStyle = '#06101a';
  ctx.fillRect(0, 0, width, height);
  drawGeoBaseMap(ctx, width, height);

  const project = event => ({
    x: ((Number(event.lon) + 180) / 360) * width,
    y: ((90 - Number(event.lat)) / 180) * height,
  });
  const byId = new Map((events || []).map(event => [event.id, event]));

  (links || []).forEach(link => {
    const a = byId.get(link.source);
    const b = byId.get(link.target);
    if (!a || !b) return;
    const pa = project(a);
    const pb = project(b);
    const alpha = Math.max(0.15, Math.min(0.72, Number(link.weight) || 0.3));
    ctx.strokeStyle = `rgba(145,190,255,${alpha})`;
    ctx.lineWidth = 1.1;
    ctx.beginPath();
    const mx = (pa.x + pb.x) / 2;
    const my = (pa.y + pb.y) / 2 - Math.min(34, Math.abs(pa.x - pb.x) * 0.05);
    ctx.moveTo(pa.x, pa.y);
    ctx.quadraticCurveTo(mx, my, pb.x, pb.y);
    ctx.stroke();
  });

  (events || []).forEach(event => {
    const p = project(event);
    const color = worldGeoColorForType(event.type);
    const projected = Boolean(event.projected);
    const size = projected ? 7 : Math.max(4, Math.min(8, 4 + (Number(event.confidence) || 0.5) * 4));
    ctx.fillStyle = color;
    ctx.strokeStyle = projected ? '#ffffff' : 'rgba(255,255,255,.7)';
    ctx.lineWidth = projected ? 1.8 : 1;
    ctx.beginPath();
    if (projected) {
      ctx.moveTo(p.x, p.y - size);
      ctx.lineTo(p.x + size, p.y);
      ctx.lineTo(p.x, p.y + size);
      ctx.lineTo(p.x - size, p.y);
      ctx.closePath();
    } else {
      ctx.arc(p.x, p.y, size, 0, Math.PI * 2);
    }
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = 'rgba(236,240,248,.9)';
    ctx.font = '10px ui-monospace, SFMono-Regular, Consolas, monospace';
    const label = String(event.title || event.id || '').slice(0, 22);
    ctx.fillText(label, Math.min(width - 110, p.x + size + 4), Math.max(12, p.y + 3));
  });
}

function drawGeoBaseMap(ctx, width, height) {
  ctx.strokeStyle = 'rgba(255,255,255,.08)';
  ctx.lineWidth = 1;
  for (let lon = -180; lon <= 180; lon += 60) {
    const x = ((lon + 180) / 360) * width;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();
  }
  for (let lat = -60; lat <= 60; lat += 30) {
    const y = ((90 - lat) / 180) * height;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }

  ctx.strokeStyle = 'rgba(255,120,86,.34)';
  ctx.beginPath();
  ctx.moveTo(width / 2, 0);
  ctx.lineTo(width / 2, height);
  ctx.moveTo(0, height / 2);
  ctx.lineTo(width, height / 2);
  ctx.stroke();

  const blobs = [
    { label: 'North America', x: 0.2, y: 0.36, w: 0.24, h: 0.2 },
    { label: 'South America', x: 0.31, y: 0.63, w: 0.13, h: 0.24 },
    { label: 'Europe', x: 0.52, y: 0.34, w: 0.12, h: 0.1 },
    { label: 'Africa', x: 0.55, y: 0.55, w: 0.15, h: 0.22 },
    { label: 'Asia', x: 0.7, y: 0.38, w: 0.28, h: 0.18 },
    { label: 'Australia', x: 0.82, y: 0.73, w: 0.12, h: 0.08 },
  ];
  ctx.fillStyle = 'rgba(86,211,100,.08)';
  ctx.strokeStyle = 'rgba(86,211,100,.16)';
  blobs.forEach(blob => {
    const x = blob.x * width;
    const y = blob.y * height;
    const w = blob.w * width;
    const h = blob.h * height;
    ctx.beginPath();
    ctx.ellipse(x, y, w / 2, h / 2, -0.25, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = 'rgba(201,209,217,.32)';
    ctx.font = '9px ui-monospace, SFMono-Regular, Consolas, monospace';
    ctx.fillText(blob.label, x - w / 2 + 4, y);
    ctx.fillStyle = 'rgba(86,211,100,.08)';
  });
}

function drawWorldGrid(ctx, width, height) {
  ctx.strokeStyle = 'rgba(255,255,255,.055)';
  ctx.lineWidth = 1;
  for (let x = 0; x <= width; x += 40) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();
  }
  for (let y = 0; y <= height; y += 40) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }
  ctx.strokeStyle = 'rgba(255,120,86,.28)';
  ctx.beginPath();
  ctx.moveTo(width / 2, 0);
  ctx.lineTo(width / 2, height);
  ctx.moveTo(0, height / 2);
  ctx.lineTo(width, height / 2);
  ctx.stroke();
}

function worldColorForKind(kind) {
  const map = {
    operator: '#ff7856',
    vessel: '#79c0ff',
    location: '#56d364',
    note: '#d2a8ff',
    event: '#ffa657',
    memory: '#f2cc60',
    tool_layer: '#7ee787',
    query: '#ff7b72',
    concept: '#a5d6ff',
    force_field: '#ff9b85',
    blackbox: '#c9d1d9',
    speaker: '#f778ba',
  };
  return map[kind] || '#8b949e';
}

function worldGeoColorForType(type) {
  const map = {
    coordinate_origin: '#ff7856',
    war_trigger: '#ff7b72',
    major_war: '#ff7b72',
    war_boundary_crossing: '#ffa657',
    nuclear_threshold: '#f2cc60',
    revolutionary_threshold: '#d2a8ff',
    regime_turn: '#d2a8ff',
    regime_boundary_break: '#a5d6ff',
    network_origin: '#79c0ff',
    networked_mobilization: '#79c0ff',
    platform_governance: '#7ee787',
    global_system_shock: '#f778ba',
    security_shock: '#c9d1d9',
    news_observation: '#58a6ff',
    future_projection: '#ffffff',
  };
  return map[type] || '#8b949e';
}

function renderWorldAnswer(input, payload) {
  const out = document.getElementById('output-council');
  if (!out) return;
  const evaluation = payload.evaluation || {};
  const world = payload.world || {};
  const counts = world.source_counts || {};
  const scenarios = Array.isArray(payload.scenarios) ? payload.scenarios : [];
  const rec = scenarios.find(s => s.id === evaluation.recommended_scenario) || scenarios[0] || {};
  out.classList.remove('streaming', 'error');
  out.innerHTML = `
    <div><strong>World simulation</strong></div>
    <p>${escapeHtml(evaluation.summary || 'World state generated.')}</p>
    <p><strong>Trigger:</strong> ${escapeHtml(input || '(empty)')}</p>
    <p><strong>Graph:</strong> ${(world.entities || []).length} entities, ${(world.relations || []).length} relations, ${(world.forces || []).length} forces. Tools ${counts.tools ?? 0}, notes ${counts.notes ?? 0}, events ${counts.calendar_events ?? 0}.</p>
    ${rec.id ? `<p><strong>Recommended scenario:</strong> ${escapeHtml(rec.label || rec.id)} (${escapeHtml(rec.risk || 'risk?')})</p>` : ''}
    <p>Open the World tab on the left to inspect the 3D state map and scenario deltas.</p>
  `;
}

function renderWorldForecastAnswer(input, payload) {
  const out = document.getElementById('output-council');
  if (!out) return;
  const forecast = payload.forecast || {};
  const counts = payload.evidence_counts || {};
  const newsFilter = payload.news_filter || {};
  const scenarios = Array.isArray(payload.scenarios) ? payload.scenarios : [];
  const top = scenarios.slice(0, 3).map(s => {
    const pct = Math.round((Number(s.relative_weight) || 0) * 100);
    return `${escapeHtml(s.id || 'scenario')} ${pct}%/${escapeHtml(s.band || '')}`;
  }).join(' · ');
  out.classList.remove('streaming', 'error');
  out.innerHTML = `
    <div><strong>World forecast</strong></div>
    <p>${escapeHtml(forecast.interpretation || 'Forecast generated from filtered evidence.')}</p>
    <p><strong>Trigger:</strong> ${escapeHtml(input || '(empty)')}</p>
    <p><strong>Evidence:</strong> ${counts.total ?? 0} total, ${counts.history ?? 0} history, ${counts.news ?? 0} news. News coordinates ${newsFilter.coordinate_count ?? 0}.</p>
    ${top ? `<p><strong>Scenario weights:</strong> ${top}</p>` : ''}
    <p><strong>Warning:</strong> scenario weighting only; not a guaranteed prediction.</p>
    <p>Open the World tab to inspect signals, source-coordinate flags, and raw evidence.</p>
  `;
}

function renderWorldGeoTimelineAnswer(input, payload) {
  const out = document.getElementById('output-council');
  if (!out) return;
  const events = Array.isArray(payload.events) ? payload.events : [];
  const links = Array.isArray(payload.links) ? payload.links : [];
  const correction = payload.forecast_correction || {};
  const corrected = correction.corrected || {};
  const projected = events.filter(e => e.projected).length;
  out.classList.remove('streaming', 'error');
  out.innerHTML = `
    <div><strong>World geo timeline</strong></div>
    <p>${escapeHtml(corrected.interpretation || 'Real-coordinate timeline generated.')}</p>
    <p><strong>Trigger:</strong> ${escapeHtml(input || '(empty)')}</p>
    <p><strong>Map:</strong> ${events.length} coordinate events, ${links.length} causal links, ${projected} future projection node.</p>
    <p><strong>Correction:</strong> ${escapeHtml(correction.correction_strength || 'weak')} news correction. Future projection nodes are not observed history.</p>
    <p>Open the World tab to inspect the real lat/lon map, timeline, links, and scenario deltas.</p>
  `;
}

function setWorldStatus(message, isError = false) {
  const status = document.getElementById('world-status');
  if (!status) return;
  status.textContent = message || '';
  status.classList.toggle('error', Boolean(isError));
}

let __skillsLoaded = false;

async function loadSkills() {
  const listEl = document.getElementById('skills-list');
  if (!listEl) return;
  try {
    const r = await fetch('/api/skills');
    if (!r.ok) throw new Error(`skills fetch ${r.status}`);
    const skills = await r.json();
    renderSkillsList(skills);
  } catch (e) {
    listEl.innerHTML = `<div class="empty">載入失敗: ${escapeHtml(String(e))}</div>`;
    __skillsLoaded = false;   // allow retry on next click
  }
}

function renderSkillsList(skills) {
  const listEl = document.getElementById('skills-list');
  if (!listEl) return;

  const createDrawer = `
    <div id="skill-create-drawer" style="display:none;padding:10px 12px;border-bottom:0.5px solid var(--color-border-tertiary)">
      <label style="display:block;margin-bottom:6px;font-size:12px">name (kebab-case)
        <input id="skill-create-name" type="text" placeholder="my-new-skill" autocomplete="off" style="width:100%;margin-top:2px">
      </label>
      <label style="display:block;margin-bottom:6px;font-size:12px">description
        <textarea id="skill-create-desc" rows="2" placeholder="One-paragraph summary of what this skill does" style="width:100%;margin-top:2px"></textarea>
      </label>
      <label style="display:block;margin-bottom:6px;font-size:12px">body (Markdown)
        <textarea id="skill-create-body" rows="6" placeholder="# Title\n\n## What it does\n..." style="width:100%;margin-top:2px"></textarea>
      </label>
      <div style="display:flex;align-items:center;gap:8px">
        <button id="skill-create-submit" type="button" style="font-size:12px">儲存 skill</button>
        <span id="skill-create-status" style="font-size:11px"></span>
      </div>
    </div>`;

  const addBtn = `<button class="skill-add-btn" id="skill-add-trigger"><span style="font-size:14px">＋</span> 新增 skill</button>`;

  function wireAddToggle() {
    document.getElementById('skill-add-trigger')?.addEventListener('click', () => {
      const d = document.getElementById('skill-create-drawer');
      if (d) d.style.display = d.style.display === 'none' ? '' : 'none';
    });
  }

  if (!Array.isArray(skills) || skills.length === 0) {
    listEl.innerHTML = createDrawer + '<div class="empty">冇 skill</div>' + addBtn;
    _wireSkillCreate();
    wireAddToggle();
    return;
  }

  const ORDER = ['protocol','tool','output','user'];
  const groups = {};
  skills.forEach(s => {
    const cat = _skillCategory(s.name);
    if (!groups[cat]) groups[cat] = [];
    groups[cat].push(s);
  });

  const html = ORDER.filter(g => groups[g]?.length).map(g => {
    const label = `<div class="skills-group-label">${_skillGroupLabel[g]}</div>`;
    const items = groups[g].map(s => {
      const name = escapeHtml(s.name || '(unnamed)');
      const desc = escapeHtml(s.description || '');
      const body = escapeHtml(s.body || '');
      const dotCls = _skillDotClass[g];
      return `
        <div class="skill-item-v2" data-skill-name="${name}">
          <div class="si-name"><span class="skill-dot ${dotCls}"></span>${name}</div>
          ${desc ? `<div class="si-desc">${desc}</div>` : ''}
          <div class="skill-body-drawer" style="display:none;padding:8px 0 0;font-size:11px;white-space:pre-wrap">${body}</div>
        </div>`;
    }).join('');
    return label + items;
  }).join('');

  listEl.innerHTML = createDrawer + html + addBtn;
  _wireSkillCreate();
  wireAddToggle();

  listEl.querySelectorAll('.skill-item-v2').forEach(el => {
    el.addEventListener('click', () => {
      const drawer = el.querySelector('.skill-body-drawer');
      if (drawer) drawer.style.display = drawer.style.display === 'none' ? 'block' : 'none';
    });
  });
}

function _wireSkillCreate() {
  const btn = document.getElementById('skill-create-submit');
  if (!btn) return;
  btn.addEventListener('click', async () => {
    const name = document.getElementById('skill-create-name').value.trim();
    const desc = document.getElementById('skill-create-desc').value;
    const body = document.getElementById('skill-create-body').value;
    const statusEl = document.getElementById('skill-create-status');
    if (!name) {
      statusEl.textContent = '⚠ name 唔可以空';
      statusEl.style.color = '#e74c3c';
      return;
    }
    statusEl.textContent = '儲存中…';
    statusEl.style.color = '';
    btn.disabled = true;
    try {
      const r = await fetch('/api/skills', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name, description: desc, body})
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({detail: `HTTP ${r.status}`}));
        statusEl.textContent = `✗ ${err.detail || err}`;
        statusEl.style.color = '#e74c3c';
        return;
      }
      const data = await r.json();
      statusEl.textContent = `✓ 已儲存: ${data.source_path}`;
      statusEl.style.color = '#2ecc71';
      // Refresh list to show new skill
      __skillsLoaded = false;
      await loadSkills();
      __skillsLoaded = true;
    } catch (e) {
      statusEl.textContent = `✗ ${e.message}`;
      statusEl.style.color = '#e74c3c';
    } finally {
      btn.disabled = false;
    }
  });
}

async function loadFileTree() {
  const treeEl = document.getElementById('file-tree');
  if (!treeEl) return;
  try {
    const r = await fetch('/api/files/tree');
    if (!r.ok) throw new Error(`tree fetch ${r.status}`);
    const tree = await r.json();
    renderFileTree(tree);
  } catch (e) {
    treeEl.innerHTML = `<div class="empty error">載入失敗：${escapeHtml(e.message)}</div>`;
  }
}

function renderFileTree(tree) {
  const treeEl = document.getElementById('file-tree');
  if (!treeEl) return;

  const SECTION_CONFIG = [
    { prefix: 'data/core',                           key: 'core',           label: 'Core',           color: 'purple' },
    { prefix: 'data/theory',                         key: 'theory',         label: 'Theory',         color: 'indigo' },
    { prefix: 'data/misc',                           key: 'supplements',    label: 'Supplements',    color: 'green'  },
    { prefix: 'data/protocol',                       key: 'protocol',       label: 'Protocol',       color: 'teal'   },
    { prefix: 'config/protocol/references/module_t', key: 'module_t',       label: 'Module T',       color: 'cyan'   },
    { prefix: 'data/causal_db',                      key: 'causal_db',      label: 'Causal DB',      color: 'coral'  },
    { prefix: 'data/causal_records',                 key: 'causal_records', label: 'Causal Records', color: 'red'    },
    { prefix: 'config/prompts',                      key: 'prompts',        label: 'Prompts',        color: 'amber'  },
    { prefix: 'data/kairos',                         key: 'kairos',         label: 'Kairos',         color: 'blue'   },
    { prefix: 'data/experiments',                    key: 'experiments',    label: 'Experiments',    color: 'gray'   },
    { prefix: 'config',                              key: 'config',         label: 'Config',         color: 'gray'   },
  ];

  function sectionFor(path) {
    const kairosSection = SECTION_CONFIG.find(s => s.key === 'kairos');
    if (
      path.startsWith('data/kairos/') ||
      /(^|\/)KAIROS_(CORE|ACTIVE|ARCHIVE_INDEX|LOG_.*)\.md$/.test(path)
    ) {
      return kairosSection;
    }
    for (const s of SECTION_CONFIG) {
      if (path.startsWith(s.prefix + '/') || path === s.prefix) return s;
    }
    return { key: 'other', label: 'Other', color: 'gray' };
  }

  const allFiles = [];
  for (const layer of ['canonical', 'prompts', 'personal', 'config']) {
    const data = tree[layer];
    if (!data) continue;
    for (const f of data.files) allFiles.push(f);
  }

  const sectionOrder = [...SECTION_CONFIG, { key: 'other', label: 'Other', color: 'gray' }];
  const groups = new Map(sectionOrder.map(s => [s.key, { config: s, files: [] }]));
  for (const f of allFiles) {
    const s = sectionFor(f.path);
    if (!groups.has(s.key)) groups.set(s.key, { config: s, files: [] });
    groups.get(s.key).files.push(f);
  }

  const SVG_SEARCH = `<svg class="file-search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>`;
  const svgFileText = cls => `<svg class="file-type-icon ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>`;
  const svgFile    = cls => `<svg class="file-type-icon ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><polyline points="13 2 13 9 20 9"/></svg>`;

  const activePath = editorCurrent ? editorCurrent.path : null;
  const parts = [];

  parts.push(`<div class="file-search-wrap">${SVG_SEARCH}<input type="search" class="file-search" id="file-search-input" placeholder="搜索⋯" autocomplete="off"></div>`);

  let first = true;
  for (const [, { config, files }] of groups) {
    if (!files.length) continue;
    if (!first) parts.push(`<div class="file-section-divider"></div>`);
    first = false;
    parts.push(`<div class="file-section" data-section="${config.key}">`);
    parts.push(`<div class="file-section-header"><span class="file-section-chevron">▾</span><span class="file-section-badge badge-${config.color}"></span><span class="file-section-name">${config.label}</span><span class="file-section-count">${files.length}</span></div>`);
    parts.push(`<div class="file-section-body">`);
    for (const f of files) {
      const full = f.path.split('/').slice(-1)[0];
      const dot = full.lastIndexOf('.');
      const ext = dot >= 0 ? full.slice(dot) : '';
      const base = dot >= 0 ? full.slice(0, dot) : full;
      const isActive = f.path === activePath;
      const iconCls = ext === '.md' ? 'icon-md' : ext === '.txt' ? 'icon-txt' : 'icon-other';
      const icon = ext === '.md' ? svgFileText(iconCls) : svgFile(iconCls);
      parts.push(`<div class="file-row${isActive ? ' active' : ''}" data-path="${escapeHtml(f.path)}" title="${escapeHtml(f.path)}">${icon}<span class="file-row-name">${escapeHtml(base)}</span>${ext ? `<span class="file-row-ext">${escapeHtml(ext)}</span>` : ''}</div>`);
    }
    parts.push(`</div></div>`);
  }

  treeEl.innerHTML = parts.join('');

  treeEl.querySelectorAll('.file-row').forEach(el => {
    el.addEventListener('click', () => {
      treeEl.querySelectorAll('.file-row.active').forEach(r => r.classList.remove('active'));
      el.classList.add('active');
      openFile(el.dataset.path);
    });
  });

  treeEl.querySelectorAll('.file-section-header').forEach(header => {
    header.addEventListener('click', () => {
      const section = header.closest('.file-section');
      const body = section.querySelector('.file-section-body');
      const chevron = header.querySelector('.file-section-chevron');
      const nowCollapsed = body.style.display !== 'none';
      body.style.display = nowCollapsed ? 'none' : '';
      chevron.textContent = nowCollapsed ? '▸' : '▾';
    });
  });

  const searchInput = document.getElementById('file-search-input');
  if (searchInput) {
    searchInput.addEventListener('input', () => {
      const q = searchInput.value.toLowerCase();
      treeEl.querySelectorAll('.file-row').forEach(row => {
        const match = !q
          || (row.dataset.path || '').toLowerCase().includes(q)
          || (row.querySelector('.file-row-name')?.textContent || '').toLowerCase().includes(q);
        row.style.display = match ? '' : 'none';
      });
      treeEl.querySelectorAll('.file-section').forEach(sec => {
        const anyVisible = [...sec.querySelectorAll('.file-row')].some(r => r.style.display !== 'none');
        sec.style.display = anyVisible ? '' : 'none';
        if (anyVisible && q) {
          const body = sec.querySelector('.file-section-body');
          const chevron = sec.querySelector('.file-section-chevron');
          if (body) body.style.display = '';
          if (chevron) chevron.textContent = '▾';
        }
      });
    });
  }
}

// Note: dropped CodeMirror 6 ESM (esm.sh bundle was unstable —
// 'basicSetup' undefined caused 'reading extension' crash).
// Use plain textarea + monospace styling. Simple, reliable, no CDN dependency.

async function openFile(path, options = {}) {
  // Open file in the sidebar viewer overlay (covers full sidebar).
  // Files tree clicks switch to Files; Kairos panel clicks can keep their tab.
  if (!options.keepTab) {
    const filesTabBtn = document.querySelector('.tab-btn[data-tab="files"]');
    if (filesTabBtn && !filesTabBtn.classList.contains('active')) filesTabBtn.click();
  }

  const viewer  = document.getElementById('sidebar-viewer');
  const svPath  = document.getElementById('sv-path');
  const svFooter= document.getElementById('sv-footer');
  const svHost  = document.getElementById('sv-host');
  const svSave  = document.getElementById('sv-save');
  const svRevert= document.getElementById('sv-revert');
  const svDirty = document.getElementById('sv-dirty');
  const svBadge = document.getElementById('sv-layer-badge');

  if (!viewer) {
    // Fallback: old main-column editor (shouldn't happen in normal UI)
    const pane = document.getElementById('editor-pane');
    if (pane) pane.classList.remove('hidden');
    return;
  }

  // Show viewer — lock #main-column scroll so absolute overlay stays in view
  const mainCol = document.getElementById('main-column');
  if (mainCol) { mainCol.scrollTop = 0; mainCol.classList.add('viewer-open'); }
  svPath.textContent = path;
  svFooter.textContent = '載入中⋯';
  svHost.innerHTML = '';
  svSave.disabled = true;
  svRevert.disabled = true;
  if (svDirty) svDirty.textContent = '';
  viewer.classList.remove('hidden');

  try {
    const r = await fetch(`/api/files/read?path=${encodeURIComponent(path)}`);
    if (!r.ok) {
      const err = await r.text();
      svFooter.textContent = `讀檔失敗 ${r.status}: ${err}`;
      return;
    }
    const info = await r.json();
    editorCurrent = { path, originalContent: info.content, info };
    editorDirty = false;

    const meta = LAYER_LABELS[info.layer] || { label: info.layer, cls: '', readonly_note: '' };
    svBadge.textContent = info.layer.toUpperCase();
    svBadge.className = `sv-layer-badge ${meta.cls}`;
    svSave.disabled = info.readonly;
    svRevert.disabled = true;

    // Mount textarea
    const ta = document.createElement('textarea');
    ta.value = info.content;
    ta.spellcheck = false;
    if (info.readonly) ta.readOnly = true;
    ta.className = 'editor-textarea' + (info.readonly ? ' readonly' : '');
    svHost.appendChild(ta);
    editorView = { textarea: ta };

    if (!info.readonly) {
      ta.addEventListener('input', () => {
        editorDirty = true;
        if (svDirty) svDirty.textContent = '●';
        svRevert.disabled = false;
      });
    }

    const ext = path.split('.').pop().toLowerCase();
    const langHint = ({ md:'Markdown', yaml:'YAML', yml:'YAML', py:'Python', json:'JSON', txt:'Text' }[ext] || ext.toUpperCase());
    svFooter.textContent = `${info.size}B · sha256:${info.sha256.slice(0,8)} · ${info.mtime} · ${langHint}`;
  } catch (e) {
    svFooter.textContent = `Error: ${e.message}`;
  }
}

async function mountEditor(content, readonly, path) {
  // Plain textarea with monospace styling. Reliable across environments.
  const host = document.getElementById('editor-host');
  const ext = path.split('.').pop().toLowerCase();
  // Auto-detect line-language for hint (no syntax highlighting in textarea,
  // but show file type in status bar)
  const langHint = ({md: 'Markdown', yaml: 'YAML', yml: 'YAML', py: 'Python', json: 'JSON', txt: 'Text'}[ext] || ext.toUpperCase());

  const ta = document.createElement('textarea');
  ta.id = 'editor-textarea';
  ta.value = content;
  ta.spellcheck = false;
  if (readonly) ta.readOnly = true;
  ta.className = 'editor-textarea' + (readonly ? ' readonly' : '');
  ta.placeholder = readonly ? '(read-only)' : '';

  host.innerHTML = '';
  host.appendChild(ta);

  if (!readonly) {
    ta.addEventListener('input', () => markDirty());
  }

  // Stash reference for save handler
  editorView = { textarea: ta };
  // Append lang hint to status
  const statusEl = document.getElementById('editor-status');
  if (statusEl) statusEl.textContent += ` · ${langHint}`;
}

function markDirty() {
  if (!editorCurrent) return;
  editorDirty = true;
  document.getElementById('editor-dirty').textContent = '●';
  document.getElementById('editor-revert').disabled = false;
}

function _closeSidebarViewer() {
  if (editorDirty && !confirm('有未儲存改動，確認關閉？')) return;
  document.getElementById('sidebar-viewer')?.classList.add('hidden');
  document.getElementById('main-column')?.classList.remove('viewer-open');
  document.getElementById('sv-host').innerHTML = '';
  editorView = null;
  editorCurrent = null;
  editorDirty = false;
}

function setupEditorPane() {
  // Sidebar viewer: back button + Escape key to dismiss
  document.getElementById('sv-back')?.addEventListener('click', _closeSidebarViewer);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !document.getElementById('sidebar-viewer')?.classList.contains('hidden')) {
      _closeSidebarViewer();
    }
  });

  // Sidebar viewer: revert
  document.getElementById('sv-revert')?.addEventListener('click', () => {
    if (!editorCurrent) return;
    if (!confirm('還原到讀入時嘅版本？')) return;
    openFile(editorCurrent.path);
  });

  // Sidebar viewer: save
  document.getElementById('sv-save')?.addEventListener('click', async () => {
    if (!editorCurrent) return;
    const content = editorView?.textarea?.value ?? '';
    const svFooter = document.getElementById('sv-footer');
    const svDirty  = document.getElementById('sv-dirty');
    const svRevert = document.getElementById('sv-revert');
    if (svFooter) svFooter.textContent = '儲存中⋯';
    try {
      const r = await fetch('/api/files/write', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: editorCurrent.path, content }),
      });
      if (!r.ok) {
        const err = await r.text();
        if (svFooter) svFooter.textContent = `儲存失敗 ${r.status}: ${err}`;
        return;
      }
      const info = await r.json();
      editorCurrent.originalContent = content;
      editorCurrent.info = info;
      editorDirty = false;
      if (svDirty)  svDirty.textContent = '';
      if (svRevert) svRevert.disabled = true;
      const backup = info.backup ? ` · backup: ${info.backup.backup_path}` : '';
      if (svFooter) svFooter.textContent = `已儲存 · ${info.size}B · sha256:${info.sha256.slice(0,8)}${backup}`;
      loadFileTree();
    } catch (e) {
      if (svFooter) svFooter.textContent = `Error: ${e.message}`;
    }
  });

  // Legacy main-column editor-pane close (kept for any other callers)
  document.getElementById('editor-close').addEventListener('click', () => {
    if (editorDirty && !confirm('有未儲存改動，確認關閉？')) return;
    document.getElementById('editor-pane').classList.add('hidden');
    document.getElementById('main-column')?.classList.remove('editor-open');
    editorView = null;
    document.getElementById('editor-host').innerHTML = '';
    editorCurrent = null;
    editorDirty = false;
  });
  document.getElementById('editor-revert').addEventListener('click', () => {
    if (!editorCurrent) return;
    if (!confirm('還原到讀入時嘅版本？')) return;
    openFile(editorCurrent.path);
  });
  document.getElementById('editor-save').addEventListener('click', async () => {
    if (!editorCurrent) return;
    const content = editorView && editorView.textarea
      ? editorView.textarea.value
      : (document.getElementById('editor-textarea')?.value || '');
    const statusEl = document.getElementById('editor-status');
    statusEl.textContent = '儲存中⋯';
    try {
      const r = await fetch('/api/files/write', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: editorCurrent.path, content }),
      });
      if (!r.ok) {
        const err = await r.text();
        statusEl.textContent = `儲存失敗 ${r.status}: ${err}`;
        return;
      }
      const info = await r.json();
      editorCurrent.originalContent = content;
      editorCurrent.info = info;
      editorDirty = false;
      document.getElementById('editor-dirty').textContent = '';
      document.getElementById('editor-revert').disabled = true;
      const backup = info.backup ? ` · backup: ${info.backup.backup_path}` : '';
      statusEl.textContent = `已儲存 · ${info.size}B · sha256:${info.sha256.slice(0, 8)}${backup}`;
      loadFileTree();  // refresh
    } catch (e) {
      statusEl.textContent = `Error: ${e.message}`;
    }
  });
}

// ═══════════════════════════════════════════════════════════════
// Phase 1: Tool Palette (Web Search / Fetch URL / Calendar)
// ═══════════════════════════════════════════════════════════════

let lastToolResult = null;  // { kind: 'search'|'fetch'|'calendar', formatted: string }

function setupToolPalette() {
  // Tool button bindings
  const sb = document.getElementById('tool-search-btn');
  const fb = document.getElementById('tool-fetch-btn');
  const cb = document.getElementById('tool-calendar-btn');
  if (sb) sb.addEventListener('click', () => openModal('tool-search-modal'));
  if (fb) fb.addEventListener('click', () => openModal('tool-fetch-modal'));
  if (cb) cb.addEventListener('click', () => { openModal('tool-calendar-modal'); loadCalendarFiles(); });

  // Modal close handlers
  document.querySelectorAll('.tool-modal-close').forEach(btn => {
    btn.addEventListener('click', () => closeModal(btn.dataset.modal));
  });
  // ESC to close any open modal
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      document.querySelectorAll('.tool-modal:not(.hidden)').forEach(m => m.classList.add('hidden'));
    }
  });
  // Click backdrop to close
  document.querySelectorAll('.tool-modal').forEach(m => {
    m.addEventListener('click', (e) => {
      if (e.target === m) m.classList.add('hidden');
    });
  });

  // Search modal handlers
  const sgo = document.getElementById('tool-search-go');
  if (sgo) sgo.addEventListener('click', runWebSearch);
  const sq = document.getElementById('tool-search-query');
  if (sq) sq.addEventListener('keydown', e => { if (e.key === 'Enter') runWebSearch(); });
  const sins = document.getElementById('tool-search-insert');
  if (sins) sins.addEventListener('click', () => insertToolResult('tool-search-modal'));
  const srun = document.getElementById('tool-search-insert-run');
  if (srun) srun.addEventListener('click', () => insertToolResultAndRun('tool-search-modal'));

  // Fetch modal handlers
  const fgo = document.getElementById('tool-fetch-go');
  if (fgo) fgo.addEventListener('click', runFetchUrl);
  const fu = document.getElementById('tool-fetch-url');
  if (fu) fu.addEventListener('keydown', e => { if (e.key === 'Enter') runFetchUrl(); });
  const fins = document.getElementById('tool-fetch-insert');
  if (fins) fins.addEventListener('click', () => insertToolResult('tool-fetch-modal'));

  // Calendar modal handlers
  const cgo = document.getElementById('tool-cal-go');
  if (cgo) cgo.addEventListener('click', runCalendarQuery);
  const cins = document.getElementById('tool-cal-insert');
  if (cins) cins.addEventListener('click', () => insertToolResult('tool-calendar-modal'));

  // v8.45 — Tool Workshop quick-access button
  const twBtn = document.getElementById('tool-workshop-btn');
  if (twBtn) {
    twBtn.addEventListener('click', () => {
      // Set mode to tool_workshop, uncheck everything else
      document.querySelectorAll('input[name="mode"]').forEach(cb => {
        cb.checked = cb.value === 'tool_workshop';
      });
      // Focus input
      const inp = document.getElementById('user-input');
      if (inp) {
        if (!inp.value) inp.value = '';
        inp.focus();
        inp.placeholder = '問工具坊：例「點樣新增一個工具？」 / 「幫我新增一個壓縮資料夾嘅工具」';
      }
      setStatus('🔧 工具坊模式 — 直接對話新增或了解 Agent 工具');
    });
  }
}

// ── v8.45 Tool Workshop: inline install card ───────────────────────────────
function _renderToolInstallCard(parentEl, proposal) {
  const card = document.createElement('div');
  card.className = 'tw-install-card';

  const catClass = {
    screen: 'at-cat-screen', mouse: 'at-cat-mouse', keyboard: 'at-cat-keyboard',
    file: 'at-cat-file', state: 'at-cat-state', clipboard: 'at-cat-clipboard',
    nav: 'at-cat-nav', wait: 'at-cat-wait',
  }[proposal.category] || 'at-cat-misc';

  const argsRows = (proposal.args || []).map(a =>
    `<tr><td style="font-family:monospace">${_escHtml(a.name)}</td>` +
    `<td>${_escHtml(a.type)}</td>` +
    `<td>${a.required ? '✓' : '—'}</td>` +
    `<td>${_escHtml(a.description || '')}</td></tr>`
  ).join('');

  const codeId = 'tw-code-' + Math.random().toString(36).slice(2);

  card.innerHTML =
    '<div class="tw-card-header">' +
      '<span class="tw-card-icon">🔧</span>' +
      '<span class="tw-card-title">新工具草案</span>' +
    '</div>' +
    '<div class="tw-card-body">' +
      '<div class="tw-meta-row">' +
        '<span class="at-cat-badge ' + catClass + '">' + _escHtml(proposal.category || 'misc') + '</span>' +
        (proposal.needs_visual ? '<span class="at-visual-badge">👁 visual</span>' : '') +
        '<span class="tw-tool-name">' + _escHtml(proposal.name || '') + '</span>' +
      '</div>' +
      '<div class="tw-desc">' + _escHtml(proposal.description || '') + '</div>' +
      (argsRows ? '<table class="at-ai-args-table" style="margin:8px 0">' +
        '<thead><tr><th>Arg</th><th>Type</th><th>Req</th><th>Description</th></tr></thead>' +
        '<tbody>' + argsRows + '</tbody></table>' : '') +
      '<details class="tw-code-details">' +
        '<summary class="tw-code-summary">Python 實作 <span class="tw-code-edit-hint">（可編輯）</span></summary>' +
        '<textarea id="' + codeId + '" class="tw-code-editor" spellcheck="false">' +
          _escHtml(proposal.python_code || '') +
        '</textarea>' +
      '</details>' +
    '</div>' +
    '<div class="tw-card-actions">' +
      '<button class="tw-install-btn">⬇ 安裝工具</button>' +
      '<button class="tw-dismiss-btn">✕</button>' +
      '<span class="tw-install-status"></span>' +
    '</div>';

  // Wire install button
  const installBtn = card.querySelector('.tw-install-btn');
  const dismissBtn = card.querySelector('.tw-dismiss-btn');
  const statusEl   = card.querySelector('.tw-install-status');

  if (dismissBtn) dismissBtn.addEventListener('click', () => card.remove());

  if (installBtn) {
    installBtn.addEventListener('click', async () => {
      const codeEl = document.getElementById(codeId);
      const code = codeEl ? codeEl.value : (proposal.python_code || '');
      installBtn.disabled = true;
      statusEl.textContent = '安裝中⋯';
      statusEl.style.color = '';
      try {
        const res = await fetch('/api/agent/tool/install', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: proposal.name,
            description: proposal.description,
            category: proposal.category || 'misc',
            needs_visual: !!proposal.needs_visual,
            args: proposal.args || [],
            python_code: code,
            explanation: proposal.explanation || '',
          }),
        });
        const d = await res.json();
        if (!res.ok) {
          statusEl.textContent = '失敗: ' + (d.detail || res.statusText);
          statusEl.style.color = '#f88';
          installBtn.disabled = false;
        } else {
          statusEl.textContent = '✓ 已安裝：' + d.name;
          statusEl.style.color = '#5be87a';
          installBtn.remove();
          setStatus('🔧 工具已安裝並熱載入：' + d.name);
        }
      } catch (e) {
        statusEl.textContent = '錯誤: ' + e.message;
        statusEl.style.color = '#f88';
        installBtn.disabled = false;
      }
    });
  }

  // Append card after the council output text
  parentEl.appendChild(card);
}

function _escHtml(s) {
  return String(s || '')
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function openModal(id) {
  const m = document.getElementById(id);
  if (m) m.classList.remove('hidden');
}

function closeModal(id) {
  const m = document.getElementById(id);
  if (m) m.classList.add('hidden');
}

// ───── Web Search ─────
async function runWebSearch() {
  const q = document.getElementById('tool-search-query').value.trim();
  const n = parseInt(document.getElementById('tool-search-n').value || '5', 10);
  const resultsEl = document.getElementById('tool-search-results');
  const insertBtn = document.getElementById('tool-search-insert');
  if (!q) { resultsEl.innerHTML = '<div class="tool-error">輸入搜索詞先</div>'; return; }
  resultsEl.innerHTML = '<div class="tool-loading">搜索中⋯</div>';
  insertBtn.disabled = true;
  try {
    const r = await fetch(`/api/tools/web_search?q=${encodeURIComponent(q)}&n=${n}`);
    if (!r.ok) {
      const err = await r.text();
      resultsEl.innerHTML = `<div class="tool-error">HTTP ${r.status}: ${escapeHtml(err)}</div>`;
      return;
    }
    const results = await r.json();
    if (!results.length) {
      resultsEl.innerHTML = '<div class="tool-error">冇結果</div>';
      return;
    }
    resultsEl.innerHTML = results.map((res, i) => `
      <div class="tool-result-item">
        <div class="tool-result-title"><a href="${escapeHtml(res.url)}" target="_blank" rel="noopener">${i+1}. ${escapeHtml(res.title)}</a></div>
        <div class="tool-result-url">${escapeHtml(res.url)}</div>
        <div class="tool-result-snippet">${escapeHtml(res.snippet)}</div>
      </div>
    `).join('');
    // Format for prompt injection — simplified (title — URL only, no snippet)
    let formatted = `📎 [Web Search: "${q}"]
`;
    results.forEach((res, i) => {
      formatted += `${i+1}. ${res.title} — ${res.url}
`;
    });
    lastToolResult = { kind: 'search', formatted };
    insertBtn.disabled = false;
    const runBtn = document.getElementById('tool-search-insert-run');
    if (runBtn) runBtn.disabled = false;
  } catch (e) {
    resultsEl.innerHTML = `<div class="tool-error">Error: ${escapeHtml(e.message)}</div>`;
  }
}

// ───── Fetch URL ─────
async function runFetchUrl() {
  const url = document.getElementById('tool-fetch-url').value.trim();
  const resultEl = document.getElementById('tool-fetch-result');
  const insertBtn = document.getElementById('tool-fetch-insert');
  if (!url) { resultEl.innerHTML = '<div class="tool-error">輸入 URL 先</div>'; return; }
  resultEl.innerHTML = '<div class="tool-loading">Fetching⋯</div>';
  insertBtn.disabled = true;
  try {
    const r = await fetch(`/api/tools/fetch_url?url=${encodeURIComponent(url)}`);
    if (!r.ok) {
      const err = await r.text();
      resultEl.innerHTML = `<div class="tool-error">HTTP ${r.status}: ${escapeHtml(err)}</div>`;
      return;
    }
    const data = await r.json();
    resultEl.innerHTML = `
      <div class="tool-fetch-meta">
        <div><strong>Title:</strong> ${escapeHtml(data.title || '(no title)')}</div>
        <div><strong>URL:</strong> ${escapeHtml(data.final_url)} (HTTP ${data.status})</div>
        <div><strong>Date:</strong> ${escapeHtml(data.date_published || '?')}</div>
        <div><strong>Size:</strong> ${data.size_bytes} bytes · sha256: ${data.content_hash.slice(0,12)}⋯</div>
        <div><strong>Fetched:</strong> ${escapeHtml(data.fetched_at)}</div>
      </div>
      <div class="tool-fetch-text">${escapeHtml(data.main_text.slice(0, 3000))}${data.main_text.length > 3000 ? '\n\n[⋯ truncated, full available on insert]' : ''}</div>
    `;
    let formatted = `📎 [Fetched URL]
Title: ${data.title}
URL: ${data.final_url}
Date: ${data.date_published || '?'}
Fetched: ${data.fetched_at}
Content hash: ${data.content_hash.slice(0,16)}

=== Main text ===
${data.main_text}
=== END ===
`;
    lastToolResult = { kind: 'fetch', formatted };
    insertBtn.disabled = false;
  } catch (e) {
    resultEl.innerHTML = `<div class="tool-error">Error: ${escapeHtml(e.message)}</div>`;
  }
}

// ───── Calendar ─────
async function loadCalendarFiles() {
  const sel = document.getElementById('tool-cal-file');
  if (!sel) return;
  sel.innerHTML = '<option value="">載入中⋯</option>';
  try {
    const r = await fetch('/api/tools/calendar/files');
    const files = await r.json();
    if (!files.length) {
      sel.innerHTML = '<option value="">(冇 .ics 喺 data/calendar/)</option>';
      return;
    }
    sel.innerHTML = '<option value="">— 揀 .ics 檔 —</option>' + files.map(f =>
      `<option value="${escapeHtml(f.filename)}">${escapeHtml(f.filename)} (${f.size}B, mtime=${escapeHtml(f.mtime.slice(0,10))})</option>`
    ).join('');
  } catch (e) {
    sel.innerHTML = `<option value="">Error: ${escapeHtml(e.message)}</option>`;
  }
}

async function runCalendarQuery() {
  const file = document.getElementById('tool-cal-file').value;
  const from = document.getElementById('tool-cal-from').value;
  const to = document.getElementById('tool-cal-to').value;
  const resultEl = document.getElementById('tool-cal-result');
  const insertBtn = document.getElementById('tool-cal-insert');
  if (!file) { resultEl.innerHTML = '<div class="tool-error">揀 .ics 檔先</div>'; return; }
  resultEl.innerHTML = '<div class="tool-loading">解析中⋯</div>';
  insertBtn.disabled = true;
  try {
    const params = new URLSearchParams({ file });
    if (from) params.set('from_dt', from);
    if (to)   params.set('to_dt', to);
    const r = await fetch(`/api/tools/calendar/events?${params.toString()}`);
    if (!r.ok) {
      const err = await r.text();
      resultEl.innerHTML = `<div class="tool-error">HTTP ${r.status}: ${escapeHtml(err)}</div>`;
      return;
    }
    const events = await r.json();
    if (!events.length) {
      resultEl.innerHTML = '<div class="tool-error">冇事件 (filter 後)</div>';
      return;
    }
    resultEl.innerHTML = events.map(ev => `
      <div class="tool-cal-event">
        <div class="tool-cal-title">${escapeHtml(ev.summary)}</div>
        <div class="tool-cal-time">${escapeHtml(ev.start || '?')} → ${escapeHtml(ev.end || '?')}</div>
        ${ev.location ? `<div class="tool-cal-loc">📍 ${escapeHtml(ev.location)}</div>` : ''}
        ${ev.description ? `<div class="tool-cal-desc">${escapeHtml(ev.description.slice(0,200))}</div>` : ''}
      </div>
    `).join('');
    let formatted = `📎 [Calendar: ${file}${from || to ? ` ${from || '?'}→${to || '?'}` : ''}]
`;
    events.forEach((ev, i) => {
      formatted += `
${i+1}. ${ev.summary}
   ${ev.start} → ${ev.end || '?'}
`;
      if (ev.location) formatted += `   📍 ${ev.location}
`;
      if (ev.description) formatted += `   ${ev.description.slice(0,150).replace(/\n/g,' ')}
`;
    });
    lastToolResult = { kind: 'calendar', formatted };
    insertBtn.disabled = false;
  } catch (e) {
    resultEl.innerHTML = `<div class="tool-error">Error: ${escapeHtml(e.message)}</div>`;
  }
}

// ───── Insert tool result into prompt textarea ─────
function insertToolResult(closeModalId) {
  if (!lastToolResult) return;
  const ta = document.getElementById('user-input');
  if (!ta) return;
  const before = ta.value.trimEnd();
  ta.value = before + (before ? '\n\n' : '') + lastToolResult.formatted;
  ta.dispatchEvent(new Event('input'));
  ta.focus();
  ta.scrollTop = ta.scrollHeight;
  closeModal(closeModalId);
}

// ───── Insert + auto-trigger run pipeline ─────
function insertToolResultAndRun(closeModalId) {
  insertToolResult(closeModalId);
  const runBtn = document.getElementById('run-btn');
  if (runBtn && !runBtn.disabled) {
    setTimeout(() => runBtn.click(), 100);
  }
}

// ═══════════════════════════════════════════════════════════════
// Phase 3 Fix-3: LLM Settings Modal
// ═══════════════════════════════════════════════════════════════

let settingsState = {
  data: null,
  dirty: false,
};

async function openSettingsModal() {
  const modal = document.getElementById('settings-modal');
  if (!modal) return;
  modal.classList.remove('hidden');
  setSettingsStatus('', false);
  setSettingsError('');
  try {
    const r = await fetch('/api/nodes/config');
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    settingsState.data = data;
    settingsState.dirty = false;
    renderPresets(data.presets);
    renderKeyStatus(data.api_key_status, data.providers);
    renderNodesTable(data.nodes, data.providers);
    // v8.2: render new failover sections + health
    renderProfilesTable(data.api_profiles || {}, data.providers);
    renderChainList(data.failover?.global_chain || [], data.api_profiles || {});
    renderFailoverControls(data.failover || {});
    renderCrossSessionControls(data.cross_session || {});
    renderHealthGrid(data.health || {}, data.failover?.cooldown_seconds || 300);
    // v8.7 — developer_mode (client-only localStorage flag)
    const devToggle = document.getElementById('developer-mode-toggle');
    if (devToggle) {
      devToggle.checked = getDeveloperMode();
      // Use onchange (replaces any prior listener) so re-opens don't stack
      devToggle.onchange = () => setDeveloperMode(devToggle.checked);
    }
    // v8.11 — in-session conversation history controls
    const convToggle = document.getElementById('conv-history-enabled');
    const convN = document.getElementById('conv-history-n');
    const convClear = document.getElementById('conv-history-clear');
    const convStatus = document.getElementById('conv-history-status');
    if (convToggle) {
      convToggle.checked = !!__convHistory.enabled;
      convToggle.onchange = () => {
        __convHistory.enabled = !!convToggle.checked;
        if (convStatus) convStatus.textContent = `In-session memory ${__convHistory.enabled ? 'ENABLED' : 'DISABLED'}.`;
      };
    }
    if (convN) {
      convN.value = __convHistory.n_turns;
      convN.onchange = () => {
        const v = Math.max(1, Math.min(20, parseInt(convN.value, 10) || 5));
        __convHistory.n_turns = v;
        convN.value = v;
        // Truncate if new cap is smaller than current
        while (__convHistory.turns.length > v) {
          __convHistory.turns.shift();
          __convHistory.truncation_count++;
        }
        _updateTruncationWarning();
        if (convStatus) convStatus.textContent = `N turns = ${v} (current: ${__convHistory.turns.length} turns in memory).`;
      };
    }
    if (convClear) {
      convClear.onclick = () => {
        const before = __convHistory.turns.length;
        clearConvHistory();
        if (convStatus) convStatus.textContent = `Cleared ${before} turn(s) + thread DOM.`;
      };
    }
    if (convStatus) {
      convStatus.textContent = `${__convHistory.turns.length} turn(s) in memory, ${__convHistory.truncation_count} truncated.`;
    }
    // v8.15 MS-2/MS-1 — Source Registry table + Search engines grid
    initSourceRegistryUI();
    renderSourceRegistry().catch(() => {});
    renderSearchEnginesGrid().catch(() => {});
    startHealthPolling();   // poll every 2s while modal open
    if (data.pipeline_running) {
      setSettingsError('⚠ Pipeline 而家 running，要等個 turn 完先可以 save。');
    }
  } catch (e) {
    setSettingsError('Load settings fail: ' + e.message);
  }
}

function setSettingsStatus(msg, ok) {
  const el = document.getElementById('settings-status');
  if (!el) return;
  if (!msg) { el.classList.add('hidden'); el.textContent = ''; return; }
  el.classList.remove('hidden');
  el.classList.toggle('settings-status-ok', !!ok);
  el.classList.toggle('settings-status-warn', !ok);
  el.textContent = msg;
}

function setSettingsError(msg) {
  const el = document.getElementById('settings-error');
  if (!el) return;
  if (!msg) { el.classList.add('hidden'); el.textContent = ''; return; }
  el.classList.remove('hidden');
  el.textContent = msg;
}

function renderPresets(presets) {
  const wrap = document.getElementById('settings-preset-buttons');
  const desc = document.getElementById('settings-preset-desc');
  if (!wrap) return;
  wrap.innerHTML = '';
  presets.forEach(p => {
    const btn = document.createElement('button');
    btn.className = 'settings-preset-btn';
    btn.textContent = p.name;
    btn.title = p.description;
    btn.dataset.presetId = p.id;
    btn.addEventListener('click', () => {
      applyPreset(p);
      if (desc) desc.textContent = `✓ Applied to form: ${p.description}`;
    });
    wrap.appendChild(btn);
  });
  if (desc) desc.textContent = '揀一個 preset，會即時填曬 8 nodes 嘅 config（未 save 前唔影響 backend）';
}

function applyPreset(preset) {
  if (!preset || !preset.config) return;
  Object.entries(preset.config).forEach(([role, spec]) => {
    setNodeRow(role, spec);
  });
  settingsState.dirty = true;
  setSettingsStatus('Preset applied to form. 按「💾 儲存」先生效。', true);
}

function renderKeyStatus(keyStatus, providers) {
  const wrap = document.getElementById('settings-key-list');
  if (!wrap) return;
  const items = Object.entries(keyStatus).sort();
  if (!items.length) { wrap.innerHTML = '<em>冇 key env vars detected</em>'; return; }
  wrap.innerHTML = items.map(([name, isSet]) => {
    const cls = isSet ? 'key-set' : 'key-unset';
    const mark = isSet ? '✓' : '✗';
    return `<span class="settings-key-pill ${cls}">${mark} ${escapeHtml(name)}</span>`;
  }).join('');
}

function renderNodesTable(nodesMap, providers) {
  const section = document.getElementById('settings-nodes-section');
  if (!section) return;

  const PIPELINE_NODES = ['delabeling','explanation','filter','dispatcher'];
  const TRINITY_NODES  = ['father','son','spirit','council'];
  const NODE_LABELS = {
    delabeling:'去標籤', explanation:'四律分析', filter:'八律過濾', dispatcher:'Dispatcher',
    father:'聖父', son:'聖子', spirit:'聖靈', council:'Council',
  };
  const NODE_COLORS = {
    father:'#7F77DD', son:'#1D9E75', spirit:'#D85A30', council:'#378ADD',
    delabeling:'#888780', explanation:'#888780', filter:'#888780', dispatcher:'#888780',
  };

  section.innerHTML = `
    <div class="node-cards-section-label">分析管道</div>
    <div class="node-cards-grid" id="nc-pipeline"></div>
    <div class="node-cards-section-label">三位一體</div>
    <div class="node-cards-grid" id="nc-trinity"></div>`;

  const health = (settingsState.data && settingsState.data.health) || {};
  const provNames = (providers && providers.length)
    ? providers.map(p => (typeof p === 'object' ? p.name : p))
    : COMMON_PROVIDERS;

  function _nbClass(prov) {
    const m = {groq:'nb-groq',openrouter:'nb-openrouter',google:'nb-gemini',gemini:'nb-gemini',
               anthropic:'nb-anthropic',xai:'nb-xai',ollama:'nb-ollama'};
    return m[prov] || 'nb-other';
  }

  function renderCard(role, containerId) {
    const nd = nodesMap[role] || {};
    const h = health[nd.provider] || {};
    const container = document.getElementById(containerId);
    if (!container) return;

    const hClass = h.cooling ? 'hwarn' : (h.success > 0 ? 'hok' : 'hoff');
    const latency = h.last_latency_ms ? (h.last_latency_ms/1000).toFixed(1)+'s' : '';
    const stats = latency ? `${latency} · ${h.success||0}/${(h.success||0)+(h.fail||0)}` : '就緒';

    const card = document.createElement('div');
    card.className = 'node-card-v2';
    card.dataset.role = role;
    card.innerHTML = `
      <div class="nc-header">
        <div class="nc-role-dot" style="background:${NODE_COLORS[role]}"></div>
        <span class="nc-role-name">${NODE_LABELS[role]||role}</span>
        <span class="nc-provider-badge ${_nbClass(nd.provider)}">${escapeHtml(nd.provider||'—')}</span>
      </div>
      <div class="nc-model">${escapeHtml(nd.model||'')}</div>
      <div class="nc-stats"><div class="hdot ${hClass}"></div><span class="nc-stat-text">${escapeHtml(stats)}</span></div>
      <div class="nc-expanded-body">
        <div class="nc-field"><label>Provider</label>
          <select class="nc-provider-sel" data-role="${role}">
            ${provNames.map(pn => `<option${pn===nd.provider?' selected':''}>${escapeHtml(pn)}</option>`).join('')}
          </select>
        </div>
        <div class="nc-field"><label>Model</label>
          <input class="nc-model-inp" data-role="${role}" value="${escapeHtml(nd.model||'')}">
        </div>
        <div class="nc-field"><label>Temp</label>
          <input type="number" class="nc-temp-inp" data-role="${role}" value="${nd.temperature??0.7}" min="0" max="2" step="0.1" style="width:60px">
        </div>
        <div class="nc-field"><label>Max tokens</label>
          <input type="number" class="nc-tokens-inp" data-role="${role}" value="${nd.max_tokens??4096}" min="50" max="32000" style="width:80px">
        </div>
      </div>`;

    card.querySelector('.nc-header').addEventListener('click', () => card.classList.toggle('expanded'));

    card.querySelector('.nc-provider-sel').addEventListener('change', (e) => {
      const newProv = e.target.value;
      const provSpec = providers.find(p => (typeof p === 'object' ? p.name : p) === newProv);
      if (provSpec && settingsState.data && settingsState.data.nodes && settingsState.data.nodes[role]) {
        settingsState.data.nodes[role].api_base = provSpec.default_base || '';
        settingsState.data.nodes[role].api_key_env = provSpec.default_key_env || '';
      }
      settingsState.dirty = true;
    });

    container.appendChild(card);
  }

  PIPELINE_NODES.forEach(r => renderCard(r, 'nc-pipeline'));
  TRINITY_NODES.forEach(r => renderCard(r, 'nc-trinity'));

  section.removeEventListener('change', _debounceNodeSave);
  section.removeEventListener('input', _debounceNodeSave);
  section.addEventListener('change', _debounceNodeSave);
  section.addEventListener('input', _debounceNodeSave);
}

// v8.4 — Cross-session banner: surface attached history + one-shot Detach.
// Detach state lives on `window.__detachNextQuery` (cleared after each run).
window.__detachNextQuery = false;

// v8.7 — Trinity v7.2 Spirit Mode B chip + raw metadata renderers
// Developer mode = localStorage flag, default false. Toggle in Settings.
function getDeveloperMode() {
  return localStorage.getItem('uruk_developer_mode') === '1';
}
function setDeveloperMode(on) {
  localStorage.setItem('uruk_developer_mode', on ? '1' : '0');
  // Re-render every cached chip so dev-mode visibility updates live
  const spiritCache = window.__lastSpiritMeta || {};
  Object.values(spiritCache).forEach(meta => renderSpiritMetadata(meta));
  const sonCache = window.__lastSonVeto || {};
  Object.values(sonCache).forEach(meta => renderSonVetoMetadata(meta));
  const councilCache = window.__lastCouncilDecision || {};
  Object.values(councilCache).forEach(d => renderCouncilDecision(d));
}

function renderSpiritInterrupt(data) {
  const _mid = (data && data._mode_id) || '_default';
  const sonOut = getModeElement(_mid, 'output-son');
  const spiritOut = getModeElement(_mid, 'output-spirit');
  const fatherOut = getModeElement(_mid, 'output-father');
  // Visual cue: tag all three panels as re-scanning
  [sonOut, spiritOut, fatherOut].forEach(el => {
    if (el) el.classList.add('streaming');
  });
  const modeLabel = (_mid && _mid !== '_default') ? ` [${_mid}]` : '';
  const msg = `⚡ Spirit interrupt${modeLabel} #${data.rescan_count}/${data.rescan_cap} · `
            + `${data.trigger_mode} score=${data.semantic_score} mag=${data.magnitude}→${data.magnitude_rescan} · `
            + `「${data.primary_assumption || '(no assumption)'}」`;
  setStatus(msg, false, true);
}

function renderSpiritMetadata(data) {
  const _mid = (data && data._mode_id) || '_default';
  // Cache per-mode for dev-mode toggle re-render
  window.__lastSpiritMeta = window.__lastSpiritMeta || {};
  window.__lastSpiritMeta[_mid] = data;
  const spiritOut = getModeElement(_mid, 'output-spirit');
  if (!spiritOut) return;
  // Strip any previous chip from this run
  spiritOut.querySelectorAll('.spirit-meta-chip').forEach(el => el.remove());
  const tm = data.trigger_mode || 'NONE';
  const dev = getDeveloperMode();
  // Hide NONE chip in normal mode; show always in dev mode
  if (tm === 'NONE' && !dev && !data._parse_error) return;
  const wrap = document.createElement('div');
  wrap.className = 'spirit-meta-chip';
  let badge = '';
  switch (tm) {
    case 'SEMANTIC': badge = '🟡 SEMANTIC'; break;
    case 'STOCHASTIC': badge = '🎲 STOCHASTIC'; break;
    case 'STOCHASTIC+SEMANTIC': badge = '⚡ STOCHASTIC+SEMANTIC'; break;
    default: badge = '⚪ NONE';
  }
  const score = data.semantic_score ?? 0;
  const mag = (data.magnitude ?? 0).toFixed?.(1) ?? data.magnitude;
  const rc = data.rescan_count || 0;
  const rcSuffix = rc > 0 ? ` · rescan ×${rc}` : '';
  const parseErr = data._parse_error ? ` · ⚠ parse_error` : '';
  const assumption = data.primary_assumption ? ` · 「${escapeHtml(data.primary_assumption)}」` : '';
  const top = document.createElement('div');
  top.className = 'spirit-meta-top';
  top.innerHTML = `<b>${badge}</b> · score=${score} · mag=${mag}${rcSuffix}${parseErr}${assumption}`;
  wrap.appendChild(top);
  if (dev) {
    const det = document.createElement('details');
    det.className = 'spirit-meta-raw';
    const sum = document.createElement('summary');
    sum.textContent = 'raw metadata';
    det.appendChild(sum);
    const pre = document.createElement('pre');
    pre.textContent = JSON.stringify(data, null, 2);
    det.appendChild(pre);
    wrap.appendChild(det);
  }
  // Prepend so the chip sits at the top of the Spirit panel
  spiritOut.prepend(wrap);
}

// v8.9 Phase B — Son veto + Father pause renderers
function renderSonVetoMetadata(data) {
  const _mid = (data && data._mode_id) || '_default';
  window.__lastSonVeto = window.__lastSonVeto || {};
  window.__lastSonVeto[_mid] = data;
  const sonOut = getModeElement(_mid, 'output-son');
  if (!sonOut) return;
  sonOut.querySelectorAll('.son-veto-chip').forEach(el => el.remove());
  const vtype = data.veto_type || 'none';
  const dev = getDeveloperMode();
  // Hide 'none' chip in normal mode; always show veto-active variants
  if (vtype === 'none' && !dev && !data._parse_error) return;
  const wrap = document.createElement('div');
  wrap.className = 'son-veto-chip ' + (vtype === 'origin_echo' ? 'veto-origin' :
                                       vtype === 'authentic_suffering' ? 'veto-auth' :
                                       vtype === 'narrative_packaging' ? 'veto-narrative' :
                                       'veto-none');
  let badge;
  switch (vtype) {
    case 'origin_echo':         badge = '🚨 VETO · origin_echo'; break;
    case 'authentic_suffering': badge = '🚨 VETO · authentic_suffering'; break;
    case 'narrative_packaging': badge = '⚠ narrative_packaging'; break;
    default:                    badge = '⚪ veto=none';
  }
  const score = (data.authentic_suffering_score ?? 0).toFixed?.(2) ?? data.authentic_suffering_score;
  const cost = data.physical_cost_present ? 'cost=true' : 'cost=false';
  const locus = data.primary_pain_locus ? ` · 「${escapeHtml(data.primary_pain_locus)}」` : '';
  const parseErr = data._parse_error ? ` · ⚠ parse_error` : '';
  const top = document.createElement('div');
  top.className = 'son-veto-top';
  top.innerHTML = `<b>${badge}</b> · score=${score} · ${cost}${locus}${parseErr}`;
  wrap.appendChild(top);
  if (dev) {
    const det = document.createElement('details');
    det.className = 'son-veto-raw';
    const sum = document.createElement('summary');
    sum.textContent = 'raw son_veto_metadata';
    det.appendChild(sum);
    const pre = document.createElement('pre');
    pre.textContent = JSON.stringify(data, null, 2);
    det.appendChild(pre);
    wrap.appendChild(det);
  }
  sonOut.prepend(wrap);
}

// v8.14 BN — BrowserNode source audit chip + summary renderers
function renderSourceAudit(data) {
  const _mid = (data && data._mode_id) || '_default';
  const section = getModeElement(_mid, 'browser-audit-section');
  const list = getModeElement(_mid, 'browser-audit-list');
  const counter = getModeElement(_mid, 'browser-audit-counter');
  if (!section || !list) return;
  section.classList.remove('hidden');

  const rating = data.rating || 'UNVERIFIED';
  const cls = `rating-${escapeHtml(rating.toLowerCase())}`;
  const domain = data.domain || data.url || 'unknown';
  const coord = data.coordinate || 'unknown_unverified';
  const title = data.title || '';
  const snippet = data.snippet || '';
  const url = data.url || '#';

  const item = document.createElement('div');
  item.className = `browser-audit-item ${cls}`;
  const ratingIcon = {VERIFIED: '✓', PROBABLE: '◆', INFERRED: '◇', UNVERIFIED: '?'}[rating] || '?';
  item.innerHTML =
      `<div class="browser-audit-item-row1">`
    +   `<span class="browser-audit-rating ${cls}">${ratingIcon} ${escapeHtml(rating)}</span>`
    +   `<span class="browser-audit-domain">🌐 ${escapeHtml(domain)}</span>`
    +   `<span class="browser-audit-coord">「${escapeHtml(coord)}」</span>`
    + `</div>`
    + (title ? `<div class="browser-audit-title"><a href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(title)}</a></div>` : '')
    + (snippet ? `<div class="browser-audit-snippet">${escapeHtml(snippet)}</div>` : '');
  list.appendChild(item);

  // Update counter
  if (counter) {
    const count = list.querySelectorAll('.browser-audit-item').length;
    counter.textContent = `${count} source${count === 1 ? '' : 's'}`;
  }
}

function renderBrowserAuditSummary(data) {
  const _mid = (data && data._mode_id) || '_default';
  const summary = getModeElement(_mid, 'browser-audit-summary');
  if (!summary) return;
  const fetched = data.fetched ?? 0;
  const raw = data.raw_search_results ?? 0;
  const coords = data.unique_coordinates || [];
  const ok = !!data.spec_compliant;
  const errors = data.errors || [];
  const badge = ok
    ? `<span class="browser-audit-pass">✓ spec compliant</span>`
    : `<span class="browser-audit-fail">⚠ spec NOT met (need ≥${data.min_sources_required||3} sources / ≥${data.min_coords_required||2} coords)</span>`;
  // v8.15 MS-3 — engines_used sub-section
  const engines = Array.isArray(data.engines_used) ? data.engines_used : [];
  let enginesBlock = '';
  if (engines.length) {
    const rows = engines.map(e => {
      const reason = e.reason || '';
      const cls = `engine-used-reason-${reason.replace(/[^a-z_]/gi,'')}`;
      return `<div class="engine-used-row"><span class="engine-name">${escapeHtml(e.engine||'?')}</span> · <span class="${cls}">${escapeHtml(reason)}</span> · ${e.results_count ?? 0} result(s)</div>`;
    }).join('');
    enginesBlock = `<div class="engines-used-list"><b>engines used:</b>${rows}</div>`;
  }
  summary.innerHTML =
      badge
    + ` · fetched ${fetched}/${raw}`
    + ` · ${coords.length} unique coords`
    + (coords.length ? `: ${coords.map(escapeHtml).join(' / ')}` : '')
    + enginesBlock
    + (errors.length ? `<div class="browser-audit-errors">errors: ${errors.map(escapeHtml).join('; ')}</div>` : '');
  // Open the details by default if non-compliant or has errors
  const section = getModeElement(_mid, 'browser-audit-section');
  if (section && (!ok || errors.length > 0)) section.open = true;
}

// v8.14 Module N — Alignment Resonance chip (positive signal, detection-only)
function renderAlignmentResonance(data) {
  const _mid = (data && data._mode_id) || '_default';
  const councilOut = getModeElement(_mid, 'output-council');
  if (!councilOut) return;
  // Remove prior chip for this mode (idempotent re-render)
  councilOut.querySelectorAll('.alignment-chip').forEach(el => el.remove());

  const verPaths = data.verification_paths_count ?? 0;
  const primary = data.primary_anchor_law || '';
  const magnitude = (data.magnitude ?? 0).toFixed?.(2) ?? data.magnitude;
  const scores = data.score_breakdown || {};
  const universal = data.universal_axiom_claim ? ' · ✦ universal_axiom' : '';
  // Detect which laws cleared the threshold for the chip's "law X+Y+Z" label
  const clearedLaws = [];
  if ((scores.science_precision ?? 0) >= 0.85) clearedLaws.push('5');
  if ((scores.geography_anchor ?? 0) >= 0.85 || data.universal_axiom_claim) clearedLaws.push('7');
  if ((scores.art_frequency ?? 0) >= 0.7) clearedLaws.push('1');
  if (Math.abs((scores.physics_cost ?? 0) - 1.0) < 0.01) clearedLaws.push('3');
  const lawLabel = clearedLaws.length ? `律 ${clearedLaws.join('+')} 對齊` : '對齊';

  const wrap = document.createElement('div');
  wrap.className = 'alignment-chip';
  const top = document.createElement('div');
  top.className = 'alignment-chip-top';
  top.innerHTML = `<b>✨ KAIROS RESONANCE</b> · ${escapeHtml(lawLabel)} · magnitude ${magnitude} · 「${escapeHtml(primary)}」${universal}`;
  wrap.appendChild(top);

  const dev = getDeveloperMode();
  const det = document.createElement('details');
  det.className = 'alignment-chip-detail';
  if (dev) det.open = true;
  const sum = document.createElement('summary');
  sum.textContent = `verification paths: ${verPaths}/4 · 8-law score breakdown`;
  det.appendChild(sum);
  const tbl = document.createElement('table');
  tbl.className = 'alignment-score-table';
  const rows = [
    ['律一 art_frequency',          scores.art_frequency,         0.7],
    ['律二 psychology_defense',     scores.psychology_defense,    null],
    ['律三 physics_cost',           scores.physics_cost,          1.0],
    ['律四 chemistry_transformation', scores.chemistry_transformation, null],
    ['律五 science_precision',      scores.science_precision,     0.85],
    ['律六 philosophy_legislation', scores.philosophy_legislation, null],
    ['律七 geography_anchor',       scores.geography_anchor,      0.85],
    ['律八 temporal_encapsulation', scores.temporal_encapsulation, null],
  ];
  for (const [label, val, threshold] of rows) {
    const v = (val ?? 0).toFixed?.(2) ?? val;
    const cleared = threshold !== null && val !== undefined &&
      (threshold === 1.0 ? Math.abs(val - 1.0) < 0.01 : val >= threshold);
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${escapeHtml(label)}</td><td>${v}</td><td>${threshold !== null ? '≥ ' + threshold : '—'}</td><td>${cleared ? '✓' : ''}</td>`;
    if (cleared) tr.classList.add('cleared');
    tbl.appendChild(tr);
  }
  det.appendChild(tbl);
  wrap.appendChild(det);
  councilOut.prepend(wrap);

  const modeLabel = (_mid && _mid !== '_default') ? ` [${_mid}]` : '';
  setStatus(`✨ Alignment detected${modeLabel} — 內部座標 ↔ 外部物理現實 張力消失`, false);
}

// v8.9 Phase A — Council 4b decision chip (4c fusion is server-side deterministic)
function renderCouncilDecision(data) {
  const _mid = (data && data._mode_id) || '_default';
  window.__lastCouncilDecision = window.__lastCouncilDecision || {};
  window.__lastCouncilDecision[_mid] = data;
  const councilOut = getModeElement(_mid, 'output-council');
  if (!councilOut) return;
  councilOut.querySelectorAll('.council-decision-chip').forEach(el => el.remove());

  const verdict = data.verdict || 'consensus';
  const reason = data.reason || '';
  const weights = data.consensus_weights || {father: 1/3, son: 1/3, spirit: 1/3};
  const wf = Math.round((weights.father || 0) * 100);
  const ws = Math.round((weights.son || 0) * 100);
  const wsp = Math.round((weights.spirit || 0) * 100);
  const primDim = data.primary_dimension || '';
  const parseErr = data._parse_error ? ` · ⚠ parse_error` : '';
  const consistencyOverride = data._consistency_override ? ` · 🔒 phase-B override` : '';
  const dev = getDeveloperMode();

  let badge;
  let cls;
  switch (verdict) {
    case 'veto':
      badge = '⚖ VETO';
      cls = 'verdict-veto';
      break;
    case 'interrupt':
      badge = '⚡ INTERRUPT';
      cls = 'verdict-interrupt';
      break;
    default:
      badge = '🤝 CONSENSUS';
      cls = 'verdict-consensus';
  }

  const wrap = document.createElement('div');
  wrap.className = `council-decision-chip ${cls}`;
  const top = document.createElement('div');
  top.className = 'council-decision-top';
  let weightsStr = '';
  if (verdict === 'consensus' || verdict === 'interrupt') {
    weightsStr = ` · F${wf}% S${ws}% Sp${wsp}%`;
  }
  top.innerHTML = `<b>${badge}</b>`
                + (reason ? ` · ${escapeHtml(reason)}` : '')
                + weightsStr
                + (primDim ? ` · 「${escapeHtml(primDim)}」` : '')
                + parseErr
                + consistencyOverride;
  wrap.appendChild(top);
  if (dev) {
    const det = document.createElement('details');
    det.className = 'council-decision-raw';
    const sum = document.createElement('summary');
    sum.textContent = 'raw council_decision';
    det.appendChild(sum);
    const pre = document.createElement('pre');
    pre.textContent = JSON.stringify(data, null, 2);
    det.appendChild(pre);
    wrap.appendChild(det);
  }
  councilOut.prepend(wrap);

  // Status bar surface: veto / interrupt only
  const modeLabel = (_mid && _mid !== '_default') ? ` [${_mid}]` : '';
  if (verdict === 'veto') {
    setStatus(`⚖ Council VETO${modeLabel} · ${reason}`, true);
  } else if (verdict === 'interrupt') {
    setStatus(`⚡ Council INTERRUPT${modeLabel} · ${reason}`, false);
  }
}

function renderFatherPaused(data) {
  const _mid = (data && data._mode_id) || '_default';
  const fatherOut = getModeElement(_mid, 'output-father');
  if (!fatherOut) return;
  // Replace existing content with paused chip + reason details
  fatherOut.innerHTML = '';
  fatherOut.classList.remove('streaming', 'error');
  fatherOut.classList.add('father-paused');
  const wrap = document.createElement('div');
  wrap.className = 'father-paused-chip';
  const vtype = data.veto_type || 'unknown';
  const score = (data.authentic_suffering_score ?? 0).toFixed?.(2) ?? data.authentic_suffering_score;
  const cost = data.physical_cost_present;
  const locus = data.primary_pain_locus || '(no locus)';
  wrap.innerHTML =
    `<div class="father-paused-badge"><b>⛔ 聖父被否決</b></div>`
    + `<div class="father-paused-meta">`
    +   `<div>veto_type: <code>${escapeHtml(vtype)}</code></div>`
    +   `<div>authentic_suffering: <code>${score}</code></div>`
    +   `<div>physical_cost_present: <code>${cost}</code></div>`
    +   `<div>primary_pain_locus: 「${escapeHtml(locus)}」</div>`
    + `</div>`
    + `<div class="father-paused-note">Son veto active — Father LLM call skipped per Trinity v7.2 spec.</div>`;
  fatherOut.appendChild(wrap);
  const modeLabel = (_mid && _mid !== '_default') ? ` [${_mid}]` : '';
  setStatus(`⛔ Father paused${modeLabel} — Son veto active (${vtype})`, true);
}

function renderCrossSessionBanner(data) {
  const banner = document.getElementById('cross-session-banner');
  const textEl = document.getElementById('cs-banner-text');
  if (!banner || !textEl) return;
  const n = data.n_sessions || 0;
  if (n === 0) {
    banner.classList.add('hidden');
    return;
  }
  const lastTs = (data.last_timestamp || '').slice(0, 16).replace('T', ' ');
  const lastLabel = data.last_label || '(unlabeled)';
  textEl.innerHTML = `Continuing from <b>${n}</b> prior session${n > 1 ? 's' : ''} (last: <code>${escapeHtml(lastTs)} "${escapeHtml(lastLabel)}"</code>) · mode: <b>${escapeHtml(data.mode || 'summary')}</b>`;
  banner.classList.remove('hidden', 'detached');
}

// One-shot detach + View wiring (idempotent)
document.addEventListener('DOMContentLoaded', () => {
  const detachBtn = document.getElementById('cs-banner-detach');
  const viewBtn = document.getElementById('cs-banner-view');
  if (detachBtn) {
    detachBtn.addEventListener('click', () => {
      window.__detachNextQuery = true;
      document.getElementById('cross-session-banner')?.classList.add('detached');
      setStatus('🔗 History detached for next query (Settings toggle remains as persistent control)');
    });
  }
  if (viewBtn) {
    viewBtn.addEventListener('click', () => {
      // Switch sidebar to the session-history tab so user sees recent sessions.
      document.querySelector('[data-tab="kairos"]')?.click();
    });
  }
});

// v8.3 — populate <datalist> from /api/providers/models?provider=X.
// Hint-only: the underlying <input> remains freeform. Cached per provider.
const __modelHintCache = {};
async function refreshModelDatalist(datalistId, provider) {
  const dl = document.getElementById(datalistId);
  if (!dl || !provider) return;
  let models = __modelHintCache[provider];
  if (!models) {
    try {
      const r = await fetch(`/api/providers/models?provider=${encodeURIComponent(provider)}`);
      if (!r.ok) return;
      const data = await r.json();
      models = data.models || [];
      __modelHintCache[provider] = models;
    } catch (_e) { return; }
  }
  dl.innerHTML = models.map(m => `<option value="${escapeHtml(m)}"></option>`).join('');
}

function setNodeRow(role, spec) {
  const section = document.getElementById('settings-nodes-section');
  if (!section) return;
  const card = section.querySelector(`.node-card-v2[data-role="${CSS.escape(role)}"]`);
  if (!card) return;
  const fieldMap = {
    provider: '.nc-provider-sel',
    model: '.nc-model-inp',
    temperature: '.nc-temp-inp',
    max_tokens: '.nc-tokens-inp',
  };
  Object.entries(fieldMap).forEach(([field, sel]) => {
    if (spec[field] === undefined || spec[field] === null) return;
    const el = card.querySelector(sel);
    if (el) el.value = spec[field];
  });
  // Keep stored api_base/api_key_env in sync too
  if (settingsState.data && settingsState.data.nodes && settingsState.data.nodes[role]) {
    if (spec.api_base !== undefined) settingsState.data.nodes[role].api_base = spec.api_base;
    if (spec.api_key_env !== undefined) settingsState.data.nodes[role].api_key_env = spec.api_key_env;
  }
}

let _nodeDebounceTimer = null;
function _debounceNodeSave() {
  settingsState.dirty = true;
  clearTimeout(_nodeDebounceTimer);
  _nodeDebounceTimer = setTimeout(() => saveSettings(), 300);
}

function collectNodesPayload() {
  const section = document.getElementById('settings-nodes-section');
  if (!section) return null;
  const payload = { nodes: {}, per_node_fallback: {} };
  section.querySelectorAll('.node-card-v2[data-role]').forEach(card => {
    const role = card.dataset.role;
    const existing = (settingsState.data && settingsState.data.nodes && settingsState.data.nodes[role]) || {};
    const provSel   = card.querySelector('.nc-provider-sel');
    const modelInp  = card.querySelector('.nc-model-inp');
    const tempInp   = card.querySelector('.nc-temp-inp');
    const tokInp    = card.querySelector('.nc-tokens-inp');
    payload.nodes[role] = {
      provider:    provSel  ? provSel.value              : (existing.provider    || ''),
      model:       modelInp ? modelInp.value.trim()      : (existing.model       || ''),
      api_base:    existing.api_base    || '',
      api_key_env: existing.api_key_env || '',
      temperature: tempInp  ? parseFloat(tempInp.value)  : (existing.temperature ?? 0.7),
      max_tokens:  tokInp   ? parseInt(tokInp.value, 10) : (existing.max_tokens  ?? 4096),
    };
    // Per-node fallback preserved from loaded state
    if (Array.isArray(existing.fallback) && existing.fallback.length) {
      payload.per_node_fallback[role] = existing.fallback;
    }
  });
  const fo = collectFailoverPayload();
  if (fo) {
    payload.api_profiles = fo.api_profiles;
    payload.failover = fo.failover;
  }
  payload.cross_session = collectCrossSessionPayload();
  return payload;
}

async function saveSettings() {
  setSettingsError('');
  setSettingsStatus('Saving...', true);
  const payload = collectNodesPayload();
  if (!payload) { setSettingsError('Cannot collect form data'); return; }
  try {
    const r = await fetch('/api/nodes/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const body = await r.json();
    if (!r.ok) {
      setSettingsError('Save fail: ' + (body.detail || JSON.stringify(body)));
      setSettingsStatus('', false);
      return;
    }
    settingsState.dirty = false;
    if (body.applied_immediately) {
      setSettingsStatus(`✓ Saved + reloaded. ${body.nodes_loaded.length} nodes active.`, true);
    } else if (body.restart_needed) {
      setSettingsStatus(`⚠ Saved but reload failed: ${body.reload_error}. 需要 restart py app.py.`, false);
    } else {
      setSettingsStatus('✓ Saved.', true);
    }
  } catch (e) {
    setSettingsError('Network error: ' + e.message);
    setSettingsStatus('', false);
  }
}

async function reloadFromDisk() {
  setSettingsError('');
  setSettingsStatus('Reloading from disk...', true);
  try {
    const r = await fetch('/api/nodes/reload', { method: 'POST' });
    const body = await r.json();
    if (!r.ok) {
      setSettingsError('Reload fail: ' + (body.detail || JSON.stringify(body)));
      setSettingsStatus('', false);
      return;
    }
    setSettingsStatus(`✓ Reloaded ${(body.nodes || []).length} nodes from disk.`, true);
    openSettingsModal();
  } catch (e) {
    setSettingsError('Network error: ' + e.message);
    setSettingsStatus('', false);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const btn = document.getElementById('settings-btn');
  if (btn) btn.addEventListener('click', openSettingsModal);
  const saveBtn = document.getElementById('settings-save');
  if (saveBtn) saveBtn.addEventListener('click', saveSettings);
  const reloadBtn = document.getElementById('settings-reload-only');
  if (reloadBtn) reloadBtn.addEventListener('click', reloadFromDisk);

  // v8.2: API pill + popover + stress test wiring
  initApiPillWiring();
});

// ═══════════════════════════════════════════════════════════════
// v8.2: Failover sections (profiles editor + chain + health)
// ═══════════════════════════════════════════════════════════════

const COMMON_PROVIDERS = ['gemini', 'openrouter', 'openai', 'anthropic', 'groq', 'cerebras', 'xai', 'ollama'];

function _getProviderBadgeClass(provider) {
  const m = {openrouter:'pb-openrouter',openai:'pb-openai',google:'pb-google',gemini:'pb-google',
             groq:'pb-groq',cerebras:'pb-cerebras',xai:'pb-xai',anthropic:'pb-anthropic',
             ollama:'pb-ollama',local:'pb-local',desktop:'pb-desktop'};
  return m[provider] || 'pb-stub';
}

function _makeProviderRow(name, prof, health) {
  const h = (health || {})[name] || {};
  const enabled = prof.enabled !== false;
  const STUBS = ['grok_web', 'gemini_web'];
  const isStub = STUBS.includes(name);

  const row = document.createElement('div');
  row.className = 'provider-row' + (enabled ? '' : ' disabled-row');
  row.dataset.name = name;

  const latency = h.last_latency_ms ? (h.last_latency_ms/1000).toFixed(1)+'s' : null;
  const statusHtml = isStub
    ? '<span class="pr-status-text pst-stub">未實現</span>'
    : h.cooling
      ? '<span class="pr-status-text pst-warn"><i class="ti ti-clock"></i> 冷卻</span>'
      : latency
        ? `<span class="pr-status-text pst-ok"><i class="ti ti-check"></i> ${latency}</span>`
        : enabled
          ? '<span class="pr-status-text pst-off">就緒</span>'
          : '<span class="pr-status-text pst-off">停用</span>';

  const provBadge = _getProviderBadgeClass(prof.provider || '');

  row.innerHTML = `
    <button class="pr-toggle-v2 ${enabled ? 'on' : ''}" data-name="${escapeHtml(name)}" aria-label="toggle ${escapeHtml(name)}"></button>
    <div class="pr-info">
      <div class="pr-name">${escapeHtml(name)}</div>
      <div class="pr-meta">
        <span class="provider-badge ${provBadge}">${escapeHtml(prof.provider || '—')}</span>
        <span>${escapeHtml(prof.default_model || '')}</span>
      </div>
    </div>
    ${statusHtml}
    <button class="pr-edit-btn" data-name="${escapeHtml(name)}" title="編輯"><i class="ti ti-edit"></i></button>`;

  row.querySelector('.pr-toggle-v2').addEventListener('click', (e) => {
    e.stopPropagation();
    _toggleProvider(name, !enabled);
  });
  row.querySelector('.pr-edit-btn').addEventListener('click', (e) => {
    e.stopPropagation();
    _openProviderEditor(name, prof);
  });
  return row;
}

function _toggleProvider(name, enabled) {
  if (!settingsState.data || !settingsState.data.api_profiles) return;
  settingsState.data.api_profiles[name].enabled = enabled;
  settingsState.dirty = true;
  const providers = settingsState.data.providers || [];
  renderProfilesTable(settingsState.data.api_profiles, providers);
}

function _openProviderEditor(name, prof) {
  const container = document.getElementById('settings-provider-list');
  if (!container) return;
  container.querySelectorAll('.pr-editor-row').forEach(el => el.remove());

  const row = container.querySelector(`.provider-row[data-name="${CSS.escape(name)}"]`);
  if (!row) return;

  const providers = settingsState.data && settingsState.data.providers || [];
  const provNames = providers.length
    ? providers.map(p => (typeof p === 'object' ? p.name : p))
    : COMMON_PROVIDERS;

  const editor = document.createElement('div');
  editor.className = 'pr-editor-row';
  editor.style.cssText = 'padding:8px 12px;background:var(--color-background-secondary);border-bottom:0.5px solid var(--color-border-tertiary)';
  editor.innerHTML = `
    <div class="nc-field"><label>Name</label>
      <input class="pr-ed-name" value="${escapeHtml(name)}" style="flex:1;font-size:11px;padding:3px 6px;border:0.5px solid var(--color-border-tertiary);border-radius:4px;background:var(--color-background-primary);color:var(--color-text-primary)">
    </div>
    <div class="nc-field"><label>Provider</label>
      <select class="pr-ed-provider" style="flex:1;font-size:11px;padding:3px 6px;border:0.5px solid var(--color-border-tertiary);border-radius:4px;background:var(--color-background-primary);color:var(--color-text-primary)">
        ${provNames.map(pn => `<option${pn===(prof.provider||'')?` selected`:''}>${escapeHtml(pn)}</option>`).join('')}
      </select>
    </div>
    <div class="nc-field"><label>API Base</label>
      <input class="pr-ed-base" value="${escapeHtml(prof.api_base||'')}" placeholder="https://..." style="flex:1;font-size:11px;padding:3px 6px;border:0.5px solid var(--color-border-tertiary);border-radius:4px;background:var(--color-background-primary);color:var(--color-text-primary)">
    </div>
    <div class="nc-field"><label>Key Env</label>
      <input class="pr-ed-key" value="${escapeHtml(prof.api_key_env||'')}" placeholder="KEY_ENV" style="flex:1;font-size:11px;padding:3px 6px;border:0.5px solid var(--color-border-tertiary);border-radius:4px;background:var(--color-background-primary);color:var(--color-text-primary)">
    </div>
    <div class="nc-field"><label>Model</label>
      <input class="pr-ed-model" value="${escapeHtml(prof.default_model||'')}" placeholder="model name" style="flex:1;font-size:11px;padding:3px 6px;border:0.5px solid var(--color-border-tertiary);border-radius:4px;background:var(--color-background-primary);color:var(--color-text-primary)">
    </div>
    <div style="display:flex;gap:6px;margin-top:6px">
      <button class="pr-ed-save" style="font-size:11px;padding:3px 10px;border-radius:4px;background:#7F77DD;color:#fff;border:none;cursor:pointer">Save</button>
      <button class="pr-ed-delete" style="font-size:11px;padding:3px 10px;border-radius:4px;background:transparent;border:0.5px solid #e57373;color:#e57373;cursor:pointer">Delete</button>
      <button class="pr-ed-cancel" style="font-size:11px;padding:3px 10px;border-radius:4px;background:transparent;border:0.5px solid var(--color-border-tertiary);color:var(--color-text-secondary);cursor:pointer">Cancel</button>
    </div>`;

  row.insertAdjacentElement('afterend', editor);

  editor.querySelector('.pr-ed-cancel').addEventListener('click', () => editor.remove());

  editor.querySelector('.pr-ed-delete').addEventListener('click', () => {
    if (!settingsState.data || !settingsState.data.api_profiles) return;
    delete settingsState.data.api_profiles[name];
    settingsState.dirty = true;
    editor.remove();
    renderProfilesTable(settingsState.data.api_profiles, providers);
    document.querySelectorAll(`#settings-chain-list li[data-name="${CSS.escape(name)}"]`).forEach(li => li.remove());
  });

  editor.querySelector('.pr-ed-save').addEventListener('click', () => {
    if (!settingsState.data || !settingsState.data.api_profiles) return;
    const newName = editor.querySelector('.pr-ed-name').value.trim();
    if (!newName) { alert('Name cannot be empty'); return; }
    const existing = settingsState.data.api_profiles[name] || {};
    const updated = {
      provider:      editor.querySelector('.pr-ed-provider').value,
      api_base:      editor.querySelector('.pr-ed-base').value.trim(),
      api_key_env:   editor.querySelector('.pr-ed-key').value.trim(),
      default_model: editor.querySelector('.pr-ed-model').value.trim(),
      enabled:       existing.enabled !== false,
    };
    if (newName !== name) {
      delete settingsState.data.api_profiles[name];
      document.querySelectorAll(`#settings-chain-list li[data-name="${CSS.escape(name)}"]`).forEach(li => { li.dataset.name = newName; });
    }
    settingsState.data.api_profiles[newName] = updated;
    settingsState.dirty = true;
    editor.remove();
    renderProfilesTable(settingsState.data.api_profiles, providers);
  });
}

function renderProfilesTable(profilesMap, providers) {
  let container = document.getElementById('settings-provider-list');
  if (!container) {
    const wrap = document.getElementById('settings-profiles-table-wrap');
    if (!wrap) return;
    container = document.createElement('div');
    container.id = 'settings-provider-list';
    wrap.parentNode.replaceChild(container, wrap);
  } else {
    container.innerHTML = '';
  }

  const health = (settingsState.data && settingsState.data.health) || {};
  const STUBS = ['grok_web', 'gemini_web'];
  const enabled = [], disabled = [];

  Object.entries(profilesMap).forEach(([name, prof]) => {
    if (STUBS.includes(name) || prof.enabled === false) disabled.push([name, prof]);
    else enabled.push([name, prof]);
  });

  if (enabled.length) {
    const lbl = document.createElement('div');
    lbl.className = 'provider-group-label';
    lbl.textContent = '已啟用';
    container.appendChild(lbl);
    enabled.forEach(([name, prof]) => container.appendChild(_makeProviderRow(name, prof, health)));
  }
  if (disabled.length) {
    const lbl = document.createElement('div');
    lbl.className = 'provider-group-label';
    lbl.textContent = '停用 / 缺少 key';
    container.appendChild(lbl);
    disabled.forEach(([name, prof]) => container.appendChild(_makeProviderRow(name, prof, health)));
  }
}

function renderChainList(chain, profilesMap) {
  const ul = document.getElementById('settings-chain-list');
  if (!ul) return;
  ul.innerHTML = '';
  (chain || []).forEach(name => addChainEntry(ul, name, profilesMap));
  // Allow drop on the empty list itself
  ul.addEventListener('dragover', (e) => e.preventDefault());
}

function addChainEntry(ul, name, profilesMap) {
  const li = document.createElement('li');
  li.dataset.name = name;
  li.draggable = true;
  const exists = profilesMap && profilesMap[name];
  li.innerHTML = `
    <span class="chain-order">≡</span>
    <span class="chain-name">${escapeHtml(name)}${exists ? '' : ' <em style="color:#e57373">(unknown)</em>'}</span>
    <button class="chain-remove" type="button" title="Remove">×</button>
  `;
  li.querySelector('.chain-remove').addEventListener('click', () => {
    li.remove();
    settingsState.dirty = true;
  });
  // Drag handlers — pure HTML5 DnD
  li.addEventListener('dragstart', (e) => {
    li.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', name);
  });
  li.addEventListener('dragend', () => li.classList.remove('dragging'));
  li.addEventListener('dragover', (e) => {
    e.preventDefault();
    li.classList.add('drag-over');
  });
  li.addEventListener('dragleave', () => li.classList.remove('drag-over'));
  li.addEventListener('drop', (e) => {
    e.preventDefault();
    li.classList.remove('drag-over');
    const dragging = ul.querySelector('.dragging');
    if (dragging && dragging !== li) {
      ul.insertBefore(dragging, li);
      settingsState.dirty = true;
    }
  });
  ul.appendChild(li);
}

function renderFailoverControls(failover) {
  const enabled = document.getElementById('settings-failover-enabled');
  const cd = document.getElementById('settings-cooldown');
  if (enabled) enabled.checked = failover.enabled !== false;
  if (cd) cd.value = failover.cooldown_seconds ?? 300;
  if (enabled) enabled.addEventListener('change', () => { settingsState.dirty = true; }, { once: true });
  if (cd) cd.addEventListener('input', () => { settingsState.dirty = true; }, { once: true });
}

// v8.4 — Cross-session memory section
function renderCrossSessionControls(cs) {
  const c = cs || {};
  const enabledEl = document.getElementById('cs-enabled');
  const nEl = document.getElementById('cs-n-recent');
  if (enabledEl) enabledEl.checked = c.enabled !== false;
  if (nEl) nEl.value = c.n_recent ?? 3;
  const modeVal = c.mode || 'summary';
  document.querySelectorAll('input[name="cs-mode"]').forEach(r => {
    r.checked = (r.value === modeVal);
  });
  if (enabledEl) enabledEl.addEventListener('change', () => { settingsState.dirty = true; }, { once: true });
  if (nEl) nEl.addEventListener('input', () => { settingsState.dirty = true; }, { once: true });
  document.querySelectorAll('input[name="cs-mode"]').forEach(r => {
    r.addEventListener('change', () => { settingsState.dirty = true; }, { once: true });
  });
}

function collectCrossSessionPayload() {
  const enabledEl = document.getElementById('cs-enabled');
  const nEl = document.getElementById('cs-n-recent');
  const modeEl = document.querySelector('input[name="cs-mode"]:checked');
  return {
    enabled: enabledEl ? enabledEl.checked : true,
    n_recent: nEl ? Math.max(1, Math.min(10, parseInt(nEl.value, 10) || 3)) : 3,
    mode: modeEl ? modeEl.value : 'summary',
  };
}

function renderHealthGrid(healthMap, cooldownSeconds) {
  const grid = document.getElementById('settings-health-grid');
  if (!grid) return;
  grid.innerHTML = '';
  const entries = Object.entries(healthMap);
  if (!entries.length) {
    grid.innerHTML = '<em style="color:var(--text-dim);grid-column:1/-1">未發過 call — 跑個 stress test 或者問返 1 turn 就有數字</em>';
    return;
  }
  entries.forEach(([name, h]) => {
    const cls = h.cooling ? 'cooling'
              : (h.success_rate !== null && h.success_rate < 0.5) ? 'bad'
              : (h.success > 0) ? 'ok' : '';
    const card = document.createElement('div');
    card.className = `health-card ${cls}`;
    card.innerHTML = `
      <div class="health-card-name">
        <span class="dot ${cls === 'bad' ? 'bad' : (cls === 'cooling' ? 'cool' : (h.success > 0 ? 'ok' : ''))}"></span>
        ${escapeHtml(name)}
      </div>
      <div class="health-card-stat"><span>success</span><span>${h.success}</span></div>
      <div class="health-card-stat"><span>fail</span><span>${h.fail}</span></div>
      <div class="health-card-stat"><span>latency</span><span>${h.last_latency_ms} ms</span></div>
      <div class="health-card-stat"><span>failover</span><span>${h.failover_count}</span></div>
      ${h.cooling ? `<div class="health-card-stat" style="color:#64b5f6"><span>cooling</span><span>${h.cooldown_remaining_s}s</span></div>` : ''}
      ${h.last_error ? `<div class="health-card-error" title="${escapeHtml(h.last_error)}">${escapeHtml(h.last_trigger || '')}: ${escapeHtml((h.last_error || '').slice(0, 60))}</div>` : ''}
    `;
    grid.appendChild(card);
  });
}

function collectFailoverPayload() {
  // Profiles — read from in-memory settingsState (kept in sync by toggle/editor)
  const api_profiles = (settingsState.data && settingsState.data.api_profiles) || {};
  // Chain
  const chainList = document.getElementById('settings-chain-list');
  const global_chain = chainList
    ? Array.from(chainList.children).map(li => li.dataset.name).filter(Boolean)
    : [];
  const enabledEl = document.getElementById('settings-failover-enabled');
  const cdEl = document.getElementById('settings-cooldown');
  const failover = {
    enabled: enabledEl ? enabledEl.checked : true,
    cooldown_seconds: cdEl ? parseFloat(cdEl.value) || 300 : 300,
    global_chain,
    trigger_on: ['http_429', 'http_5xx', 'quota', 'timeout', 'network'],
  };
  return { api_profiles, failover };
}

// "+ Add profile" button
function wireAddProfileButton() {
  const btn = document.getElementById('settings-profile-add');
  if (!btn || btn.dataset.wired) return;
  btn.dataset.wired = '1';
  btn.addEventListener('click', () => {
    if (!settingsState.data) return;
    const profiles = settingsState.data.api_profiles || {};
    const providers = settingsState.data.providers || [];
    // Generate a unique placeholder name
    let newName = 'new_provider';
    let i = 2;
    while (profiles[newName]) { newName = `new_provider_${i++}`; }
    profiles[newName] = { provider: 'groq', api_base: '', api_key_env: '', default_model: '', enabled: true };
    settingsState.data.api_profiles = profiles;
    settingsState.dirty = true;
    renderProfilesTable(profiles, providers);
    _openProviderEditor(newName, profiles[newName]);
  });
}

// ═══════════════════════════════════════════════════════════════
// v8.2: Health polling (modal-scoped)
// ═══════════════════════════════════════════════════════════════

let healthPollTimer = null;
let pillPollTimer = null;
let pillState = { primary: null, chain: [], health: {}, profiles: {} };

function startHealthPolling() {
  stopHealthPolling();
  healthPollTimer = setInterval(async () => {
    const modal = document.getElementById('settings-modal');
    if (!modal || modal.classList.contains('hidden')) {
      stopHealthPolling();
      return;
    }
    try {
      const r = await fetch('/api/nodes/health');
      if (!r.ok) return;
      const data = await r.json();
      const cd = settingsState.data?.failover?.cooldown_seconds || 300;
      renderHealthGrid(data.health || {}, cd);
    } catch (_e) { /* ignore — transient */ }
  }, 2000);
}

function stopHealthPolling() {
  if (healthPollTimer) { clearInterval(healthPollTimer); healthPollTimer = null; }
}

// ═══════════════════════════════════════════════════════════════
// v8.2: Toolbar API pill + popover
// ═══════════════════════════════════════════════════════════════

function initApiPillWiring() {
  const pill = document.getElementById('api-pill');
  const popover = document.getElementById('api-popover');
  if (!pill || !popover) return;

  pill.addEventListener('click', (e) => {
    e.stopPropagation();
    const isOpen = !popover.classList.contains('hidden');
    if (isOpen) { closeApiPopover(); }
    else { openApiPopover(); }
  });

  // Click outside → close
  document.addEventListener('click', (e) => {
    if (popover.classList.contains('hidden')) return;
    if (popover.contains(e.target) || pill.contains(e.target)) return;
    closeApiPopover();
  });

  // Footer buttons
  document.getElementById('api-popover-advanced')?.addEventListener('click', () => {
    closeApiPopover();
    openSettingsModal();
  });
  document.getElementById('api-popover-stress')?.addEventListener('click', () => {
    closeApiPopover();
    openStressModal();
  });
  document.getElementById('api-popover-reset-health')?.addEventListener('click', async () => {
    try {
      const response = await fetch('/api/nodes/health/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      if (!response.ok) {
        let message = `健康重設失敗 (${response.status})`;
        try {
          const payload = await response.json();
          message = payload?.detail?.message || payload?.detail || message;
        } catch (_parseError) { /* use status fallback */ }
        setStatus(String(message), true);
        return;
      }
      refreshPill();
      renderApiPopover();
    } catch (_e) { /* ignore */ }
  });

  // Stress test modal wiring
  document.getElementById('stress-go')?.addEventListener('click', runStressTest);
  document.getElementById('stress-target')?.addEventListener('change', syncStressTargetUI);
  // v8.5 — toggle cooldown-override numeric input alongside the checkbox
  const cdEnable = document.getElementById('stress-cooldown-override-enable');
  const cdValue = document.getElementById('stress-cooldown-override-value');
  if (cdEnable && cdValue) {
    cdEnable.addEventListener('change', () => {
      cdValue.disabled = !cdEnable.checked;
    });
  }

  // Initial fetch + slow background poll (every 5s when popover closed, 2s when open)
  refreshPill();
  setInterval(refreshPill, 5000);
}

async function refreshPill() {
  try {
    const r = await fetch('/api/nodes/health');
    if (!r.ok) return;
    const data = await r.json();
    pillState.primary = data.active?.primary || null;
    pillState.chain = data.active?.chain || [];
    pillState.health = data.health || {};
    // Profiles known to backend (need full config — lighter to skip; popover fetches its own copy)
    updatePillView();
    if (!document.getElementById('api-popover').classList.contains('hidden')) {
      renderApiPopover();
    }
  } catch (_e) { /* ignore */ }
}

function updatePillView() {
  const nameEl = document.getElementById('api-pill-name');
  const statsEl = document.getElementById('api-pill-stats');
  const pill = document.getElementById('api-pill');
  if (!nameEl) return;
  const primaryName = pillState.primary || '(none)';
  nameEl.textContent = primaryName;
  const h = pillState.health[primaryName];
  if (h) {
    statsEl.textContent = `${h.success}↑ ${h.fail}↓`;
    const rate = h.success_rate;
    pill.classList.remove('health-ok', 'health-warn', 'health-bad');
    if (h.cooling || (rate !== null && rate < 0.3)) pill.classList.add('health-bad');
    else if (rate !== null && rate < 0.8)            pill.classList.add('health-warn');
    else if (h.success > 0)                          pill.classList.add('health-ok');
  } else {
    statsEl.textContent = '—';
    pill.classList.remove('health-ok', 'health-warn', 'health-bad');
  }
}

async function openApiPopover() {
  const popover = document.getElementById('api-popover');
  if (!popover) return;
  popover.classList.remove('hidden');
  // Pull full config so we know the profile list (not just chain)
  try {
    const r = await fetch('/api/nodes/config');
    if (r.ok) {
      const data = await r.json();
      pillState.profiles = data.api_profiles || {};
      pillState.chain = data.failover?.global_chain || [];
      pillState.health = data.health || {};
      pillState.primary = data.active?.primary || null;
    }
  } catch (_e) { /* ignore */ }
  renderApiPopover();
}

function closeApiPopover() {
  document.getElementById('api-popover')?.classList.add('hidden');
}

function renderApiPopover() {
  const ul = document.getElementById('api-popover-list');
  if (!ul) return;
  ul.innerHTML = '';

  const seen = new Set();
  const ordered = [];
  pillState.chain.forEach(n => { if (pillState.profiles[n]) { ordered.push(n); seen.add(n); } });
  Object.keys(pillState.profiles).forEach(n => { if (!seen.has(n)) ordered.push(n); });

  ordered.forEach((name, idx) => {
    const p = pillState.profiles[name] || {};
    const h = pillState.health[name] || {};
    const isPrimary = name === pillState.primary;
    const hClass = h.cooling ? 'hwarn'
                 : (h.success > 0 && h.fail === 0) ? 'hok'
                 : h.fail > 0 ? 'hbad' : 'hoff';
    const latency = h.last_latency_ms ? (h.last_latency_ms/1000).toFixed(1)+'s'
                  : h.cooling ? '冷卻' : '—';

    const item = document.createElement('div');
    item.className = 'chain-item-v2' + (isPrimary ? ' primary' : '');
    item.dataset.name = name;
    item.draggable = true;
    item.innerHTML = `
      <span class="chain-num">${idx+1}</span>
      <div class="chain-info">
        <div class="chain-name">${escapeHtml(name)}</div>
        <div class="chain-model">${escapeHtml(p.default_model || '')}</div>
      </div>
      <div class="hdot ${hClass}" title="${h.success||0} ok / ${h.fail||0} fail"></div>
      <span class="chain-latency">${latency}</span>
      <span style="font-size:14px;color:var(--color-text-secondary);cursor:grab"><i class="ti ti-grip-vertical"></i></span>`;

    item.addEventListener('click', () => switchActiveProfile(name));

    item.addEventListener('dragstart', (e) => {
      item.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', name);
    });
    item.addEventListener('dragend', () => item.classList.remove('dragging'));
    item.addEventListener('dragover', (e) => { e.preventDefault(); item.classList.add('drag-over'); });
    item.addEventListener('dragleave', () => item.classList.remove('drag-over'));
    item.addEventListener('drop', (e) => {
      e.preventDefault();
      item.classList.remove('drag-over');
      const dragging = ul.querySelector('.chain-item-v2.dragging');
      if (dragging && dragging !== item) {
        ul.insertBefore(dragging, item);
        saveChainOrder();
      }
    });

    ul.appendChild(item);
  });
}

async function saveChainOrder() {
  const ul = document.getElementById('api-popover-list');
  const newChain = Array.from(ul.children).map(li => li.dataset.name).filter(n => pillState.profiles[n]);
  pillState.chain = newChain;
  // Persist via /api/nodes/config — keep nodes section as-is from current settings load
  try {
    const r = await fetch('/api/nodes/config');
    if (!r.ok) return;
    const data = await r.json();
    const payload = {
      nodes: stripFallback(data.nodes),
      per_node_fallback: rebuildPerNodeFallback(data.nodes),
      api_profiles: data.api_profiles || {},
      failover: { ...(data.failover || {}), global_chain: newChain },
    };
    await fetch('/api/nodes/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  } catch (_e) { /* ignore */ }
}

function stripFallback(nodes) {
  const out = {};
  Object.entries(nodes).forEach(([role, spec]) => {
    if (!spec) return;
    const { fallback, ...rest } = spec;
    out[role] = rest;
  });
  return out;
}

function rebuildPerNodeFallback(nodes) {
  const out = {};
  Object.entries(nodes).forEach(([role, spec]) => {
    if (spec && Array.isArray(spec.fallback) && spec.fallback.length) out[role] = spec.fallback;
  });
  return out;
}

async function switchActiveProfile(profileName) {
  // Apply chosen profile (provider+api_base+api_key_env+default_model) to ALL 8 nodes.
  // Preserves temperature/max_tokens per node so role personalities stay calibrated.
  const profile = pillState.profiles[profileName];
  if (!profile) return;
  try {
    const r = await fetch('/api/nodes/config');
    if (!r.ok) return;
    const data = await r.json();
    const nodes = {};
    Object.entries(data.nodes).forEach(([role, spec]) => {
      if (!spec) return;
      nodes[role] = {
        provider: profile.provider,
        api_base: profile.api_base,
        api_key_env: profile.api_key_env,
        model: profile.default_model || spec.model,
        temperature: spec.temperature,
        max_tokens: spec.max_tokens,
      };
    });
    const payload = {
      nodes,
      api_profiles: data.api_profiles || {},
      failover: data.failover || {},
      per_node_fallback: rebuildPerNodeFallback(data.nodes),
    };
    const sr = await fetch('/api/nodes/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!sr.ok) {
      const body = await sr.json().catch(() => ({}));
      alert('切換失敗: ' + (body.detail || sr.status));
      return;
    }
    pillState.primary = profileName;
    updatePillView();
    refreshPill();
  } catch (e) {
    alert('Network error: ' + e.message);
  }
}

// ═══════════════════════════════════════════════════════════════
// v8.2: Stress test modal
// ═══════════════════════════════════════════════════════════════

function openStressModal() {
  const modal = document.getElementById('stress-modal');
  if (!modal) return;
  modal.classList.remove('hidden');
  document.getElementById('stress-results').innerHTML = '';
  syncStressTargetUI();
}

function syncStressTargetUI() {
  const target = document.getElementById('stress-target')?.value || 'llm_node';
  document.getElementById('stress-controls-llm')?.classList.toggle('hidden', target !== 'llm_node');
  document.getElementById('stress-controls-pipeline')?.classList.toggle('hidden', target !== 'pipeline');
  document.getElementById('stress-controls-skill')?.classList.toggle('hidden', target !== 'skill_tool');
  if (target === 'skill_tool') populateSkillDropdown();
}

async function populateSkillDropdown() {
  const sel = document.getElementById('stress-skill-name');
  if (!sel || sel.dataset.populated) return;
  try {
    const r = await fetch('/api/skills/list');
    if (!r.ok) return;
    const data = await r.json();
    const enabled = (data.skills || []).filter(s => s.enabled);
    if (!enabled.length) return;
    sel.innerHTML = enabled.map(s => {
      const tag = s.action_type === 'tool_call' ? '🔧' : '📝';
      return `<option value="${escapeHtml(s.name)}" ${s.name==='stress_echo'?'selected':''}>${tag} ${escapeHtml(s.name)} — ${escapeHtml((s.description||'').slice(0,40))}</option>`;
    }).join('');
    sel.dataset.populated = '1';
  } catch (_e) { /* fall back to default stress_echo option */ }
}

let stressAbortController = null;

async function runStressTest() {
  const target = document.getElementById('stress-target')?.value || 'llm_node';
  if (target === 'pipeline') {
    await runStreamStressBrowser({
      buildInput: (i) => {
        const prompt = (document.getElementById('stress-pipeline-prompt').value || 'ping').trim();
        return `/echo ${prompt} #${i}`;
      },
      n: parseInt(document.getElementById('stress-pipeline-n').value, 10) || 20,
      concurrency: parseInt(document.getElementById('stress-pipeline-concurrency').value, 10) || 10,
      label: 'pipeline (echo)',
    });
  } else if (target === 'skill_tool') {
    await runStreamStressBrowser({
      buildInput: (i) => {
        const name = document.getElementById('stress-skill-name').value || 'stress_echo';
        const input = (document.getElementById('stress-skill-input').value || 'ping').trim();
        return `/skill ${name} ${input} #${i}`;
      },
      n: parseInt(document.getElementById('stress-skill-n').value, 10) || 20,
      concurrency: parseInt(document.getElementById('stress-skill-concurrency').value, 10) || 10,
      label: 'skill+tool dispatch',
    });
  } else {
    await runLlmNodeStressBackend();
  }
}

async function runLlmNodeStressBackend() {
  const role = document.getElementById('stress-role').value;
  const mode = document.getElementById('stress-mode').value;
  const n = parseInt(document.getElementById('stress-n').value, 10) || 5;
  const concurrency = parseInt(document.getElementById('stress-concurrency').value, 10) || 3;
  // v8.5 — optional cooldown override (default off; override default 5s)
  const overrideEnabled = document.getElementById('stress-cooldown-override-enable')?.checked;
  const cooldownOverride = overrideEnabled
    ? Math.max(0, Math.min(600, parseFloat(document.getElementById('stress-cooldown-override-value').value) || 5))
    : null;
  const out = document.getElementById('stress-results');
  const cdNote = cooldownOverride !== null ? `, cooldown=${cooldownOverride}s` : '';
  out.innerHTML = `<div style="color:var(--text-dim)">⋯ Backend stress on ${role} (${mode}, n=${n}, concurrency=${concurrency}${cdNote})...</div>`;
  const btn = document.getElementById('stress-go');
  btn.disabled = true;
  try {
    const body = { role, mode, n, concurrency, prompt: 'ping' };
    if (cooldownOverride !== null) body.cooldown_override_seconds = cooldownOverride;
    const r = await fetch('/api/stress/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await r.json();
    if (!r.ok) {
      out.innerHTML = `<div style="color:#e57373">Stress failed: ${escapeHtml(data.detail || JSON.stringify(data))}</div>`;
      return;
    }
    renderStressResults(data);
    refreshPill();
  } catch (e) {
    out.innerHTML = `<div style="color:#e57373">Network: ${escapeHtml(e.message)}</div>`;
  } finally {
    btn.disabled = false;
  }
}

// ═══════════════════════════════════════════════════════════════
// Browser-driven pipeline stress runner
// Fires N concurrent fetch() POST /api/stream calls with /echo input.
// Server short-circuits at Pre-Stage A meta-command (no LLM call), so this
// exercises FastAPI / SSE / pipeline counter under load without burning quota.
// ═══════════════════════════════════════════════════════════════

async function runStreamStressBrowser({ buildInput, n, concurrency, label }) {
  n = Math.min(200, Math.max(1, n || 20));
  concurrency = Math.min(50, Math.max(1, concurrency || 10));
  label = label || 'browser';
  const out = document.getElementById('stress-results');
  const goBtn = document.getElementById('stress-go');
  const abortBtn = document.getElementById('stress-abort');

  stressAbortController = new AbortController();
  goBtn.disabled = true;
  abortBtn.classList.remove('hidden');
  abortBtn.onclick = () => stressAbortController?.abort();

  const results = new Array(n).fill(null);
  const tStart = performance.now();
  let inflight = 0;

  function renderLive() {
    const done = results.filter(r => r && r.complete).length;
    const ok = results.filter(r => r && r.ok).length;
    const fail = results.filter(r => r && r.complete && !r.ok).length;
    const elapsed = ((performance.now() - tStart) / 1000).toFixed(1);
    out.innerHTML = `
      <div class="stress-summary">
        <span class="stat-pill">target: ${escapeHtml(label)}</span>
        <span class="stat-pill">progress: ${done}/${n}</span>
        <span class="stat-pill">in-flight: ${inflight}</span>
        <span class="stat-pill" style="color:#6fcf6f">✓ ${ok}</span>
        <span class="stat-pill" style="color:#e57373">✗ ${fail}</span>
        <span class="stat-pill">elapsed: ${elapsed}s</span>
      </div>
      <div class="stress-attempt-list" id="stress-pipeline-live"></div>
    `;
    const live = document.getElementById('stress-pipeline-live');
    if (live) {
      live.innerHTML = results.slice(0, 50).map((r, i) => {
        if (!r) return `<div class="stress-attempt-line skipped">#${i} pending</div>`;
        if (!r.complete) return `<div class="stress-attempt-line skipped">#${i} ⋯ in-flight (${r.ttfb_ms ?? '—'}ms TTFB)</div>`;
        const cls = r.ok ? 'ok' : 'failed';
        const mark = r.ok ? '✓' : '✗';
        return `<div class="stress-attempt-line ${cls}">#${i} ${mark} TTFB=${r.ttfb_ms ?? '—'}ms  total=${r.total_ms ?? '—'}ms  events=${r.event_count ?? 0}${r.error ? '  err=' + escapeHtml(r.error.slice(0,60)) : ''}</div>`;
      }).join('') + (n > 50 ? `<div class="stress-attempt-line skipped">... (${n - 50} more)</div>` : '');
    }
  }

  const renderTimer = setInterval(renderLive, 200);

  // Worker-pool pattern — `concurrency` parallel workers pulling from a counter
  let nextIdx = 0;
  async function worker() {
    while (true) {
      const i = nextIdx++;
      if (i >= n) return;
      if (stressAbortController.signal.aborted) {
        results[i] = { complete: true, ok: false, error: 'aborted' };
        continue;
      }
      inflight++;
      results[i] = { complete: false };
      const slot = results[i];
      const t0 = performance.now();
      try {
        const r = await fetch('/api/stream', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            input: buildInput(i),
            refs: [],
            override_mode: null,
            save: false,
            label: '',
            auto_tools: false,
          }),
          signal: stressAbortController.signal,
        });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        // Stream SSE and look for `event: done` or `event: error`
        const reader = r.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let eventCount = 0;
        let sawDone = false;
        let sawError = null;
        let firstByteAt = null;
        while (true) {
          const { done, value } = await reader.read();
          if (firstByteAt === null) {
            firstByteAt = performance.now();
            slot.ttfb_ms = Math.round(firstByteAt - t0);
          }
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          // SSE events split on blank line
          let idx;
          while ((idx = buffer.indexOf('\n\n')) !== -1) {
            const block = buffer.slice(0, idx);
            buffer = buffer.slice(idx + 2);
            eventCount++;
            const evLine = block.split('\n').find(l => l.startsWith('event:'));
            if (evLine) {
              const ev = evLine.slice(6).trim();
              if (ev === 'done') sawDone = true;
              if (ev === 'error') {
                const dataLine = block.split('\n').find(l => l.startsWith('data:'));
                sawError = dataLine ? dataLine.slice(5).trim() : 'unknown';
              }
            }
          }
          if (sawDone || sawError) break;
        }
        try { reader.cancel(); } catch (_) {}
        slot.event_count = eventCount;
        slot.total_ms = Math.round(performance.now() - t0);
        slot.complete = true;
        slot.ok = sawDone && !sawError;
        if (sawError) slot.error = sawError;
      } catch (e) {
        slot.complete = true;
        slot.ok = false;
        slot.error = (e && e.message) || String(e);
        slot.total_ms = Math.round(performance.now() - t0);
      } finally {
        inflight--;
      }
    }
  }

  const workers = Array.from({ length: concurrency }, () => worker());
  try {
    await Promise.all(workers);
  } finally {
    clearInterval(renderTimer);
    renderLive();   // final render
    goBtn.disabled = false;
    abortBtn.classList.add('hidden');
    stressAbortController = null;
    renderPipelineFinalSummary(results, performance.now() - tStart, label);
  }
}

function renderPipelineFinalSummary(results, totalMs, label) {
  const out = document.getElementById('stress-results');
  if (!out) return;
  const complete = results.filter(r => r && r.complete);
  const ok = complete.filter(r => r.ok);
  const fail = complete.filter(r => !r.ok);
  if (!complete.length) return;
  // Percentiles
  const ttfbs = ok.map(r => r.ttfb_ms).filter(x => x !== undefined).sort((a,b)=>a-b);
  const totals = ok.map(r => r.total_ms).filter(x => x !== undefined).sort((a,b)=>a-b);
  const pct = (arr, p) => arr.length ? arr[Math.min(arr.length - 1, Math.floor(arr.length * p))] : '—';
  // Error histogram
  const errHist = {};
  fail.forEach(r => {
    const key = (r.error || 'unknown').split(':')[0].slice(0, 40);
    errHist[key] = (errHist[key] || 0) + 1;
  });
  const errRows = Object.entries(errHist)
    .sort((a,b) => b[1] - a[1])
    .map(([k, v]) => `<tr><td>${escapeHtml(k)}</td><td>${v}</td></tr>`)
    .join('') || '<tr><td colspan="2" style="color:var(--text-dim)">no errors</td></tr>';
  const summaryHTML = `
    <div class="stress-summary">
      <span class="stat-pill">target: ${escapeHtml(label || 'browser')}</span>
      <span class="stat-pill">n: ${results.length}</span>
      <span class="stat-pill" style="color:#6fcf6f">✓ ${ok.length}</span>
      <span class="stat-pill" style="color:#e57373">✗ ${fail.length}</span>
      <span class="stat-pill">wall: ${(totalMs/1000).toFixed(2)}s</span>
      <span class="stat-pill">throughput: ${(complete.length / (totalMs/1000)).toFixed(1)} req/s</span>
    </div>
    <table class="stress-by-profile">
      <thead><tr><th>Metric</th><th>p50</th><th>p90</th><th>p99</th><th>max</th></tr></thead>
      <tbody>
        <tr><td>TTFB (ms)</td><td>${pct(ttfbs,0.5)}</td><td>${pct(ttfbs,0.9)}</td><td>${pct(ttfbs,0.99)}</td><td>${ttfbs.at(-1) ?? '—'}</td></tr>
        <tr><td>Total  (ms)</td><td>${pct(totals,0.5)}</td><td>${pct(totals,0.9)}</td><td>${pct(totals,0.99)}</td><td>${totals.at(-1) ?? '—'}</td></tr>
      </tbody>
    </table>
    ${fail.length ? `<table class="stress-by-profile"><thead><tr><th>Error class</th><th>Count</th></tr></thead><tbody>${errRows}</tbody></table>` : ''}
  `;
  // Preserve the live attempt list, prepend the summary
  const live = document.getElementById('stress-pipeline-live');
  const liveHTML = live ? live.outerHTML : '';
  out.innerHTML = summaryHTML + liveHTML;
}

function renderStressResults(data) {
  const out = document.getElementById('stress-results');
  if (!out) return;
  const summary = `
    <div class="stress-summary">
      <span class="stat-pill">role: ${escapeHtml(data.role)}</span>
      <span class="stat-pill">mode: ${escapeHtml(data.mode)}</span>
      <span class="stat-pill">n: ${data.n}</span>
      <span class="stat-pill" style="color:#6fcf6f">✓ ${data.success_count}</span>
      <span class="stat-pill" style="color:#e57373">✗ ${data.fail_count}</span>
      <span class="stat-pill">total: ${data.total_ms} ms</span>
    </div>
  `;
  const profileRows = Object.entries(data.by_profile || {}).map(([prof, s]) => {
    const triggers = Object.entries(s.triggers || {}).map(([t,c]) => `${t}=${c}`).join(', ') || '—';
    return `<tr><td>${escapeHtml(prof)}</td><td style="color:#6fcf6f">${s.ok}</td><td style="color:#e57373">${s.fail}</td><td>${escapeHtml(triggers)}</td></tr>`;
  }).join('') || '<tr><td colspan="4" style="color:var(--text-dim)">no attempts recorded</td></tr>';
  const byProfileTable = `
    <table class="stress-by-profile">
      <thead><tr><th>Profile</th><th>OK</th><th>Fail</th><th>Triggers</th></tr></thead>
      <tbody>${profileRows}</tbody>
    </table>
  `;
  const attemptLines = (data.results || []).slice(0, 30).map(r => {
    const trail = (r.attempts || []).map(a => {
      const cls = a.trigger === 'ok' ? 'ok' : (a.trigger === 'cooling_skip' || a.trigger === 'no_key') ? 'skipped' : 'failed';
      const tag = a.is_primary ? '*' : '';
      return `<span class="stress-attempt-line ${cls}" style="display:inline">[${escapeHtml(a.profile)}${tag} ${escapeHtml(a.trigger)}]</span>`;
    }).join(' → ');
    return `<div class="stress-attempt-line ${r.ok ? 'ok' : 'failed'}">#${r.i} ${r.elapsed_ms}ms ${r.ok ? '✓' : '✗'} ${trail}${r.error ? ' err=' + escapeHtml(r.error.slice(0,80)) : ''}</div>`;
  }).join('');
  out.innerHTML = summary + byProfileTable + `<div class="stress-attempt-list">${attemptLines}</div>`;
}

// Wire the "+ profile" button once DOM is ready (also re-wired on modal re-open).
document.addEventListener('DOMContentLoaded', wireAddProfileButton);

// ═══════════ v8.15 MS-2 — Source Registry CRUD UI ═══════════

let __sourceRegistryWired = false;

function initSourceRegistryUI() {
  if (__sourceRegistryWired) return;
  __sourceRegistryWired = true;
  const addBtn   = document.getElementById('sr-add-btn');
  const importBtn= document.getElementById('sr-import-btn');
  const exportBtn= document.getElementById('sr-export-btn');
  const resetBtn = document.getElementById('sr-reset-btn');
  const importFile = document.getElementById('sr-import-file');
  const filter   = document.getElementById('sr-filter');
  if (addBtn) addBtn.onclick = handleSourceRegistryAdd;
  if (exportBtn) exportBtn.onclick = handleSourceRegistryExport;
  if (importBtn) importBtn.onclick = () => importFile && importFile.click();
  if (importFile) importFile.onchange = handleSourceRegistryImport;
  if (resetBtn) resetBtn.onclick = handleSourceRegistryReset;
  if (filter) filter.oninput = () => renderSourceRegistry(filter.value.trim().toLowerCase());
}

function _srStatus(msg, cls) {
  const el = document.getElementById('sr-status');
  if (!el) return;
  el.textContent = msg || '';
  el.classList.remove('ok', 'err');
  if (cls) el.classList.add(cls);
}

async function renderSourceRegistry(filterStr) {
  const tbody = document.querySelector('#sr-table tbody');
  if (!tbody) return;
  try {
    const r = await fetch('/api/source_registry');
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    const mappings = data.mappings || {};
    const filt = (filterStr || '').toLowerCase();
    const rows = Object.entries(mappings)
      .filter(([d]) => !filt || d.includes(filt))
      .sort((a, b) => a[0].localeCompare(b[0]));
    tbody.innerHTML = rows.map(([domain, m]) => {
      const rating = m.rating || 'UNVERIFIED';
      const coord = m.coordinate || '';
      const origin = m.origin || 'seed';
      const canDelete = origin === 'overlay';
      const delBtn = canDelete
        ? '<button type="button" data-act="delete">Delete</button>'
        : '';
      return '<tr data-domain="' + escapeAttr(domain) + '">'
           + '<td>' + escapeHtml(domain) + '</td>'
           + '<td>' + escapeHtml(coord) + '</td>'
           + '<td class="sr-rating-' + escapeAttr(rating) + '">' + escapeHtml(rating) + '</td>'
           + '<td class="sr-origin-' + escapeAttr(origin) + '">' + escapeHtml(origin) + '</td>'
           + '<td class="sr-actions">'
           + '<button type="button" data-act="edit">Edit</button>'
           + delBtn
           + '</td></tr>';
    }).join('');
    tbody.querySelectorAll('button[data-act]').forEach(btn => {
      btn.onclick = (e) => {
        const tr = e.target.closest('tr');
        const domain = tr && tr.getAttribute('data-domain');
        if (!domain) return;
        if (btn.dataset.act === 'edit') handleSourceRegistryEdit(domain);
        else if (btn.dataset.act === 'delete') handleSourceRegistryDelete(domain);
      };
    });
    _srStatus(rows.length + ' mapping(s)' + (filt ? ' (filtered)' : ''), '');
  } catch (e) {
    _srStatus('load failed: ' + e.message, 'err');
  }
}

const SR_VALID_RATINGS = ['VERIFIED', 'PROBABLE', 'INFERRED', 'UNVERIFIED'];

async function handleSourceRegistryAdd() {
  const domain = (prompt('Domain (e.g. mywebsite.com):') || '').trim();
  if (!domain) return;
  const coordinate = (prompt('Coordinate description (e.g. "Independent journalism"):') || '').trim();
  if (!coordinate) return;
  const rating = (prompt('Rating: VERIFIED / PROBABLE / INFERRED / UNVERIFIED') || '').trim().toUpperCase();
  if (SR_VALID_RATINGS.indexOf(rating) < 0) {
    _srStatus('invalid rating — must be VERIFIED / PROBABLE / INFERRED / UNVERIFIED', 'err');
    return;
  }
  try {
    const r = await fetch('/api/source_registry', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({domain, coordinate, rating}),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || ('HTTP ' + r.status));
    }
    _srStatus('added ' + domain, 'ok');
    renderSourceRegistry();
  } catch (e) {
    _srStatus('add failed: ' + e.message, 'err');
  }
}

async function handleSourceRegistryEdit(domain) {
  const r = await fetch('/api/source_registry');
  const data = await r.json();
  const cur = (data.mappings || {})[domain] || {};
  const coordinate = prompt('Coordinate for ' + domain + ':', cur.coordinate || '');
  if (coordinate === null) return;
  const rating = prompt('Rating (VERIFIED / PROBABLE / INFERRED / UNVERIFIED):', cur.rating || 'UNVERIFIED');
  if (rating === null) return;
  const cleanRating = rating.trim().toUpperCase();
  if (SR_VALID_RATINGS.indexOf(cleanRating) < 0) {
    _srStatus('invalid rating', 'err');
    return;
  }
  try {
    const rr = await fetch('/api/source_registry/' + encodeURIComponent(domain), {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({coordinate: coordinate.trim(), rating: cleanRating}),
    });
    if (!rr.ok) {
      const err = await rr.json().catch(() => ({}));
      throw new Error(err.detail || ('HTTP ' + rr.status));
    }
    _srStatus('updated ' + domain, 'ok');
    renderSourceRegistry();
  } catch (e) {
    _srStatus('update failed: ' + e.message, 'err');
  }
}

async function handleSourceRegistryDelete(domain) {
  if (!confirm('Delete overlay entry for ' + domain + '? (Seed mapping, if any, will still apply.)')) return;
  try {
    const r = await fetch('/api/source_registry/' + encodeURIComponent(domain), {method: 'DELETE'});
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || ('HTTP ' + r.status));
    }
    _srStatus('deleted overlay for ' + domain, 'ok');
    renderSourceRegistry();
  } catch (e) {
    _srStatus('delete failed: ' + e.message, 'err');
  }
}

async function handleSourceRegistryExport() {
  try {
    const r = await fetch('/api/source_registry/export');
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    const blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'source_registry_overlay_' + Date.now() + '.json';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    _srStatus('exported ' + data.domain_count + ' overlay mapping(s)', 'ok');
  } catch (e) {
    _srStatus('export failed: ' + e.message, 'err');
  }
}

async function handleSourceRegistryImport(ev) {
  const file = ev.target.files && ev.target.files[0];
  ev.target.value = '';
  if (!file) return;
  try {
    const text = await file.text();
    const payload = JSON.parse(text);
    const replace = confirm('Replace existing overlay? OK = replace, Cancel = merge.');
    const r = await fetch('/api/source_registry/import', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(Object.assign({}, payload, {replace})),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || ('HTTP ' + r.status));
    }
    const result = await r.json();
    _srStatus('imported ' + result.accepted + ' accepted / ' + result.rejected + ' rejected (' + (replace ? 'replace' : 'merge') + ')', 'ok');
    renderSourceRegistry();
  } catch (e) {
    _srStatus('import failed: ' + e.message, 'err');
  }
}

async function handleSourceRegistryReset() {
  if (!confirm('Clear ALL overlay entries? (Seed defaults stay intact.)')) return;
  try {
    const r = await fetch('/api/source_registry/reset', {method: 'POST'});
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    _srStatus('reset ok · remaining overlay count: ' + data.remaining_count, 'ok');
    renderSourceRegistry();
  } catch (e) {
    _srStatus('reset failed: ' + e.message, 'err');
  }
}

// ═══════════ v8.15 MS-1 — Search engines availability grid ═══════════

async function renderSearchEnginesGrid() {
  const grid = document.getElementById('search-engines-grid');
  if (!grid) return;
  try {
    const r = await fetch('/api/search_engines');
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    const engines = data.engines || [];
    const primary = (data.current && data.current.primary) || '';
    grid.innerHTML = engines.map(e => {
      const cls = (e.available ? 'available' : 'unavailable') + (e.name === primary ? ' primary' : '');
      const status = e.available ? '✓ ready' : (e.reason || 'unavailable');
      return '<div class="search-engine-card ' + cls + '">'
           + '<div class="se-name">' + escapeHtml(e.name) + '</div>'
           + '<div class="se-status">' + escapeHtml(status) + '</div>'
           + '</div>';
    }).join('');
  } catch (e) {
    grid.innerHTML = '<div class="se-status">load failed: ' + escapeHtml(e.message) + '</div>';
  }
}

function escapeAttr(s) {
  return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// ═══════════ v8.25 UX-Collapse — Trinity 4-panel → single bubble ═══════════

function _getBubbleElems(_mid) {
  // Multi-mode aware accessor (uses existing getModeElement when available)
  const lookup = (typeof getModeElement === 'function')
    ? (baseId) => getModeElement(_mid || '_default', baseId)
    : (baseId) => document.getElementById(baseId);
  return {
    bubble:    lookup('council-answer-bubble'),
    chips:     lookup('council-answer-chips'),
    body:      lookup('council-answer-body'),
    toggle:    lookup('trinity-breakdown-toggle'),
    grid:      lookup('nodes-grid'),
    council:   lookup('output-council'),
    // v8.26 UX-Collapse-2 — Stage 1 + Stage 2 sections also collapse on done
    stage1:    lookup('stage1-section'),
    stage2:    lookup('stage2-section'),
  };
}

// v8.26 UX-Collapse-2 — toggle label (full pipeline, not just Trinity)
const _BREAKDOWN_LABEL_COLLAPSED = '▸ 內部質控 / 完整流程 (Stage 1-4)';
const _BREAKDOWN_LABEL_EXPANDED  = '▼ 內部質控 / 完整流程 (Stage 1-4)';

function _collapseTrinityIntoBubble(_mid) {
  // v8.27 BUGFIX — defensive rewrite. Each step in its own try/catch so a
  // failure in one (e.g. cloneNode on weird council content during Spirit
  // rescan) cannot leave stages un-collapsed. After best-effort steps, we
  // always run a final belt-and-suspenders sweep that *forces* collapse via
  // querySelectorAll across BOTH the default DOM and any multi-mode clones.
  let e;
  try { e = _getBubbleElems(_mid); } catch (_) { e = null; }
  if (e && e.bubble) {
    // 1. Copy council fusion text — wrapped to survive cloneNode failures
    try {
      if (e.council && e.body) {
        const clone = e.council.cloneNode(true);
        clone.querySelectorAll('.placeholder, .alignment-chip').forEach(el => el.remove());
        e.body.innerHTML = clone.innerHTML;
      }
    } catch (err) { console.warn('collapse: body copy failed', err); }

    // 2. Verdict / Module N chips
    try {
      if (e.chips) {
        e.chips.innerHTML = '';
        const sel = '.alignment-chip, .verdict-chip, .father-paused-chip, .spirit-interrupt-chip, .son-veto-chip, .inference-usage-chip';
        const verdictChips = e.council ? e.council.querySelectorAll(sel) : [];
        verdictChips.forEach(c => e.chips.appendChild(c.cloneNode(true)));
      }
    } catch (err) { console.warn('collapse: chips copy failed', err); }

    // 3. Show the bubble
    try { e.bubble.classList.remove('hidden'); }
    catch (err) { console.warn('collapse: bubble show failed', err); }

    // 4. Toggle button — dev mode → start expanded; default → collapsed
    try {
      const devOn = typeof getDeveloperMode === 'function' ? getDeveloperMode() : false;
      _setPipelineExpanded(e, devOn);
    } catch (err) { console.warn('collapse: toggle init failed', err); }

    // 5. Wire toggle once (idempotent)
    try {
      if (e.toggle && !e.toggle.dataset.wired) {
        e.toggle.dataset.wired = '1';
        e.toggle.addEventListener('click', () => {
          const ne = _getBubbleElems(_mid);
          const wasCollapsed = (ne.grid && ne.grid.classList.contains('trinity-collapsed'))
            || (ne.stage1 && ne.stage1.classList.contains('trinity-collapsed'))
            || (ne.stage2 && ne.stage2.classList.contains('trinity-collapsed'));
          _setPipelineExpanded(ne, wasCollapsed);
        });
      }
    } catch (err) { console.warn('collapse: toggle wire failed', err); }
  }

  // 6. ★ Belt-and-suspenders: force-collapse ALL pipeline stage elements,
  // both the default-DOM ids and every multi-mode-stack clone. This is the
  // hard guarantee — even if step 3 above never ran, this will still hide
  // Stage 1 / Stage 2 / Trinity grid.
  //
  // Skipped only when dev-mode is ON (caller wants to see everything).
  const devOn = typeof getDeveloperMode === 'function' && getDeveloperMode();
  if (!devOn) {
    const sel = (
      '#nodes-grid, [data-base-id="nodes-grid"], ' +
      '#stage1-section, [data-base-id="stage1-section"], ' +
      '#stage2-section, [data-base-id="stage2-section"]'
    );
    document.querySelectorAll(sel).forEach(el => {
      try { el.classList.add('trinity-collapsed'); } catch (_) {}
    });
  }
}

function _setPipelineExpanded(e, expanded) {
  // expanded=true → show all stages; expanded=false → collapse all
  [e.grid, e.stage1, e.stage2].forEach(el => {
    if (!el) return;
    if (expanded) el.classList.remove('trinity-collapsed');
    else el.classList.add('trinity-collapsed');
  });
  if (e.toggle) {
    e.toggle.setAttribute('aria-expanded', String(expanded));
    e.toggle.textContent = expanded ? _BREAKDOWN_LABEL_EXPANDED : _BREAKDOWN_LABEL_COLLAPSED;
  }
}

function _resetCouncilBubble() {
  // Called at runTrinity start. Resets answer bubble, shows streaming status bar.
  // Detailed pipeline panels stay collapsed in normal mode — chips show progress.
  const allBubbles = document.querySelectorAll('[data-base-id="council-answer-bubble"], #council-answer-bubble');
  allBubbles.forEach(b => {
    b.classList.add('hidden');
    const body = b.querySelector('.council-answer-body');
    if (body) body.innerHTML = '';
    const chips = b.querySelector('.council-answer-chips');
    if (chips) chips.innerHTML = '';
  });
  const devOn = typeof getDeveloperMode === 'function' && getDeveloperMode();
  const pipelineCollapsibles = document.querySelectorAll(
    '[data-base-id="nodes-grid"], #nodes-grid, ' +
    '[data-base-id="stage1-section"], #stage1-section, ' +
    '[data-base-id="stage2-section"], #stage2-section'
  );
  pipelineCollapsibles.forEach(el => {
    if (devOn) el.classList.remove('trinity-collapsed');
    else el.classList.add('trinity-collapsed');
  });
  // Hide trinity-toggle-row (standalone grid toggle)
  const toggleRow = document.getElementById('trinity-toggle-row');
  if (toggleRow) toggleRow.classList.remove('visible');
  // Show streaming status bar with waiting chips
  _initTrinityStatusBar();
}

function _initTrinityStatusBar() {
  const bar = document.getElementById('trinity-status-bar');
  if (!bar) return;
  bar.innerHTML = '';
  bar.classList.add('trinity-running');
  const roles = [
    { role: 'father',  icon: '⊕', label: '聖父' },
    { role: 'son',     icon: '○', label: '聖子' },
    { role: 'spirit',  icon: '⟁', label: '聖靈' },
    { role: 'council', icon: '⟴', label: '會議' },
  ];
  roles.forEach(({ role, icon, label }) => {
    const chip = document.createElement('span');
    chip.className = 'node-status-chip';
    chip.dataset.role = role;
    chip.id = `status-chip-${role}`;
    chip.dataset.label = `${icon} ${label}`;
    chip.innerHTML = `<span class="chip-spinner"></span>${icon} ${label}`;
    bar.appendChild(chip);
  });
}

function _stopTrinityStatusBar() {
  const bar = document.getElementById('trinity-status-bar');
  if (!bar) return;
  bar.classList.remove('trinity-running');
  bar.innerHTML = '';
}

// ═══════════ Boot ═══════════
init();

// ═══════════ Self-Upgrade Panel ═══════════
(function initSelfUpgrade() {
  const auditBtn  = document.getElementById('sup-audit-btn');
  const learnBtn  = document.getElementById('sup-learn-btn');
  const loopBtn   = document.getElementById('sup-loop-btn');
  const pauseBtn  = document.getElementById('sup-pause-btn');
  const relaySelect = document.getElementById('sup-relay-select');
  const statusEl  = document.getElementById('sup-status');
  const resultEl  = document.getElementById('sup-result');
  const resultTitle = document.getElementById('sup-result-title');
  const resultBody  = document.getElementById('sup-result-body');
  const closeBtn  = document.getElementById('sup-result-close');
  const installActions = document.getElementById('sup-install-actions');
  const sendToInputBtn = document.getElementById('sup-send-to-input');
  const logStrip  = document.getElementById('sup-log-strip');
  const runtimeStrip = document.getElementById('sup-runtime-strip');
  const planList = document.getElementById('sup-plan-list');
  const planDetail = document.getElementById('sup-plan-detail');
  const planRefresh = document.getElementById('sup-plan-refresh');
  const gateCheckBtn = document.getElementById('sup-gate-check');
  const stabilityCheckBtn = document.getElementById('sup-stability-check');
  const promptCheckBtn = document.getElementById('sup-prompt-check');
  const reportBtn = document.getElementById('sup-report-btn');
  const stabilityStrip = document.getElementById('sup-stability-strip');
  const stabilityMain = document.getElementById('sup-stability-main');
  const stabilityMeta = document.getElementById('sup-stability-meta');
  const stabilityPath = document.getElementById('sup-stability-path');
  const promptStrip = document.getElementById('sup-prompt-strip');
  const promptMain = document.getElementById('sup-prompt-main');
  const promptMeta = document.getElementById('sup-prompt-meta');
  const promptPath = document.getElementById('sup-prompt-path');

  if (!auditBtn) return;
  let loopPollTimer = null;
  let latestRuntimeStatus = null;
  let latestLoopState = null;
  let latestSelectedPlanId = null;

  function selectedRelayLabel() {
    if (!relaySelect) return '--';
    const opt = relaySelect.options[relaySelect.selectedIndex];
    return (opt ? opt.textContent : relaySelect.value || '--').trim();
  }

  function shortStamp(value) {
    if (!value) return '--';
    const text = String(value);
    const match = text.match(/T(\d\d:\d\d:\d\d)/);
    return match ? match[1] : text.slice(0, 19);
  }

  function upgradeOutcomeLabel(status) {
    return {
      installed: '已安裝',
      failed: '未安裝',
      review_required: '需要人工確認',
      waiting_claude: '等待 Claude',
      waiting_relay: '等待 Relay',
      installing: '安裝中',
    }[status] || status || '完成';
  }

  function renderRuntimeStatus(data = latestRuntimeStatus, loopState = latestLoopState) {
    if (!runtimeStrip) return;
    latestRuntimeStatus = data || latestRuntimeStatus;
    latestLoopState = loopState || latestLoopState;
    const status = latestRuntimeStatus || {};
    const loop = latestLoopState || status.loop_state || {};
    const plan = status.latest_upgrade_plan || {};
    const code = status.code_version || {};
    const parts = [
      `Port ${status.port || status.configured_port || '--'}${status.non_default_port ? ' test' : ''}`,
      `Code ${shortStamp(code.latest_mtime)}`,
      `Relay ${selectedRelayLabel()}`,
      `Plan ${plan.plan_id ? `${plan.plan_id} ${plan.status || ''}` : '--'}`,
      `Health ${loop.last_health ? (loop.last_health.ok ? 'ok' : 'fail') : (loop.status || 'idle')}`,
    ];
    runtimeStrip.replaceChildren(...parts.map(text => {
      const span = document.createElement('span');
      span.title = text;
      span.textContent = text;
      return span;
    }));
  }

  async function loadRuntimeStatus(quiet = false) {
    try {
      const resp = await fetch('/api/runtime/status');
      const data = await resp.json();
      if (!resp.ok || !data.ok) throw new Error(data.detail || data.error || `HTTP ${resp.status}`);
      renderRuntimeStatus(data, data.loop_state);
    } catch (e) {
      if (!quiet && runtimeStrip) {
        runtimeStrip.textContent = `Runtime status unavailable: ${e.message}`;
      }
    }
  }

  function setLoading(loading, mode) {
    auditBtn.disabled = loading;
    learnBtn.disabled = loading;
    if (loopBtn) loopBtn.disabled = loading;
    if (gateCheckBtn) gateCheckBtn.disabled = loading;
    if (stabilityCheckBtn) stabilityCheckBtn.disabled = loading;
    if (promptCheckBtn) promptCheckBtn.disabled = loading;
    if (reportBtn) reportBtn.disabled = loading;
    if (pauseBtn) pauseBtn.disabled = true;
    if (loading) {
      statusEl.classList.remove('hidden');
      const relayLabel = selectedRelayLabel();
      const label = {
        audit: `掃描系統並等待 ${relayLabel} relay 中...`,
        gate: '檢查升級硬閘中⋯',
        stability: '執行穩定檢查中⋯',
        prompt: '執行 prompt regression 檢查中⋯',
        report: '生成升級報告中⋯',
        learn: `上網學習並等待 ${relayLabel} relay 中...`,
      }[mode] || '處理中⋯';
      statusEl.innerHTML = `<span class="spinner"></span> ${label}`;
      resultEl.classList.add('hidden');
    } else {
      statusEl.classList.add('hidden');
    }
  }

  function renderLoopState(state) {
    if (!state) return;
    latestLoopState = state;
    renderRuntimeStatus(latestRuntimeStatus, state);
    if (state.last_plan_id && state.last_plan_id !== latestSelectedPlanId) {
      loadUpgradePlans(state.last_plan_id);
    }
    const running = !!state.running;
    const pauseRequested = !!state.pause_requested || state.status === 'pause_requested';
    auditBtn.disabled = running || pauseRequested;
    learnBtn.disabled = running || pauseRequested;
    if (loopBtn) loopBtn.disabled = running || pauseRequested;
    if (gateCheckBtn) gateCheckBtn.disabled = running || pauseRequested;
    if (stabilityCheckBtn) stabilityCheckBtn.disabled = running || pauseRequested;
    if (promptCheckBtn) promptCheckBtn.disabled = running || pauseRequested;
    if (reportBtn) reportBtn.disabled = running || pauseRequested;
    if (pauseBtn) pauseBtn.disabled = !(running || pauseRequested);

    if (running || pauseRequested || state.status === 'paused' || state.status === 'error' || state.status === 'health_check' || state.status === 'health_failed' || state.status === 'review_required') {
      statusEl.classList.remove('hidden');
      const mode = state.current_mode ? ` · ${state.current_mode}` : '';
      const iter = state.iteration ? ` · #${state.iteration}` : '';
      const err = state.last_error ? ` · ${state.last_error}` : '';
      const label = {
        starting: '準備循環自我升級',
        running: '循環自我升級執行中',
        health_check: '檢查今輪升級是否合理',
        sleeping: '等待下一輪',
        pause_requested: '已要求暫停，完成當前工作後停低',
        paused: '已暫停',
        error: '循環遇到錯誤',
        health_failed: '升級健康檢查未通過，已停止循環',
        idle: '未啟動',
      }[state.status] || state.status;
      statusEl.innerHTML = `${running && !pauseRequested ? '<span class="spinner"></span> ' : ''}${label}${mode}${iter}${err}`;
    } else if (state.status === 'idle') {
      statusEl.classList.add('hidden');
    }

    if (state.history && state.history.length && logStrip) {
      const latest = state.history.slice(-3).reverse();
      logStrip.textContent = '循環記錄：' + latest.map(e =>
        e.ok ? `${e.mode}:${e.status || 'done'}` : `${e.mode}:health_failed`
      ).join(' · ');
      logStrip.classList.remove('hidden');
    }
  }

  async function loadLoopStatus(quiet = false) {
    try {
      const resp = await fetch('/api/upgrade/loop/status');
      const data = await resp.json();
      if (data && data.state) renderLoopState(data.state);
      const st = data.state || {};
      if ((st.running || st.pause_requested || st.status === 'pause_requested') && !loopPollTimer) {
        loopPollTimer = setInterval(() => loadLoopStatus(true), 4000);
      }
      if (!(st.running || st.pause_requested || st.status === 'pause_requested') && loopPollTimer) {
        clearInterval(loopPollTimer);
        loopPollTimer = null;
      }
    } catch (e) {
      if (!quiet) {
        statusEl.classList.remove('hidden');
        statusEl.innerHTML = `❌ 讀取循環狀態失敗：${e.message}`;
      }
    }
  }

  function showResult(title, text, mode) {
    resultTitle.textContent = title;
    resultBody.textContent = text;
    resultEl.classList.remove('hidden');
    installActions.classList.remove('hidden');
    // Scroll to result
    resultEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function yesNo(value) {
    if (value === true) return 'PASS';
    if (value === false) return 'FAIL';
    return 'SKIP';
  }

  function signedText(value) {
    const num = Number(value);
    if (!Number.isFinite(num)) return '--';
    return `${num >= 0 ? '+' : ''}${num.toFixed(3)}`;
  }

  function formatGatePreflight(data) {
    const knowledge = data.knowledge_audit || {};
    const benchmark = data.benchmark || {};
    const stability = data.stability_golden || {};
    const quick = data.quick_eval || {};
    const lines = [
      `overall: ${data.ok ? 'PASS' : 'FAIL'}`,
      `checked_at: ${data.checked_at || '--'}`,
      '',
      `knowledge_audit: ${yesNo(knowledge.passed)}`,
      `rag_present: ${knowledge.rag && knowledge.rag.present !== undefined ? knowledge.rag.present : '--'}`,
      `fatal_issues: ${Array.isArray(knowledge.fatal_issues) ? knowledge.fatal_issues.length : '--'}`,
      '',
      `coordinate_benchmark: ${yesNo(benchmark.passed)}`,
      `suite: ${benchmark.suite_id || '--'}`,
      `cases: ${benchmark.passed_count ?? '--'}/${benchmark.case_count ?? '--'}`,
    ];
    if (Array.isArray(benchmark.failed_cases) && benchmark.failed_cases.length) {
      lines.push(`failed_cases: ${benchmark.failed_cases.join(', ')}`);
    }
    lines.push(
      '',
      `stability_golden: ${yesNo(stability.passed)}`,
      `stability_cases: ${stability.passed_count ?? '--'}/${stability.case_count ?? '--'}`
    );
    if (Array.isArray(stability.failed_cases) && stability.failed_cases.length) {
      lines.push(`stability_failed_cases: ${stability.failed_cases.join(', ')}`);
    }
    lines.push(
      '',
      `quick_eval: ${yesNo(quick.passed)}`,
      `reason: ${quick.reason || (quick.skipped ? 'skipped' : '--')}`,
      `framing_iou_delta: ${signedText(quick.framing_iou_delta)}`,
      `chain_match_delta: ${signedText(quick.chain_match_delta)}`
    );
    return lines.join('\n');
  }

  function shortPathText(value) {
    if (!value) return '--';
    const parts = String(value).split(/[\\/]+/).filter(Boolean);
    return parts.slice(-3).join('/');
  }

  function renderStabilityStrip(report) {
    if (!stabilityStrip || !stabilityMain || !stabilityMeta || !stabilityPath) return;
    stabilityStrip.classList.remove('pass', 'fail', 'muted');
    if (!report) {
      stabilityStrip.classList.add('muted');
      stabilityMain.textContent = 'Stability --';
      stabilityMeta.textContent = '未檢查';
      stabilityPath.textContent = 'report --';
      return;
    }
    const checks = Array.isArray(report.checks) ? report.checks : [];
    const passedChecks = checks.filter(item => item && item.passed).length;
    const failedRequired = Number(report.failed_required_count || 0);
    stabilityStrip.classList.add(report.passed ? 'pass' : 'fail');
    stabilityMain.textContent = `Stability ${report.passed ? 'PASS' : 'FAIL'}`;
    stabilityMeta.textContent = `${passedChecks}/${report.check_count || checks.length || '--'} checks · required_fail=${failedRequired}`;
    stabilityPath.textContent = `report ${shortPathText(report.written_path || report.root)}`;
  }

  function formatStabilityReport(data) {
    const checks = Array.isArray(data.checks) ? data.checks : [];
    const lines = [
      `overall: ${data.passed ? 'PASS' : 'FAIL'}`,
      `checks: ${checks.filter(item => item && item.passed).length}/${data.check_count || checks.length || '--'}`,
      `failed_required: ${data.failed_required_count ?? '--'}`,
      `failed_optional: ${data.failed_optional_count ?? '--'}`,
      `api_url: ${data.api_url || '--'}`,
      `written_path: ${data.written_path || '--'}`,
      '',
      'Checks:',
    ];
    checks.forEach(check => {
      if (!check) return;
      let detail = check.error || check.reason || '';
      if (!detail && check.passed_count !== undefined && check.case_count !== undefined) {
        detail = `${check.passed_count}/${check.case_count}`;
      }
      if (!detail && check.elapsed_seconds !== undefined) {
        detail = `${check.elapsed_seconds}s`;
      }
      lines.push(`- ${check.name}: ${check.status || (check.passed ? 'passed' : 'failed')}${detail ? ` · ${detail}` : ''}`);
      const report = check.report || {};
      if (Array.isArray(report.failed_cases) && report.failed_cases.length) {
        lines.push(`  failed_cases: ${report.failed_cases.join(', ')}`);
      }
    });
    return lines.join('\n');
  }

  function promptRegressionLabel(report) {
    if (!report) return '--';
    if (report.ok === false) return 'FAIL';
    if (report.status === 'changed' || ((report.diff || {}).prompt_changed)) return 'CHANGED';
    return 'PASS';
  }

  function renderPromptStrip(report) {
    if (!promptStrip || !promptMain || !promptMeta || !promptPath) return;
    promptStrip.classList.remove('pass', 'fail', 'changed', 'muted');
    if (!report) {
      promptStrip.classList.add('muted');
      promptMain.textContent = 'Prompt --';
      promptMeta.textContent = '未檢查';
      promptPath.textContent = 'baseline --';
      return;
    }
    const label = promptRegressionLabel(report);
    promptStrip.classList.add(label === 'FAIL' ? 'fail' : (label === 'CHANGED' ? 'changed' : 'pass'));
    const diff = report.diff || {};
    const fingerprint = report.fingerprint || {};
    const changedCount = (Array.isArray(diff.changed) ? diff.changed.length : 0);
    const addedCount = (Array.isArray(diff.added) ? diff.added.length : 0);
    const removedCount = (Array.isArray(diff.removed) ? diff.removed.length : 0);
    promptMain.textContent = `Prompt ${label}`;
    promptMeta.textContent = `files=${fingerprint.file_count ?? '--'} · +${addedCount}/~${changedCount}/-${removedCount}`;
    promptPath.textContent = `baseline ${report.baseline_present ? 'present' : 'missing'}`;
  }

  function formatPromptRegressionReport(data) {
    const diff = data.diff || {};
    const fingerprint = data.fingerprint || {};
    const checks = data.checks || {};
    const benchmark = checks.benchmark || {};
    const quick = checks.quick_eval || {};
    const episode = checks.episode_compare || {};
    const lines = [
      `status: ${data.status || '--'} · label=${promptRegressionLabel(data)} · ok=${data.ok}`,
      `checked_at: ${data.checked_at || '--'}`,
      `prompt_hash: ${(fingerprint.sha256 || '').slice(0, 16) || '--'}`,
      `files: ${fingerprint.file_count ?? '--'} · bytes=${fingerprint.total_bytes ?? '--'}`,
      `baseline_present: ${data.baseline_present}`,
      `baseline_path: ${data.baseline_path || '--'}`,
      `written_path: ${data.written_path || '--'}`,
      '',
      `prompt_changed: ${diff.prompt_changed ? 'YES' : 'NO'}`,
      `added: ${(diff.added || []).length}`,
      `changed: ${(diff.changed || []).length}`,
      `removed: ${(diff.removed || []).length}`,
      '',
      `benchmark: ${yesNo(benchmark.passed)} ${benchmark.passed_count ?? '--'}/${benchmark.case_count ?? '--'}`,
      `quick_eval: ${yesNo(quick.passed)} ${quick.reason || (quick.skipped ? 'skipped' : '')}`.trim(),
      `episode_compare: ${episode.status || '--'} ok=${episode.ok ?? '--'}`,
    ];
    if (Array.isArray(data.failures) && data.failures.length) {
      lines.push('', 'Failures:', ...data.failures.map(item => `- ${item}`));
    }
    if (Array.isArray(data.warnings) && data.warnings.length) {
      lines.push('', 'Warnings:', ...data.warnings.map(item => `- ${item}`));
    }
    [['Added', diff.added], ['Changed', diff.changed], ['Removed', diff.removed]].forEach(([label, items]) => {
      lines.push('', `${label} files:`);
      if (Array.isArray(items) && items.length) {
        items.slice(0, 80).forEach(item => lines.push(`- ${item}`));
        if (items.length > 80) lines.push(`... ${items.length - 80} more`);
      } else {
        lines.push('- (none)');
      }
    });
    return lines.join('\n');
  }

  async function loadLatestPromptRegression(quiet = true) {
    try {
      const resp = await fetch('/api/upgrade/prompt-regression/latest');
      const data = await resp.json();
      if (!resp.ok || !data.ok) throw new Error(data.detail || data.error || `HTTP ${resp.status}`);
      renderPromptStrip(data.report || null);
    } catch (e) {
      if (!quiet && promptMain) {
        promptMain.textContent = `Prompt unavailable: ${e.message}`;
      }
    }
  }

  function formatSnapshotDiff(data) {
    const diff = data.diff || {};
    if (!data.has_snapshot) {
      return `plan_id: ${data.plan_id || '--'}\npre_install_snapshot: none`;
    }
    const lines = [
      `plan_id: ${data.plan_id || '--'}`,
      `clean: ${diff.clean === true ? 'YES' : 'NO'}`,
      `changed: ${diff.changed_count ?? 0}`,
      `added: ${diff.added_count ?? 0}`,
      `removed: ${diff.removed_count ?? 0}`,
      `unchanged: ${diff.unchanged_count ?? '--'}`,
      `snapshot_path: ${diff.snapshot_path || (data.snapshot && data.snapshot.path) || '--'}`,
      `before_sha256: ${diff.before_aggregate_sha256 || '--'}`,
      `after_sha256: ${diff.after_aggregate_sha256 || '--'}`,
    ];
    [['Changed', diff.changed], ['Added', diff.added], ['Removed', diff.removed]].forEach(([label, items]) => {
      lines.push('', `${label}:`);
      if (Array.isArray(items) && items.length) {
        items.slice(0, 80).forEach(item => lines.push(`- ${item}`));
        if (items.length > 80) lines.push(`... ${items.length - 80} more`);
      } else {
        lines.push('- (none)');
      }
    });
    return lines.join('\n');
  }

  async function runSnapshotDiff(planId) {
    if (!planId) return;
    statusEl.classList.remove('hidden');
    statusEl.innerHTML = '<span class="spinner"></span> Checking pre-install snapshot diff...';
    try {
      const resp = await fetch(`/api/upgrade/plan/${encodeURIComponent(planId)}/snapshot-diff`);
      const data = await resp.json();
      if (!resp.ok || !data.ok) throw new Error(data.detail || data.error || `HTTP ${resp.status}`);
      const diff = data.diff || {};
      const label = !data.has_snapshot ? 'NO SNAPSHOT' : (diff.clean ? 'CLEAN' : 'CHANGED');
      showResult(`Snapshot diff · ${label}`, formatSnapshotDiff(data), 'snapshot');
      installActions.classList.add('hidden');
    } catch (err) {
      statusEl.innerHTML = `Snapshot diff failed: ${err.message}`;
      statusEl.style.color = 'var(--son)';
      setTimeout(() => { statusEl.classList.add('hidden'); statusEl.style.color = ''; }, 5000);
      return;
    }
    statusEl.classList.add('hidden');
  }

  async function loadLatestStabilityReport(quiet = true) {
    try {
      const resp = await fetch('/api/upgrade/stability/latest');
      const data = await resp.json();
      if (!resp.ok || !data.ok) throw new Error(data.detail || data.error || `HTTP ${resp.status}`);
      renderStabilityStrip(data.report || null);
    } catch (e) {
      if (!quiet && stabilityMain) {
        stabilityMain.textContent = `Stability unavailable: ${e.message}`;
      }
    }
  }

  function formatSelfUpgradeReport(data) {
    const summary = data.summary || {};
    const latest = data.latest_plan || {};
    const files = data.files || {};
    const items = Array.isArray(data.action_items) ? data.action_items : [];
    const lines = [
      `report_id: ${data.report_id || '--'}`,
      `status: ${data.status || '--'} · ok=${data.ok}`,
      `generated_at: ${data.generated_at || '--'}`,
      `latest_plan: ${summary.latest_plan_id || '--'} ${summary.latest_plan_status || ''}`.trim(),
      `gates_ok: ${summary.gates_ok}`,
      `prompt_regression: ${summary.prompt_regression_status || '--'}`,
      `prompt_changed: ${summary.prompt_changed}`,
      `markdown: ${files.markdown_path || '--'}`,
      `json: ${files.json_path || '--'}`,
      '',
      'Action Items:',
    ];
    if (!items.length) {
      lines.push('- (none)');
    } else {
      items.forEach(item => {
        const detail = item.detail ? ` — ${item.detail}` : '';
        const action = item.action ? ` | Action: ${item.action}` : '';
        lines.push(`- [${item.priority || '--'}] ${item.title || ''}${detail}${action}`);
      });
    }
    if (latest.summary) {
      lines.push('', 'Latest Plan Summary:', latest.summary);
    }
    return lines.join('\n');
  }

  async function runGateCheck() {
    setLoading(true, 'gate');
    try {
      const resp = await fetch('/api/upgrade/gates');
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || data.error || `HTTP ${resp.status}`);
      showResult(`升級硬閘檢查 · ${data.ok ? 'PASS' : 'FAIL'}`, formatGatePreflight(data), 'gate');
      installActions.classList.add('hidden');
      loadRuntimeStatus(true);
    } catch (err) {
      statusEl.classList.remove('hidden');
      statusEl.innerHTML = `❌ 硬閘檢查失敗：${err.message}`;
      statusEl.style.color = 'var(--son)';
      setTimeout(() => { statusEl.classList.add('hidden'); statusEl.style.color = ''; }, 5000);
    } finally {
      setLoading(false, 'gate');
    }
  }

  async function runStabilityCheck() {
    setLoading(true, 'stability');
    try {
      const resp = await fetch('/api/upgrade/stability', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          require_api: true,
          skip_pytest: true,
          write: true,
        }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || data.error || `HTTP ${resp.status}`);
      renderStabilityStrip(data);
      showResult(`System stability · ${data.passed ? 'PASS' : 'FAIL'}`, formatStabilityReport(data), 'stability');
      installActions.classList.add('hidden');
      loadRuntimeStatus(true);
    } catch (err) {
      statusEl.classList.remove('hidden');
      statusEl.innerHTML = `Stability check failed: ${err.message}`;
      statusEl.style.color = 'var(--son)';
      setTimeout(() => { statusEl.classList.add('hidden'); statusEl.style.color = ''; }, 5000);
    } finally {
      setLoading(false, 'stability');
    }
  }

  async function runPromptRegression() {
    setLoading(true, 'prompt');
    try {
      const resp = await fetch('/api/upgrade/prompt-regression', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          run_benchmark: true,
          run_quick_eval: true,
          compare_latest_episode: true,
          strict_episode: false,
          update_baseline: false,
          label: 'ui',
          write: true,
        }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || data.error || `HTTP ${resp.status}`);
      renderPromptStrip(data);
      showResult(`Prompt regression · ${promptRegressionLabel(data)}`, formatPromptRegressionReport(data), 'prompt');
      installActions.classList.add('hidden');
      loadRuntimeStatus(true);
    } catch (err) {
      statusEl.classList.remove('hidden');
      statusEl.innerHTML = `Prompt regression failed: ${err.message}`;
      statusEl.style.color = 'var(--son)';
      setTimeout(() => { statusEl.classList.add('hidden'); statusEl.style.color = ''; }, 5000);
    } finally {
      setLoading(false, 'prompt');
    }
  }

  async function runUpgradeReport() {
    setLoading(true, 'report');
    try {
      const resp = await fetch('/api/upgrade/report', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          plan_limit: 8,
          log_limit: 12,
          run_gates: true,
          run_prompt_regression: true,
          write: true,
        }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || data.error || `HTTP ${resp.status}`);
      showResult(`Self-upgrade report · ${data.status || 'unknown'}`, formatSelfUpgradeReport(data), 'report');
      installActions.classList.add('hidden');
      loadRuntimeStatus(true);
    } catch (err) {
      statusEl.classList.remove('hidden');
      statusEl.innerHTML = `❌ 生成報告失敗：${err.message}`;
      statusEl.style.color = 'var(--son)';
      setTimeout(() => { statusEl.classList.add('hidden'); statusEl.style.color = ''; }, 5000);
    } finally {
      setLoading(false, 'report');
    }
  }

  async function runUpgrade(mode) {
    const relay = relaySelect.value;
    setLoading(true, mode);
    try {
      const endpoint = mode === 'audit' ? '/api/upgrade/audit' : '/api/upgrade/learn';
      const resp = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ relay_target: relay, max_sessions: 10 }),
      });
      const data = await resp.json();
      if (!resp.ok || !data.ok) {
        throw new Error(data.detail || data.error || `HTTP ${resp.status}`);
      }
      const modeLabel = mode === 'audit' ? '缺陷審計' : '互聯網學習';
      const relayLabel = relaySelect.options[relaySelect.selectedIndex].text;
      const actualRelayLabel = data.fallback_target ? `${relayLabel} → ${data.fallback_target}` : relayLabel;
      showResult(
        `${modeLabel}結果 · ${upgradeOutcomeLabel(data.status)} · 透過 ${actualRelayLabel}`,
        data.summary || data.response || JSON.stringify(data, null, 2),
        mode
      );
      // Load log strip
      loadUpgradeLog();
      loadRuntimeStatus(true);
      loadUpgradePlans(data.plan_id || null);
    } catch (err) {
      statusEl.classList.remove('hidden');
      statusEl.innerHTML = `❌ 失敗：${err.message}`;
      statusEl.style.color = 'var(--son)';
      setTimeout(() => { statusEl.classList.add('hidden'); statusEl.style.color = ''; }, 5000);
    } finally {
      setLoading(false, mode);
    }
  }

  auditBtn.addEventListener('click', () => runUpgrade('audit'));
  learnBtn.addEventListener('click', () => runUpgrade('learn'));
  if (relaySelect) {
    relaySelect.addEventListener('change', () => renderRuntimeStatus(latestRuntimeStatus, latestLoopState));
  }
  if (gateCheckBtn) {
    gateCheckBtn.addEventListener('click', runGateCheck);
  }
  if (stabilityCheckBtn) {
    stabilityCheckBtn.addEventListener('click', runStabilityCheck);
  }
  if (promptCheckBtn) {
    promptCheckBtn.addEventListener('click', runPromptRegression);
  }
  if (reportBtn) {
    reportBtn.addEventListener('click', runUpgradeReport);
  }
  if (loopBtn) {
    loopBtn.addEventListener('click', async () => {
      const relay = relaySelect.value;
      statusEl.classList.remove('hidden');
      statusEl.innerHTML = '<span class="spinner"></span> 啟動循環自我升級⋯';
      try {
        const resp = await fetch('/api/upgrade/loop/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            relay_target: relay,
            max_sessions: 10,
            modes: ['audit', 'learn'],
            interval_seconds: 30,
          }),
        });
        const data = await resp.json();
        if (!resp.ok || !data.ok) throw new Error(data.detail || data.error || `HTTP ${resp.status}`);
        renderLoopState(data.state);
        if (!loopPollTimer) loopPollTimer = setInterval(() => loadLoopStatus(true), 4000);
      } catch (e) {
        statusEl.innerHTML = `❌ 啟動失敗：${e.message}`;
      }
    });
  }

  if (pauseBtn) {
    pauseBtn.disabled = true;
    pauseBtn.addEventListener('click', async () => {
      statusEl.classList.remove('hidden');
      statusEl.innerHTML = '<span class="spinner"></span> 已要求暫停；等待當前工作完成⋯';
      try {
        const resp = await fetch('/api/upgrade/loop/pause', { method: 'POST' });
        const data = await resp.json();
        if (!resp.ok || !data.ok) throw new Error(data.detail || data.error || `HTTP ${resp.status}`);
        renderLoopState(data.state);
        if (!loopPollTimer) loopPollTimer = setInterval(() => loadLoopStatus(true), 4000);
      } catch (e) {
        statusEl.innerHTML = `❌ 暫停失敗：${e.message}`;
      }
    });
  }

  closeBtn.addEventListener('click', () => {
    resultEl.classList.add('hidden');
    installActions.classList.add('hidden');
  });

  // 發送結果到主輸入欄讓用戶處理
  sendToInputBtn.addEventListener('click', () => {
    const userInput = document.getElementById('user-input');
    if (userInput && resultBody.textContent) {
      userInput.value = resultBody.textContent;
      userInput.dispatchEvent(new Event('input'));
      userInput.focus();
      resultEl.classList.add('hidden');
    }
  });

  async function loadUpgradeLog() {
    try {
      const resp = await fetch('/api/upgrade/log');
      const data = await resp.json();
      if (data.entries && data.entries.length > 0) {
        const latest = data.entries.slice(0, 3);
        logStrip.textContent = '最近升級：' + latest.map(e =>
          `${e.tool_name}（${(e.timestamp||'').slice(0,10)}）`
        ).join(' · ');
        logStrip.classList.remove('hidden');
      }
    } catch (_) {}
  }

  function planStatusClass(status) {
    return `status-${String(status || '').replace(/[^a-z0-9_]+/gi, '_')}`;
  }

  function gateBadge(ok, fallbackText = '--') {
    if (ok === true) return '<span class="sup-gate-badge pass">PASS</span>';
    if (ok === false) return '<span class="sup-gate-badge fail">FAIL</span>';
    return `<span class="sup-gate-badge muted">${escapeHtml(fallbackText)}</span>`;
  }

  function formatSigned(value) {
    if (typeof value !== 'number' || Number.isNaN(value)) return '--';
    return `${value >= 0 ? '+' : ''}${value.toFixed(3)}`;
  }

  function renderRegressionGateBlock(steps) {
    const evalStep = steps.find(s => s.action === 'post_install_eval');
    const output = evalStep && evalStep.output && typeof evalStep.output === 'object' ? evalStep.output : null;
    if (!output) {
      return `
        <div class="sup-plan-detail-block">
          <strong>Regression Gates</strong>
          <div>未有 post-install eval 記錄</div>
        </div>`;
    }

    const knowledge = output.knowledge_audit || {};
    const benchmark = output.benchmark || {};
    const stability = output.stability_golden || {};
    const rollback = output.rollback || {};
    const failedCases = Array.isArray(benchmark.failed_cases) ? benchmark.failed_cases : [];
    const stabilityFailedCases = Array.isArray(stability.failed_cases) ? stability.failed_cases : [];
    const rollbackRemoved = Array.isArray(rollback.removed) ? rollback.removed : [];
    const hasQuickEvalDelta = output.framing_iou_delta !== undefined || output.chain_match_delta !== undefined;
    const quickEvalSkipped = output.skipped ? `skipped: ${output.reason || 'no reason'}` : '';
    const quickEvalLine = hasQuickEvalDelta
      ? `framing_iou Δ=${formatSigned(Number(output.framing_iou_delta))} · chain_match Δ=${formatSigned(Number(output.chain_match_delta))}`
      : quickEvalSkipped || 'quick_eval 未執行或無 baseline';
    const quickEvalOk = hasQuickEvalDelta ? output.regressed !== true : null;

    return `
      <div class="sup-plan-detail-block">
        <strong>Regression Gates</strong>
        <div class="sup-gate-row">
          <span>Knowledge audit</span>
          ${gateBadge(knowledge.passed)}
          <span>${escapeHtml(knowledge.passed === false ? 'P0 / fatal issue' : 'clean / no fatal issue')}</span>
        </div>
        <div class="sup-gate-row">
          <span>Coordinate benchmark</span>
          ${gateBadge(benchmark.passed)}
          <span>${escapeHtml(`${benchmark.passed_count ?? '--'}/${benchmark.case_count ?? '--'} cases`)}</span>
        </div>
        ${failedCases.length ? `<div class="sup-gate-note">failed_cases: ${escapeHtml(failedCases.join(', '))}</div>` : ''}
        <div class="sup-gate-row">
          <span>Stability golden</span>
          ${gateBadge(stability.passed)}
          <span>${escapeHtml(`${stability.passed_count ?? '--'}/${stability.case_count ?? '--'} cases`)}</span>
        </div>
        ${stabilityFailedCases.length ? `<div class="sup-gate-note">stability_failed_cases: ${escapeHtml(stabilityFailedCases.join(', '))}</div>` : ''}
        <div class="sup-gate-row">
          <span>quick_eval</span>
          ${gateBadge(quickEvalOk, hasQuickEvalDelta ? '--' : 'SKIP')}
          <span>${escapeHtml(quickEvalLine)}</span>
        </div>
        ${output.reason ? `<div class="sup-gate-note">reason: ${escapeHtml(output.reason)}</div>` : ''}
        ${rollbackRemoved.length ? `<div class="sup-gate-note fail">rollback_removed: ${escapeHtml(rollbackRemoved.join(', '))}</div>` : ''}
      </div>`;
  }

  async function loadUpgradePlans(selectPlanId = latestSelectedPlanId) {
    if (!planList) return;
    try {
      const resp = await fetch('/api/upgrade/plans');
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || data.error || `HTTP ${resp.status}`);
      renderUpgradePlanList(data.plans || [], selectPlanId);
      const target = selectPlanId || (data.plans && data.plans[0] && data.plans[0].plan_id);
      if (target) loadUpgradePlanDetail(target);
    } catch (e) {
      planList.innerHTML = `<div class="sup-plan-empty">讀取計劃失敗：${escapeHtml(String(e.message || e))}</div>`;
    }
  }

  function renderUpgradePlanList(plans, selectedPlanId) {
    if (!planList) return;
    if (!plans.length) {
      planList.innerHTML = '<div class="sup-plan-empty">未有升級計劃</div>';
      if (planDetail) planDetail.classList.add('hidden');
      return;
    }
    planList.innerHTML = plans.slice(0, 8).map(p => {
      const active = p.plan_id === selectedPlanId ? ' active' : '';
      const status = escapeHtml(p.status || 'unknown');
      const mode = escapeHtml(p.mode || '');
      const installed = Array.isArray(p.installed_tools) ? p.installed_tools.length : 0;
      const review = Number(p.review_count || 0);
      const gap = Number(p.gap_count || 0);
      const summary = p.summary || `${gap} gaps · ${installed} installed${review ? ` · ${review} review` : ''}`;
      return `
        <div class="sup-plan-card${active}" data-plan-id="${escapeHtml(p.plan_id)}">
          <div class="sup-plan-row">
            <span class="sup-plan-id">${escapeHtml(p.plan_id)}</span>
            <span class="sup-plan-chip">${mode}</span>
            <span class="sup-plan-chip ${planStatusClass(p.status)}">${status}</span>
          </div>
          <div class="sup-plan-summary">${escapeHtml(summary)}</div>
        </div>`;
    }).join('');
    planList.querySelectorAll('.sup-plan-card').forEach(card => {
      card.addEventListener('click', () => loadUpgradePlanDetail(card.dataset.planId));
    });
  }

  async function loadUpgradePlanDetail(planId) {
    if (!planId || !planDetail) return;
    latestSelectedPlanId = planId;
    try {
      const resp = await fetch(`/api/upgrade/plan/${encodeURIComponent(planId)}`);
      const plan = await resp.json();
      if (!resp.ok) throw new Error(plan.detail || plan.error || `HTTP ${resp.status}`);
      renderUpgradePlanDetail(plan);
      if (planList) {
        planList.querySelectorAll('.sup-plan-card').forEach(card => {
          card.classList.toggle('active', card.dataset.planId === planId);
        });
      }
    } catch (e) {
      planDetail.classList.remove('hidden');
      planDetail.innerHTML = `<div class="sup-plan-detail-title">讀取 ${escapeHtml(planId)} 失敗</div><div class="sup-plan-detail-block">${escapeHtml(String(e.message || e))}</div>`;
    }
  }

  function renderUpgradePlanDetail(plan) {
    if (!planDetail) return;
    const steps = Array.isArray(plan.steps) ? plan.steps : [];
    const failed = steps.filter(s => s.status === 'failed').map(s => s.action);
    const reviewCount = Array.isArray(plan.review_tool_specs) ? plan.review_tool_specs.length : 0;
    const executorEvents = Array.isArray(plan.executor_events) ? plan.executor_events : [];
    const gaps = Array.isArray(plan.gaps) ? plan.gaps : [];
    const snapshots = plan.snapshots && typeof plan.snapshots === 'object' ? plan.snapshots : {};
    const preSnapshot = snapshots.pre_install || {};
    const gateHtml = renderRegressionGateBlock(steps);
    const stepHtml = steps.map(s => `
      <div class="sup-plan-step" title="${escapeHtml(s.error || s.success_criteria || '')}">
        <span class="sup-step-status ${escapeHtml(s.status || '')}">${escapeHtml(s.status || 'pending')}</span>
        <span class="sup-step-action">${escapeHtml(s.action || '')}</span>
        <span>${Number(s.duration_ms || 0)}ms</span>
      </div>`).join('');
    const gapHtml = gaps.slice(0, 5).map(g =>
      `<div>${escapeHtml(g.priority || '')} · ${escapeHtml(g.type || '')} · ${escapeHtml(g.description || g.evidence || g.id || '')}</div>`
    ).join('') || '<div>無 recorded gaps</div>';
    const eventHtml = executorEvents.slice(-5).map(e => {
      const decision = e.decision || {};
      return `<div>${escapeHtml(e.step || '')}: ${escapeHtml(e.outcome || '')} · ${escapeHtml(decision.reason || e.reason || '')}</div>`;
    }).join('') || '<div>無 executor events</div>';
    const snapshotHtml = preSnapshot.path ? `
      <div class="sup-plan-detail-block">
        <strong>Pre-install Snapshot</strong>
        <div>path: ${escapeHtml(preSnapshot.path || '')}</div>
        <div>sha256: ${escapeHtml(preSnapshot.aggregate_sha256 || '--')}</div>
        <div>files: ${escapeHtml(String(preSnapshot.file_count ?? '--'))} · missing: ${escapeHtml(String(preSnapshot.missing_count ?? '--'))}</div>
        <button class="sup-plan-refresh sup-snapshot-diff-btn" type="button" data-plan-id="${escapeHtml(plan.plan_id || '')}">Diff snapshot</button>
      </div>` : `
      <div class="sup-plan-detail-block">
        <strong>Pre-install Snapshot</strong>
        <div>(none)</div>
      </div>`;
    planDetail.classList.remove('hidden');
    planDetail.innerHTML = `
      <div class="sup-plan-detail-title">${escapeHtml(plan.plan_id || '')} · ${escapeHtml(plan.status || '')}</div>
      <div class="sup-plan-steps">${stepHtml}</div>
      <div class="sup-plan-detail-block">
        <strong>Summary</strong>
        <div>${escapeHtml(plan.summary || '(empty)')}</div>
        <div>installed: ${escapeHtml((plan.installed_tools || []).join(', ') || '(none)')}</div>
        <div>review_required: ${reviewCount}</div>
        ${failed.length ? `<div>failed_steps: ${escapeHtml(failed.join(', '))}</div>` : ''}
      </div>
      ${snapshotHtml}
      ${gateHtml}
      <div class="sup-plan-detail-block"><strong>Gaps</strong>${gapHtml}</div>
      <div class="sup-plan-detail-block"><strong>Executor Events</strong>${eventHtml}</div>
    `;
    const snapshotDiffBtn = planDetail.querySelector('.sup-snapshot-diff-btn');
    if (snapshotDiffBtn) {
      snapshotDiffBtn.addEventListener('click', () => runSnapshotDiff(plan.plan_id));
    }
  }

  // Load log on init
  loadRuntimeStatus(true);
  loadLatestStabilityReport(true);
  loadLatestPromptRegression(true);
  loadUpgradeLog();
  loadUpgradePlans();
  loadLoopStatus(true);
  setInterval(() => loadRuntimeStatus(true), 15000);
  if (planRefresh) planRefresh.addEventListener('click', () => loadUpgradePlans(null));
})();

// ═══════════════════════════════════════════════════════════
// Feature 1 + 2 — Tool Toolbar + Live Mode
// ═══════════════════════════════════════════════════════════

async function _callAgentTool(name, args) {
  const r = await fetch('/api/agent/execute', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, args }),
  });
  if (!r.ok) throw new Error(`tool ${name} HTTP ${r.status}`);
  return await r.json();
}

// Live mode state
const _live = {
  on: false,
  state: 'idle',       // idle | listening | thinking | speaking
  lang: 'yue',
  abortController: null,
};

function _setLiveState(state) {
  _live.state = state;
  const dot = document.getElementById('live-state-dot');
  const txt = document.getElementById('live-state-text');
  const wave = document.getElementById('live-wave');
  if (!dot || !txt) return;
  dot.className = 'live-state-dot ' + (state === 'idle' ? '' : state);
  const labels = { idle: '就緒', listening: '聆聽中…', thinking: '思考中…', speaking: '說話中…' };
  txt.textContent = labels[state] || state;
  if (wave) wave.classList.toggle('active', state === 'listening');
}

async function _liveLoop() {
  if (!_live.on) return;
  _setLiveState('listening');
  try {
    const txRes = await _callAgentTool('transcribe_audio', {
      source: 'record', duration_seconds: 5, lang: _live.lang,
    });
    if (!_live.on) return;
    if (txRes.ok && txRes.output) {
      const text = typeof txRes.output === 'string' ? txRes.output : (txRes.output.text || JSON.stringify(txRes.output));
      const inputEl = document.getElementById('user-input');
      if (inputEl) inputEl.value = text;
      _setLiveState('thinking');
      // auto-submit
      await new Promise(resolve => {
        const doneHandler = () => {
          document.removeEventListener('_trinityDone', doneHandler);
          resolve();
        };
        document.addEventListener('_trinityDone', doneHandler, { once: true });
        runTrinity();
        // fallback timeout
        setTimeout(resolve, 30000);
      });
      if (!_live.on) return;
      _setLiveState('speaking');
      const councilEl = document.getElementById('council-answer-body') || document.getElementById('output-council');
      const councilText = councilEl ? councilEl.textContent.trim() : '';
      if (councilText) {
        await _callAgentTool('speak_text', { text: councilText.slice(0, 2000), lang: _live.lang });
      }
      const lastTurnEl = document.getElementById('live-last-turn');
      if (lastTurnEl) lastTurnEl.textContent = '↩ ' + (text.slice(0, 60) || '(no input)');
    }
  } catch (e) {
    console.warn('live loop error:', e);
  }
  if (_live.on) {
    await new Promise(r => setTimeout(r, 1000));
    _liveLoop();
  } else {
    _setLiveState('idle');
  }
}

function _startLive() {
  _live.on = true;
  const panel = document.getElementById('live-mode-panel');
  if (panel) panel.style.display = '';
  const btnLabel = document.getElementById('live-btn-label');
  const liveDot = document.getElementById('live-dot');
  const liveBtn = document.getElementById('btn-live');
  if (btnLabel) btnLabel.textContent = 'Live';
  if (liveDot) liveDot.classList.add('pulse');
  if (liveBtn) liveBtn.classList.add('on');
  _liveLoop();
}

function _stopLive() {
  _live.on = false;
  _setLiveState('idle');
  const panel = document.getElementById('live-mode-panel');
  if (panel) panel.style.display = 'none';
  const liveDot = document.getElementById('live-dot');
  const liveBtn = document.getElementById('btn-live');
  if (liveDot) liveDot.classList.remove('pulse');
  if (liveBtn) liveBtn.classList.remove('on');
}

function setupToolToolbar() {
  const btnScreenshot = document.getElementById('btn-screenshot');
  const btnOcr        = document.getElementById('btn-ocr');
  const btnClipboard  = document.getElementById('btn-clipboard');
  const btnMic        = document.getElementById('btn-mic');
  const btnSpeak      = document.getElementById('btn-speak');
  const btnLive       = document.getElementById('btn-live');
  const btnLiveStop   = document.getElementById('btn-live-stop');

  if (btnScreenshot) {
    btnScreenshot.addEventListener('click', async () => {
      btnScreenshot.classList.add('active');
      try {
        const res = await _callAgentTool('capture_screenshot', { region: 'full' });
        const path = res.output?.path || res.output?.file || (typeof res.output === 'string' ? res.output : '');
        setStatus(res.ok ? `📸 截圖已儲存${path ? ': ' + path : ''}` : `截圖失敗: ${res.error}`);
      } catch (e) { setStatus('截圖錯誤: ' + e.message); }
      finally { btnScreenshot.classList.remove('active'); }
    });
  }

  if (btnOcr) {
    btnOcr.addEventListener('click', async () => {
      btnOcr.classList.add('active');
      try {
        const res = await _callAgentTool('ocr_read_screen', { source: 'screen' });
        if (res.ok && res.output) {
          const text = typeof res.output === 'string' ? res.output : (res.output.text || JSON.stringify(res.output));
          const inp = document.getElementById('user-input');
          if (inp) { inp.value = (inp.value ? inp.value + '\n' : '') + text; inp.focus(); }
          setStatus('OCR 完成，文字已貼入輸入框');
        } else { setStatus('OCR 失敗: ' + (res.error || '未知錯誤')); }
      } catch (e) { setStatus('OCR 錯誤: ' + e.message); }
      finally { btnOcr.classList.remove('active'); }
    });
  }

  if (btnClipboard) {
    btnClipboard.addEventListener('click', async () => {
      btnClipboard.classList.add('active');
      try {
        const res = await _callAgentTool('read_clipboard_image', {});
        setStatus(res.ok ? `剪貼板已讀取${res.output ? ': ' + JSON.stringify(res.output).slice(0, 80) : ''}` : `剪貼板失敗: ${res.error}`);
      } catch (e) { setStatus('剪貼板錯誤: ' + e.message); }
      finally { btnClipboard.classList.remove('active'); }
    });
  }

  if (btnMic) {
    btnMic.addEventListener('click', async () => {
      btnMic.classList.add('active');
      setStatus('🎙 錄音中 (5s)…');
      try {
        const res = await _callAgentTool('transcribe_audio', { source: 'record', duration_seconds: 5, lang: 'auto' });
        if (res.ok && res.output) {
          const text = typeof res.output === 'string' ? res.output : (res.output.text || JSON.stringify(res.output));
          const inp = document.getElementById('user-input');
          if (inp) { inp.value = (inp.value ? inp.value + ' ' : '') + text; inp.focus(); }
          setStatus('🎙 語音識別完成');
        } else { setStatus('語音識別失敗: ' + (res.error || '未知錯誤')); }
      } catch (e) { setStatus('語音識別錯誤: ' + e.message); }
      finally { btnMic.classList.remove('active'); }
    });
  }

  if (btnSpeak) {
    btnSpeak.addEventListener('click', async () => {
      btnSpeak.classList.add('active');
      try {
        const councilEl = document.getElementById('council-answer-body') || document.getElementById('output-council');
        const text = councilEl ? councilEl.textContent.trim() : '';
        if (!text) { setStatus('沒有回覆文字可朗讀'); return; }
        const res = await _callAgentTool('speak_text', { text: text.slice(0, 2000), lang: 'auto' });
        setStatus(res.ok ? '🔊 朗讀完成' : `朗讀失敗: ${res.error}`);
      } catch (e) { setStatus('朗讀錯誤: ' + e.message); }
      finally { btnSpeak.classList.remove('active'); }
    });
  }

  if (btnLive) {
    btnLive.addEventListener('click', () => {
      if (_live.on) _stopLive(); else _startLive();
    });
  }

  if (btnLiveStop) {
    btnLiveStop.addEventListener('click', _stopLive);
  }

  // lang chip selection in live panel
  document.querySelectorAll('#live-lang-row .lang-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      document.querySelectorAll('#live-lang-row .lang-chip').forEach(c => c.classList.remove('selected'));
      chip.classList.add('selected');
      _live.lang = chip.dataset.lang;
    });
  });

  // ESC stops live mode
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && _live.on) _stopLive();
  });
}

// ═══════════════════════════════════════════════════════════
// Feature 3 — Learn Pane
// ═══════════════════════════════════════════════════════════

function setupLearnPane() {
  // Wire quick buttons
  document.querySelectorAll('.learn-quick-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const tool = btn.dataset.tool;
      let args = {};
      try { args = JSON.parse(btn.dataset.args || '{}'); } catch(e) {}
      btn.disabled = true;
      const resultsEl = document.getElementById('learn-results');
      if (resultsEl) { resultsEl.textContent = '⋯ 載入中'; resultsEl.classList.add('visible'); }
      try {
        const res = await _callAgentTool(tool, args);
        const out = res.output;
        const saved = out && (out.items_saved ?? out.saved ?? (Array.isArray(out) ? out.length : null));
        const reindexed = out && !!out.rag_reindexed;
        if (res.ok) {
          if (resultsEl) resultsEl.textContent = `✓ ${saved != null ? saved + ' items saved' : 'done'}${reindexed ? ' · RAG re-indexed' : ''}`;
        } else {
          if (resultsEl) resultsEl.textContent = `✗ ${res.error || '失敗'}`;
        }
      } catch (e) {
        if (resultsEl) resultsEl.textContent = '錯誤: ' + e.message;
      } finally {
        btn.disabled = false;
      }
    });
  });

  // Wire URL input + fetch button
  const fetchBtn = document.getElementById('learn-fetch-btn');
  const urlInput = document.getElementById('learn-url-input');
  const toolSel  = document.getElementById('learn-tool-select');
  const resultsEl = document.getElementById('learn-results');

  async function doLearnFetch() {
    const val = urlInput ? urlInput.value.trim() : '';
    const tool = toolSel ? toolSel.value : 'fetch_webpage';
    if (!val) return;
    if (fetchBtn) fetchBtn.disabled = true;
    if (resultsEl) { resultsEl.textContent = '⋯ 載入中'; resultsEl.classList.add('visible'); }
    const urlTools = ['fetch_webpage', 'fetch_rss_feed'];
    const args = urlTools.includes(tool)
      ? { url: val, save: true }
      : { query: val, save: true };
    try {
      const res = await _callAgentTool(tool, args);
      const out = res.output;
      const saved = out && (out.items_saved ?? out.saved ?? (Array.isArray(out) ? out.length : null));
      const reindexed = out && !!out.rag_reindexed;
      if (res.ok) {
        if (resultsEl) resultsEl.textContent = `✓ ${saved != null ? saved + ' items saved' : 'done'}${reindexed ? ' · RAG re-indexed' : ''}`;
      } else {
        if (resultsEl) resultsEl.textContent = `✗ ${res.error || '失敗'}`;
      }
    } catch (e) {
      if (resultsEl) resultsEl.textContent = '錯誤: ' + e.message;
    } finally {
      if (fetchBtn) fetchBtn.disabled = false;
    }
  }

  if (fetchBtn) fetchBtn.addEventListener('click', doLearnFetch);
  if (urlInput) urlInput.addEventListener('keydown', e => { if (e.key === 'Enter') doLearnFetch(); });
}
