/**
 * URUK Trinity Console — Desktop App Controller UI (v8.47b)
 *
 * Endpoints used:
 *   GET  /api/app-control/status
 *   POST /api/app-control/install-deps
 *   POST /api/app-control/{key}/launch
 *   POST /api/app-control/{key}/send
 */

(function () {
  'use strict';

  // ── State ──────────────────────────────────────────────────────
  let _apps = [];
  let _sendTarget = null; // {key, display, icon}

  // ── Escape ────────────────────────────────────────────────────
  function esc(s) {
    return String(s || '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // ── Modal open/close ──────────────────────────────────────────
  function _openModal() {
    const modal = document.getElementById('app-control-modal');
    if (modal) modal.classList.remove('hidden');
    _loadStatus();
  }

  function _closeModal() {
    const modal = document.getElementById('app-control-modal');
    if (modal) modal.classList.add('hidden');
  }

  // ── Dep status bar ────────────────────────────────────────────
  function _renderDeps(deps) {
    const bar  = document.getElementById('ac-dep-status');
    const iBtn = document.getElementById('ac-install-deps-btn');
    if (!bar) return;

    const isWin = deps.is_windows;
    const hasPW = deps.pywinauto;
    const hasPS = deps.psutil;

    if (!isWin) {
      bar.textContent = '⚠ App 控制只支援 Windows。';
      bar.className = 'ac-dep-status warn';
      if (iBtn) iBtn.classList.add('hidden');
      return;
    }

    if (hasPW && hasPS) {
      bar.textContent = '✓ 自動化依賴已就緒 (pywinauto + psutil)';
      bar.className = 'ac-dep-status ok';
      if (iBtn) iBtn.classList.add('hidden');
    } else {
      const missing = [!hasPW && 'pywinauto', !hasPS && 'psutil'].filter(Boolean).join(', ');
      bar.textContent = `缺少依賴: ${missing}。點「安裝」後重啟 server。`;
      bar.className = 'ac-dep-status warn';
      if (iBtn) iBtn.classList.remove('hidden');
    }
  }

  // ── App cards ─────────────────────────────────────────────────
  function _renderApps() {
    const grid = document.getElementById('ac-apps-grid');
    if (!grid) return;

    if (!_apps.length) {
      grid.innerHTML = '<div class="ac-loading">無已知 App。</div>';
      return;
    }

    grid.innerHTML = _apps.map(app => {
      const dotCls  = app.running ? 'online' : 'offline';
      const dotTxt  = app.running ? '●' : '●';
      const statusTxt = app.running ? '運行中' : '未啟動';
      const launchDis = app.running || !app.launchable ? 'disabled' : '';
      const launchTip = !app.launchable ? '未安裝' : '';
      const sendDis   = app.running ? '' : 'disabled';

      return `<div class="ac-app-card" data-key="${esc(app.key)}">
        <div class="ac-app-header">
          <span class="ac-app-icon">${esc(app.icon)}</span>
          <span class="ac-app-name">${esc(app.display)}</span>
          <span class="ac-app-dot ${dotCls}" title="${statusTxt}">${dotTxt}</span>
        </div>
        <div class="ac-app-status-text">${statusTxt}</div>
        <div class="ac-app-actions">
          <button class="ac-launch-btn" data-key="${esc(app.key)}" ${launchDis} title="${launchTip}">
            ▶ 啟動
          </button>
          <button class="ac-send-open-btn" data-key="${esc(app.key)}"
                  data-display="${esc(app.display)}" data-icon="${esc(app.icon)}"
                  ${sendDis}>
            💬 發送訊息
          </button>
        </div>
      </div>`;
    }).join('');

    grid.querySelectorAll('.ac-launch-btn').forEach(btn => {
      btn.addEventListener('click', () => _launchApp(btn.dataset.key));
    });
    grid.querySelectorAll('.ac-send-open-btn').forEach(btn => {
      btn.addEventListener('click', () => _openSendPanel(btn.dataset.key, btn.dataset.display, btn.dataset.icon));
    });
  }

  // ── Load status ───────────────────────────────────────────────
  async function _loadStatus() {
    const grid = document.getElementById('ac-apps-grid');
    if (grid) grid.innerHTML = '<div class="ac-loading">掃描中⋯</div>';

    try {
      const res  = await fetch('/api/app-control/status');
      const data = await res.json();
      _apps = data.apps || [];
      _renderDeps(data.deps || {});
      _renderApps();
    } catch (e) {
      if (grid) grid.innerHTML = `<div class="ac-loading">錯誤: ${esc(e.message)}</div>`;
    }
  }

  // ── Install deps ──────────────────────────────────────────────
  async function _installDeps() {
    const btn = document.getElementById('ac-install-deps-btn');
    const bar = document.getElementById('ac-dep-status');
    if (btn) btn.disabled = true;
    if (bar) { bar.textContent = '安裝中⋯ (可能需要 30 秒)'; bar.className = 'ac-dep-status'; }
    try {
      const res = await fetch('/api/app-control/install-deps', { method: 'POST' });
      const d   = await res.json();
      if (bar) { bar.textContent = (res.ok ? '✓ ' : '✗ ') + (d.message || d.error); bar.className = 'ac-dep-status ' + (res.ok ? 'ok' : 'warn'); }
    } catch (e) {
      if (bar) { bar.textContent = '安裝失敗: ' + e.message; bar.className = 'ac-dep-status warn'; }
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  // ── Launch app ────────────────────────────────────────────────
  async function _launchApp(key) {
    const card = document.querySelector(`.ac-app-card[data-key="${key}"]`);
    const btn  = card ? card.querySelector('.ac-launch-btn') : null;
    if (btn) btn.disabled = true;

    try {
      const res = await fetch(`/api/app-control/${encodeURIComponent(key)}/launch`, { method: 'POST' });
      const d   = await res.json();
      // Refresh after a short wait for the app to start
      setTimeout(_loadStatus, 2500);
    } catch (_) {}
  }

  // ── Send panel ────────────────────────────────────────────────
  function _openSendPanel(key, display, icon) {
    _sendTarget = { key, display, icon };
    const panel = document.getElementById('ac-send-panel');
    const target = document.getElementById('ac-send-target');
    const status = document.getElementById('ac-send-status');
    const inp    = document.getElementById('ac-send-input');
    if (target) target.textContent = icon + ' ' + display;
    if (status) { status.textContent = ''; status.className = 'ac-send-status'; }
    if (inp)    inp.value = '';
    if (panel)  panel.classList.remove('hidden');
    inp?.focus();
  }

  function _closeSendPanel() {
    const panel = document.getElementById('ac-send-panel');
    if (panel) panel.classList.add('hidden');
    _sendTarget = null;
  }

  async function _sendMessage() {
    if (!_sendTarget) return;
    const inp    = document.getElementById('ac-send-input');
    const status = document.getElementById('ac-send-status');
    const btn    = document.getElementById('ac-send-btn');
    const msg    = inp ? inp.value.trim() : '';
    if (!msg) return;

    if (btn) btn.disabled = true;
    if (status) { status.textContent = '發送中⋯'; status.className = 'ac-send-status'; }

    try {
      const res = await fetch(`/api/app-control/${encodeURIComponent(_sendTarget.key)}/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: msg }),
      });
      const d = await res.json();
      if (res.ok) {
        if (status) { status.textContent = `✓ 已發送 (${d.method || 'ok'})。${_sendTarget.display} 會彈到前台。`; status.className = 'ac-send-status ok'; }
        if (inp) inp.value = '';
      } else {
        if (status) { status.textContent = '失敗: ' + (d.detail || res.statusText); status.className = 'ac-send-status err'; }
      }
    } catch (e) {
      if (status) { status.textContent = '錯誤: ' + e.message; status.className = 'ac-send-status err'; }
    } finally {
      if (btn) btn.disabled = false;
      inp?.focus();
    }
  }

  // ── Init ──────────────────────────────────────────────────────
  function _init() {
    // Toolbar button
    document.getElementById('app-control-btn')
      ?.addEventListener('click', _openModal);

    // Modal close buttons
    document.querySelectorAll('[data-modal="app-control-modal"]').forEach(btn => {
      btn.addEventListener('click', _closeModal);
    });

    // Refresh button
    document.getElementById('ac-refresh-btn')
      ?.addEventListener('click', _loadStatus);

    // Install deps button
    document.getElementById('ac-install-deps-btn')
      ?.addEventListener('click', _installDeps);

    // Send panel
    document.getElementById('ac-send-close')
      ?.addEventListener('click', _closeSendPanel);
    document.getElementById('ac-send-btn')
      ?.addEventListener('click', _sendMessage);

    const sendInp = document.getElementById('ac-send-input');
    if (sendInp) {
      sendInp.addEventListener('keydown', e => {
        if (e.key === 'Enter' && e.ctrlKey) { e.preventDefault(); _sendMessage(); }
      });
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', _init);
  else _init();
})();
