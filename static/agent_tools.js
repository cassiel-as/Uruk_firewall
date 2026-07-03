/**
 * URUK Trinity Console — Agent Tools Manager (v8.45)
 * 工具瀏覽 / 修改 / 新增 / AI 生成 UI
 *
 * Depends on: openModal() / closeModal() from app.js
 * API: GET /api/agent/tools · PATCH /api/agent/tool/{name}
 *      POST /api/agent/tool · DELETE /api/agent/tool/{name}
 *      POST /api/agent/tool/design · POST /api/agent/tool/install
 *      POST /api/agent/tool/reload
 */

(function () {
  'use strict';

  // ── State ──────────────────────────────────────────────────────
  let _allTools = [];          // full list from API
  let _filterCat = '';         // active category filter
  let _editingName = null;     // tool being edited (null = none)

  // ── Category → CSS suffix mapping ─────────────────────────────
  const _CAT_CLASS = {
    screen: 'screen', mouse: 'mouse', keyboard: 'keyboard',
    file: 'file', state: 'state', clipboard: 'clipboard',
    nav: 'nav', wait: 'wait', misc: 'misc',
  };
  function _catClass(cat) { return 'at-cat-' + (_CAT_CLASS[cat] || 'misc'); }

  // ── Arg count helper ──────────────────────────────────────────
  function _argCount(tool) {
    const props = (tool.args_schema && tool.args_schema.properties) || {};
    const n = Object.keys(props).length;
    if (n === 0) return '無參數';
    const names = Object.keys(props).slice(0, 3).join(', ');
    return n + ' arg' + (n > 1 ? 's' : '') + ': ' + names + (n > 3 ? '…' : '');
  }

  // ── Render card grid ──────────────────────────────────────────
  function _renderGrid() {
    const grid = document.getElementById('at-grid');
    if (!grid) return;

    const tools = _filterCat
      ? _allTools.filter(t => t.category === _filterCat)
      : _allTools;

    if (tools.length === 0) {
      grid.innerHTML = '<div class="at-loading">呢個類別冇工具</div>';
      return;
    }

    grid.innerHTML = tools.map(t => {
      const catCls = t.custom ? 'at-cat-custom' : _catClass(t.category);
      const visualBadge = t.needs_visual
        ? '<span class="at-visual-badge">👁 visual</span>' : '';
      const customBadge = t.custom
        ? '<span class="at-custom-badge">✦ 自定義</span>' : '';
      const escapedName = _esc(t.name);
      const escapedDesc = _esc(t.description);

      return `<div class="at-card" data-tool="${escapedName}">
        <div class="at-card-header">
          <span class="at-cat-badge ${catCls}">${_esc(t.category)}</span>
          ${visualBadge}${customBadge}
        </div>
        <div class="at-card-name">${escapedName}</div>
        <div class="at-card-desc" title="${escapedDesc}">${escapedDesc}</div>
        <div class="at-card-footer">
          <span class="at-card-args">${_esc(_argCount(t))}</span>
          <button class="at-card-edit-btn" data-action="edit" data-tool="${escapedName}">✏ 修改</button>
          <button class="at-card-del-btn"  data-action="del"  data-tool="${escapedName}">🗑</button>
        </div>
      </div>`;
    }).join('');

    // Wire card buttons
    grid.querySelectorAll('[data-action="edit"]').forEach(btn => {
      btn.addEventListener('click', () => _openEdit(btn.dataset.tool));
    });
    grid.querySelectorAll('[data-action="del"]').forEach(btn => {
      btn.addEventListener('click', () => _deleteTool(btn.dataset.tool));
    });
  }

  // ── HTML escape ───────────────────────────────────────────────
  function _esc(s) {
    return String(s || '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // ── Load tools from API ───────────────────────────────────────
  async function _loadTools() {
    const grid = document.getElementById('at-grid');
    if (grid) grid.innerHTML = '<div class="at-loading">載入工具⋯</div>';
    try {
      const res = await fetch('/api/agent/tools');
      const data = await res.json();
      _allTools = data.tools || [];
      // Update count badge
      const badge = document.getElementById('at-count');
      if (badge) badge.textContent = _allTools.length;
      _renderGrid();
    } catch (e) {
      if (grid) grid.innerHTML = '<div class="at-loading" style="color:#f88">載入失敗: ' + _esc(String(e)) + '</div>';
    }
  }

  // ── Status helper ─────────────────────────────────────────────
  function _setStatus(id, msg, isOk) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = msg;
    el.className = 'at-form-status ' + (isOk ? 'ok' : 'err');
    if (isOk) setTimeout(() => { if (el.textContent === msg) el.textContent = ''; }, 2500);
  }

  // ── Edit panel ────────────────────────────────────────────────
  function _openEdit(name) {
    const tool = _allTools.find(t => t.name === name);
    if (!tool) return;
    _editingName = name;

    const panel = document.getElementById('at-edit-panel');
    const label = document.getElementById('at-edit-name-label');
    const desc  = document.getElementById('at-edit-desc');
    const cat   = document.getElementById('at-edit-category');
    const vis   = document.getElementById('at-edit-visual');

    if (label) label.textContent = name;
    if (desc)  desc.value = tool.description || '';
    if (cat)   cat.value  = tool.category || 'misc';
    if (vis)   vis.checked = !!tool.needs_visual;

    _setStatus('at-edit-status', '', true);
    if (panel) panel.classList.remove('hidden');
    if (desc) desc.focus();

    // Scroll edit panel into view
    setTimeout(() => { if (panel) panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }, 50);
  }

  function _closeEdit() {
    _editingName = null;
    const panel = document.getElementById('at-edit-panel');
    if (panel) panel.classList.add('hidden');
  }

  async function _saveEdit() {
    if (!_editingName) return;
    const desc = document.getElementById('at-edit-desc');
    const cat  = document.getElementById('at-edit-category');
    const vis  = document.getElementById('at-edit-visual');
    _setStatus('at-edit-status', '儲存中⋯', true);
    try {
      const res = await fetch('/api/agent/tool/' + encodeURIComponent(_editingName), {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          description: desc ? desc.value : undefined,
          category: cat ? cat.value : undefined,
          needs_visual: vis ? vis.checked : undefined,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        _setStatus('at-edit-status', '錯誤: ' + (err.detail || res.statusText), false);
        return;
      }
      _setStatus('at-edit-status', '✓ 已儲存', true);
      _closeEdit();
      await _loadTools();
    } catch (e) {
      _setStatus('at-edit-status', '錯誤: ' + e.message, false);
    }
  }

  // ── Delete / disable ──────────────────────────────────────────
  async function _deleteTool(name) {
    const tool = _allTools.find(t => t.name === name);
    if (!tool) return;
    const action = tool.custom ? '永久刪除' : '停用';
    if (!confirm(`確定要${action}工具「${name}」？`)) return;
    try {
      const res = await fetch('/api/agent/tool/' + encodeURIComponent(name), { method: 'DELETE' });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        alert('錯誤: ' + (err.detail || res.statusText));
        return;
      }
      if (_editingName === name) _closeEdit();
      await _loadTools();
    } catch (e) {
      alert('錯誤: ' + e.message);
    }
  }

  // ── Add tool form ─────────────────────────────────────────────
  function _openAddForm() {
    const form = document.getElementById('at-add-form');
    if (form) form.classList.remove('hidden');
    const inp = document.getElementById('at-new-name');
    if (inp) { inp.value = ''; inp.focus(); }
    const desc = document.getElementById('at-new-desc');
    const args = document.getElementById('at-new-args');
    if (desc) desc.value = '';
    if (args) args.value = '';
    document.getElementById('at-new-category') && (document.getElementById('at-new-category').value = 'misc');
    document.getElementById('at-new-visual') && (document.getElementById('at-new-visual').checked = false);
    _setStatus('at-new-status', '', true);
  }

  function _closeAddForm() {
    const form = document.getElementById('at-add-form');
    if (form) form.classList.add('hidden');
  }

  async function _submitAdd() {
    const name = (document.getElementById('at-new-name')?.value || '').trim();
    const desc = (document.getElementById('at-new-desc')?.value || '').trim();
    const cat  = document.getElementById('at-new-category')?.value || 'misc';
    const vis  = document.getElementById('at-new-visual')?.checked || false;
    const argsRaw = (document.getElementById('at-new-args')?.value || '').trim();

    if (!name) { _setStatus('at-new-status', '⚠ 請填寫工具名稱', false); return; }
    if (!desc) { _setStatus('at-new-status', '⚠ 請填寫描述', false); return; }

    let argsSchema = null;
    if (argsRaw) {
      try { argsSchema = JSON.parse(argsRaw); }
      catch (e) { _setStatus('at-new-status', 'Args JSON 格式錯誤: ' + e.message, false); return; }
    }

    _setStatus('at-new-status', '新增中⋯', true);
    try {
      const res = await fetch('/api/agent/tool', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, description: desc, category: cat, needs_visual: vis, args_schema: argsSchema }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        _setStatus('at-new-status', '錯誤: ' + (err.detail || res.statusText), false);
        return;
      }
      _setStatus('at-new-status', '✓ 工具已登記', true);
      setTimeout(_closeAddForm, 1200);
      await _loadTools();
      // Switch filter to custom-friendly (all)
      _filterCat = '';
      document.querySelectorAll('.at-filter-pill').forEach(p => {
        p.classList.toggle('active', p.dataset.cat === '');
      });
    } catch (e) {
      _setStatus('at-new-status', '錯誤: ' + e.message, false);
    }
  }

  // ── Wire up everything ────────────────────────────────────────
  function _init() {
    // Open modal button
    const openBtn = document.getElementById('agent-tools-btn');
    if (openBtn) {
      openBtn.addEventListener('click', () => {
        if (typeof openModal === 'function') openModal('agent-tools-modal');
        _closeEdit();
        _closeAddForm();
        _filterCat = '';
        document.querySelectorAll('.at-filter-pill').forEach(p =>
          p.classList.toggle('active', p.dataset.cat === ''));
        _loadTools();
      });
    }

    // Modal close (shared handler in app.js handles .tool-modal-close — add reload-safety)
    const modal = document.getElementById('agent-tools-modal');
    if (modal) {
      modal.addEventListener('click', e => {
        if (e.target === modal) {
          if (typeof closeModal === 'function') closeModal('agent-tools-modal');
        }
      });
    }

    // Filter pills
    document.querySelectorAll('.at-filter-pill').forEach(pill => {
      pill.addEventListener('click', () => {
        _filterCat = pill.dataset.cat;
        document.querySelectorAll('.at-filter-pill').forEach(p =>
          p.classList.toggle('active', p === pill));
        _renderGrid();
      });
    });

    // Add tool form
    const addBtn = document.getElementById('at-add-btn');
    if (addBtn) addBtn.addEventListener('click', () => {
      const form = document.getElementById('at-add-form');
      if (form && !form.classList.contains('hidden')) _closeAddForm();
      else _openAddForm();
    });

    const newSave   = document.getElementById('at-new-save');
    const newCancel = document.getElementById('at-new-cancel');
    if (newSave)   newSave.addEventListener('click', _submitAdd);
    if (newCancel) newCancel.addEventListener('click', _closeAddForm);

    // Edit panel
    const editSave   = document.getElementById('at-edit-save');
    const editCancel = document.getElementById('at-edit-cancel');
    if (editSave)   editSave.addEventListener('click', _saveEdit);
    if (editCancel) editCancel.addEventListener('click', _closeEdit);

    // AI Designer
    const aiBtn = document.getElementById('at-ai-design-btn');
    if (aiBtn) aiBtn.addEventListener('click', () => {
      const panel = document.getElementById('at-ai-panel');
      if (panel && !panel.classList.contains('hidden')) _closeAiPanel();
      else _openAiPanel();
    });

    const aiGo = document.getElementById('at-ai-go');
    if (aiGo) aiGo.addEventListener('click', _runDesign);

    const aiCancel = document.getElementById('at-ai-cancel');
    if (aiCancel) aiCancel.addEventListener('click', _closeAiPanel);

    const aiInstall = document.getElementById('at-ai-install');
    if (aiInstall) aiInstall.addEventListener('click', _installDesigned);

    const aiDiscard = document.getElementById('at-ai-discard');
    if (aiDiscard) aiDiscard.addEventListener('click', _discardDraft);

    // Reload button
    const reloadBtn = document.getElementById('at-reload-btn');
    if (reloadBtn) reloadBtn.addEventListener('click', async () => {
      reloadBtn.disabled = true;
      try {
        const res = await fetch('/api/agent/tool/reload', { method: 'POST' });
        const d = await res.json();
        await _loadTools();
      } finally { reloadBtn.disabled = false; }
    });
  }

  // ── AI Designer ────────────────────────────────────────────────
  let _aiDraft = null;  // last generated draft

  function _openAiPanel() {
    const panel = document.getElementById('at-ai-panel');
    if (panel) panel.classList.remove('hidden');
    const inp = document.getElementById('at-ai-intent');
    if (inp) inp.focus();
    _setStatus('at-ai-status', '', true);
    document.getElementById('at-ai-preview')?.classList.add('hidden');
    document.getElementById('at-ai-preview-actions')?.classList.add('hidden');
  }

  function _closeAiPanel() {
    const panel = document.getElementById('at-ai-panel');
    if (panel) panel.classList.add('hidden');
    _aiDraft = null;
  }

  async function _runDesign() {
    const intent = (document.getElementById('at-ai-intent')?.value || '').trim();
    if (!intent) { _setStatus('at-ai-status', '⚠ 請描述工具用途', false); return; }

    const goBtn = document.getElementById('at-ai-go');
    if (goBtn) goBtn.disabled = true;
    _setStatus('at-ai-status', '🤖 AI 生成中⋯ (需要幾秒)', true);
    document.getElementById('at-ai-preview')?.classList.add('hidden');
    document.getElementById('at-ai-preview-actions')?.classList.add('hidden');
    _aiDraft = null;

    try {
      const res = await fetch('/api/agent/tool/design', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ intent }),
      });
      const data = await res.json();
      if (!res.ok || !data.draft) {
        _setStatus('at-ai-status', '錯誤: ' + (data.detail || JSON.stringify(data)), false);
        return;
      }
      _aiDraft = data.draft;
      _renderDraft(data.draft);
      _setStatus('at-ai-status', '✓ 已生成草案 — 檢查後點「安裝工具」', true);
    } catch (e) {
      _setStatus('at-ai-status', '錯誤: ' + e.message, false);
    } finally {
      if (goBtn) goBtn.disabled = false;
    }
  }

  function _renderDraft(draft) {
    const preview = document.getElementById('at-ai-preview');
    if (!preview) return;

    const warnHtml = draft.syntax_warning
      ? `<div class="at-ai-warn">⚠ ${_esc(draft.syntax_warning)}</div>` : '';

    const argsHtml = (draft.args || []).map(a =>
      `<tr><td class="at-ai-td-mono">${_esc(a.name)}</td>
           <td>${_esc(a.type)}</td>
           <td>${a.required ? '✓' : '—'}</td>
           <td>${_esc(a.description || '')}</td></tr>`
    ).join('');

    preview.innerHTML = `
      <div class="at-ai-preview-inner">
        ${warnHtml}
        <div class="at-ai-meta-row">
          <span class="at-cat-badge ${_catClass(draft.category || 'misc')}">${_esc(draft.category || 'misc')}</span>
          ${draft.needs_visual ? '<span class="at-visual-badge">👁 visual</span>' : ''}
          <span class="at-ai-name">${_esc(draft.name || '')}</span>
        </div>
        <div class="at-ai-desc">${_esc(draft.description || '')}</div>
        ${argsHtml ? `<table class="at-ai-args-table">
          <thead><tr><th>Arg</th><th>Type</th><th>Required</th><th>Description</th></tr></thead>
          <tbody>${argsHtml}</tbody></table>` : '<div class="at-ai-no-args">無參數</div>'}
        <div class="at-ai-code-label">Python 實作</div>
        <textarea id="at-ai-code-editor" class="at-textarea at-textarea-code at-ai-code-editor"
          spellcheck="false" rows="14">${_esc(draft.python_code || '')}</textarea>
        ${draft.explanation ? `<div class="at-ai-explanation">ℹ ${_esc(draft.explanation)}</div>` : ''}
      </div>`;

    preview.classList.remove('hidden');
    document.getElementById('at-ai-preview-actions')?.classList.remove('hidden');
  }

  function _discardDraft() {
    _aiDraft = null;
    document.getElementById('at-ai-preview')?.classList.add('hidden');
    document.getElementById('at-ai-preview-actions')?.classList.add('hidden');
    _setStatus('at-ai-status', '', true);
  }

  async function _installDesigned() {
    if (!_aiDraft) return;
    // Read possibly-edited code from textarea
    const codeEl = document.getElementById('at-ai-code-editor');
    const code = codeEl ? codeEl.value : (_aiDraft.python_code || '');

    const installBtn = document.getElementById('at-ai-install');
    if (installBtn) installBtn.disabled = true;
    _setStatus('at-ai-status', '安裝中⋯', true);

    try {
      const res = await fetch('/api/agent/tool/install', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: _aiDraft.name,
          description: _aiDraft.description,
          category: _aiDraft.category || 'misc',
          needs_visual: !!_aiDraft.needs_visual,
          args: _aiDraft.args || [],
          python_code: code,
          explanation: _aiDraft.explanation || '',
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        _setStatus('at-ai-status', '安裝失敗: ' + (data.detail || JSON.stringify(data)), false);
        return;
      }
      _setStatus('at-ai-status', `✓ 工具「${_esc(data.name)}」已安裝並熱載入`, true);
      _aiDraft = null;
      document.getElementById('at-ai-preview')?.classList.add('hidden');
      document.getElementById('at-ai-preview-actions')?.classList.add('hidden');
      document.getElementById('at-ai-intent') && (document.getElementById('at-ai-intent').value = '');
      await _loadTools();
    } catch (e) {
      _setStatus('at-ai-status', '錯誤: ' + e.message, false);
    } finally {
      if (installBtn) installBtn.disabled = false;
    }
  }

  // Run after DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _init);
  } else {
    _init();
  }

})();
