/**
 * URUK Trinity Console — Local LLM Discovery + Direct Chat (v8.46)
 *
 * UI lives inside the Settings modal (#settings-local-llm-section)
 * + a standalone direct-chat drawer (#local-chat-drawer).
 *
 * Endpoints used:
 *   POST /api/local-llm/scan
 *   POST /api/local-llm/chat
 *   POST /api/local-llm/add-profile
 */

(function () {
  'use strict';

  // ── State ──────────────────────────────────────────────────────
  let _discovered = [];          // last scan result
  let _chatTarget = null;        // {app_name, api_base, provider, model}

  // ── Escape ────────────────────────────────────────────────────
  function esc(s) {
    return String(s || '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // ── Status helper ─────────────────────────────────────────────
  function _setLLMStatus(msg, ok) {
    const el = document.getElementById('llm-scan-status');
    if (!el) return;
    el.textContent = msg;
    el.className = 'llm-status ' + (ok ? 'ok' : 'err');
    if (ok && msg) setTimeout(() => { if (el.textContent === msg) el.textContent = ''; }, 3000);
  }

  // ── Render scan results ───────────────────────────────────────
  function _renderApps() {
    const grid = document.getElementById('llm-apps-grid');
    if (!grid) return;

    if (!_discovered.length) {
      grid.innerHTML = '<div class="llm-empty">未發現本機 LLM 應用。確認對應 app 已啟動後重試。</div>';
      return;
    }

    grid.innerHTML = _discovered.map((app, idx) => {
      const modelOpts = (app.models || []).map(m =>
        `<option value="${esc(m)}">${esc(m)}</option>`
      ).join('');
      const hasModels = app.models && app.models.length > 0;

      return `<div class="llm-app-card" data-idx="${idx}">
        <div class="llm-app-header">
          <span class="llm-app-icon">${esc(app.icon)}</span>
          <span class="llm-app-name">${esc(app.name)}</span>
          <span class="llm-app-port">:${app.port}</span>
          <span class="llm-online-dot" title="Online">●</span>
        </div>
        <div class="llm-app-base">${esc(app.api_base)}</div>
        ${hasModels
          ? `<div class="llm-model-row">
               <select class="llm-model-select" id="llm-model-${idx}">${modelOpts}</select>
               <span class="llm-model-count">${app.models.length} 個模型</span>
             </div>`
          : `<div class="llm-no-models">（無法列出模型）</div>`
        }
        <div class="llm-card-actions">
          <button class="llm-chat-btn" data-idx="${idx}" title="直接對話">💬 對話</button>
          <button class="llm-add-btn"  data-idx="${idx}" title="加入為 API Profile">＋ 加入節點</button>
          <span class="llm-card-status" id="llm-cstatus-${idx}"></span>
        </div>
      </div>`;
    }).join('');

    // Wire buttons
    grid.querySelectorAll('.llm-chat-btn').forEach(btn => {
      btn.addEventListener('click', () => _openChat(parseInt(btn.dataset.idx)));
    });
    grid.querySelectorAll('.llm-add-btn').forEach(btn => {
      btn.addEventListener('click', () => _addProfile(parseInt(btn.dataset.idx)));
    });
  }

  // ── Scan ──────────────────────────────────────────────────────
  async function _runScan() {
    const scanBtn = document.getElementById('llm-scan-btn');
    if (scanBtn) scanBtn.disabled = true;
    _setLLMStatus('掃描中⋯', true);
    const grid = document.getElementById('llm-apps-grid');
    if (grid) grid.innerHTML = '<div class="llm-empty">掃描本機端口⋯</div>';

    try {
      const res = await fetch('/api/local-llm/scan', { method: 'POST' });
      const data = await res.json();
      _discovered = data.apps || [];
      _setLLMStatus(
        _discovered.length
          ? `✓ 發現 ${_discovered.length} 個應用`
          : '未發現本機 LLM 應用',
        true,
      );
      _renderApps();
    } catch (e) {
      _setLLMStatus('掃描失敗: ' + e.message, false);
      if (grid) grid.innerHTML = '<div class="llm-empty err">掃描失敗</div>';
    } finally {
      if (scanBtn) scanBtn.disabled = false;
    }
  }

  // ── Add profile ───────────────────────────────────────────────
  async function _addProfile(idx) {
    const app = _discovered[idx];
    if (!app) return;

    const modelSel = document.getElementById('llm-model-' + idx);
    const model = modelSel ? modelSel.value : (app.models[0] || '');
    const slug = (app.name.toLowerCase().replace(/[^a-z0-9]/g, '_') + '_' + model.replace(/[^a-z0-9]/g, '_').slice(0, 20))
      .replace(/_+/g, '_').replace(/^_|_$/g, '');

    const statusEl = document.getElementById('llm-cstatus-' + idx);
    if (statusEl) statusEl.textContent = '加入中⋯';

    try {
      const res = await fetch('/api/local-llm/add-profile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          profile_name: slug,
          app_name: app.name,
          provider: app.provider,
          api_base: app.api_base,
          model: model,
          api_key_env: '',
        }),
      });
      const d = await res.json();
      if (!res.ok) {
        if (statusEl) { statusEl.textContent = '失敗: ' + (d.detail || ''); statusEl.style.color = '#f88'; }
      } else {
        if (statusEl) { statusEl.textContent = '✓ 已加入為 ' + slug; statusEl.style.color = '#5be87a'; }
        // Reload settings health if visible
        if (typeof loadSettingsHealth === 'function') loadSettingsHealth();
      }
    } catch (e) {
      if (statusEl) { statusEl.textContent = '錯誤: ' + e.message; statusEl.style.color = '#f88'; }
    }
  }

  // ── Open direct chat drawer ───────────────────────────────────
  function _openChat(idx) {
    const app = _discovered[idx];
    if (!app) return;
    const modelSel = document.getElementById('llm-model-' + idx);
    const model = modelSel ? modelSel.value : (app.models[0] || '');

    _chatTarget = { app_name: app.name, api_base: app.api_base, provider: app.provider, model };

    const drawer = document.getElementById('local-chat-drawer');
    if (!drawer) return;

    // Reset UI
    document.getElementById('lc-app-label').textContent = app.icon + ' ' + app.name + ' · ' + model;
    document.getElementById('lc-model-input').value = model;
    document.getElementById('lc-api-base').value = app.api_base;
    document.getElementById('lc-provider').value = app.provider;
    const hist = document.getElementById('lc-history');
    if (hist) hist.innerHTML = '';
    drawer.classList.remove('hidden');
    document.getElementById('lc-input')?.focus();
  }

  function _closeChat() {
    const drawer = document.getElementById('local-chat-drawer');
    if (drawer) drawer.classList.add('hidden');
    _chatTarget = null;
  }

  // ── Send direct chat message ──────────────────────────────────
  async function _sendChat() {
    const inp = document.getElementById('lc-input');
    const msg = inp ? inp.value.trim() : '';
    if (!msg) return;

    const api_base = document.getElementById('lc-api-base')?.value || _chatTarget?.api_base || '';
    const provider = document.getElementById('lc-provider')?.value || _chatTarget?.provider || 'openai';
    const model    = document.getElementById('lc-model-input')?.value || _chatTarget?.model || '';
    const system   = document.getElementById('lc-system')?.value || '你係 URUK 協議載體嘅直接回應模式，用廣東話回答。';

    if (!model) { _appendChatMsg('system', '⚠ 請填寫 model'); return; }
    if (provider !== 'anthropic' && !api_base) { _appendChatMsg('system', '⚠ 請填寫 API base'); return; }

    if (inp) inp.value = '';
    _appendChatMsg('user', msg);

    const sendBtn = document.getElementById('lc-send-btn');
    if (sendBtn) sendBtn.disabled = true;
    const thinkEl = _appendChatMsg('assistant', '⋯');

    try {
      // Route Anthropic provider to dedicated Claude endpoint
      const endpoint = provider === 'anthropic' ? '/api/claude/chat' : '/api/local-llm/chat';
      const body = provider === 'anthropic'
        ? JSON.stringify({ model, message: msg, system })
        : JSON.stringify({ api_base, provider, model, message: msg, system });

      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body,
      });
      const data = await res.json();
      if (!res.ok) {
        thinkEl.textContent = '錯誤: ' + (data.detail || res.statusText);
        thinkEl.style.color = '#f88';
      } else {
        thinkEl.textContent = data.reply || '(no reply)';
        thinkEl.style.color = '';
      }
    } catch (e) {
      thinkEl.textContent = '錯誤: ' + e.message;
      thinkEl.style.color = '#f88';
    } finally {
      if (sendBtn) sendBtn.disabled = false;
      inp?.focus();
    }
  }

  function _appendChatMsg(role, text) {
    const hist = document.getElementById('lc-history');
    if (!hist) return null;
    const el = document.createElement('div');
    el.className = 'lc-msg lc-msg-' + role;
    el.textContent = text;
    hist.appendChild(el);
    hist.scrollTop = hist.scrollHeight;
    return el;
  }

  // ── Claude Connect ─────────────────────────────────────────────
  let _claudeModels = [
    'claude-sonnet-4-6', 'claude-opus-4-6', 'claude-haiku-4-5-20251001',
    'claude-3-5-sonnet-20241022', 'claude-3-5-haiku-20241022',
  ];

  function _setClaudeUI(configured, keyTail) {
    const dot       = document.getElementById('claude-status-dot');
    const txt       = document.getElementById('claude-status-text');
    const chatBtn   = document.getElementById('claude-chat-btn');
    const disBtn    = document.getElementById('claude-disconnect-btn');
    const form      = document.getElementById('claude-connect-form');

    if (configured) {
      if (dot)   { dot.className = 'claude-dot online'; }
      if (txt)   txt.textContent = `已連接 · Key ****${keyTail}`;
      chatBtn?.classList.remove('hidden');
      disBtn?.classList.remove('hidden');
      if (form)  form.style.display = 'none';
    } else {
      if (dot)   { dot.className = 'claude-dot offline'; }
      if (txt)   txt.textContent = '未配置 API Key';
      chatBtn?.classList.add('hidden');
      disBtn?.classList.add('hidden');
      if (form)  form.style.display = '';
    }
  }

  async function _checkClaudeStatus() {
    try {
      const r = await fetch('/api/claude/status');
      const d = await r.json();
      _setClaudeUI(d.configured, d.key_tail || '');
    } catch (_) { /* server not started yet */ }
  }

  async function _connectClaude() {
    const keyInp  = document.getElementById('claude-key-input');
    const modelEl = document.getElementById('claude-model-select');
    const statusEl = document.getElementById('claude-connect-status');
    const btn     = document.getElementById('claude-connect-btn');

    const key   = keyInp ? keyInp.value.trim() : '';
    const model = modelEl ? modelEl.value : 'claude-sonnet-4-6';

    if (!key) { if (statusEl) { statusEl.textContent = '請輸入 API Key'; statusEl.className = 'claude-connect-status err'; } return; }

    if (btn) btn.disabled = true;
    if (statusEl) { statusEl.textContent = '驗證中⋯'; statusEl.className = 'claude-connect-status'; }

    try {
      const res = await fetch('/api/claude/connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: key, model }),
      });
      const d = await res.json();
      if (!res.ok) {
        if (statusEl) { statusEl.textContent = '失敗: ' + (d.detail || res.statusText); statusEl.className = 'claude-connect-status err'; }
      } else {
        if (d.models && d.models.length) {
          _claudeModels = d.models;
          // Update model selector
          if (modelEl) {
            modelEl.innerHTML = _claudeModels.map(m =>
              `<option value="${esc(m)}"${m === model ? ' selected' : ''}>${esc(m)}</option>`
            ).join('');
          }
        }
        if (statusEl) { statusEl.textContent = '✓ 已連接'; statusEl.className = 'claude-connect-status ok'; }
        if (keyInp) keyInp.value = '';
        _setClaudeUI(true, d.key_tail || '');
      }
    } catch (e) {
      if (statusEl) { statusEl.textContent = '錯誤: ' + e.message; statusEl.className = 'claude-connect-status err'; }
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function _disconnectClaude() {
    try {
      // Remove key via connect with empty — actually just clear UI; user can reconnect
      await fetch('/api/claude/connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: ' ', model: 'claude-sonnet-4-6' }),
      });
    } catch (_) {}
    _setClaudeUI(false, '');
  }

  function _openClaudeChat() {
    const modelEl = document.getElementById('claude-model-select');
    const model   = modelEl ? modelEl.value : 'claude-sonnet-4-6';

    _chatTarget = {
      app_name: 'Claude',
      api_base: 'https://api.anthropic.com',
      provider: 'anthropic',
      model,
    };

    const drawer = document.getElementById('local-chat-drawer');
    if (!drawer) return;

    document.getElementById('lc-app-label').textContent = '🤖 Claude · ' + model;
    document.getElementById('lc-model-input').value = model;
    document.getElementById('lc-api-base').value = 'https://api.anthropic.com';
    document.getElementById('lc-provider').value = 'anthropic';
    const hist = document.getElementById('lc-history');
    if (hist) hist.innerHTML = '';
    drawer.classList.remove('hidden');
    document.getElementById('lc-input')?.focus();
  }

  // ── Init ──────────────────────────────────────────────────────
  function _init() {
    // Scan button
    const scanBtn = document.getElementById('llm-scan-btn');
    if (scanBtn) scanBtn.addEventListener('click', _runScan);

    // Chat drawer close
    const closeBtn = document.getElementById('lc-close-btn');
    if (closeBtn) closeBtn.addEventListener('click', _closeChat);

    // Send message
    const sendBtn = document.getElementById('lc-send-btn');
    if (sendBtn) sendBtn.addEventListener('click', _sendChat);

    const lcInp = document.getElementById('lc-input');
    if (lcInp) {
      lcInp.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); _sendChat(); }
      });
    }

    // Clear chat
    const clearBtn = document.getElementById('lc-clear-btn');
    if (clearBtn) clearBtn.addEventListener('click', () => {
      const hist = document.getElementById('lc-history');
      if (hist) hist.innerHTML = '';
    });

    // Claude connect
    document.getElementById('claude-connect-btn')
      ?.addEventListener('click', _connectClaude);
    document.getElementById('claude-disconnect-btn')
      ?.addEventListener('click', _disconnectClaude);
    document.getElementById('claude-chat-btn')
      ?.addEventListener('click', _openClaudeChat);

    // Toggle key visibility
    const toggle = document.getElementById('claude-key-toggle');
    const keyInp = document.getElementById('claude-key-input');
    if (toggle && keyInp) {
      toggle.addEventListener('click', () => {
        keyInp.type = keyInp.type === 'password' ? 'text' : 'password';
      });
    }

    // Auto-scan when settings modal opens (light: only if section visible)
    const settingsBtn = document.getElementById('settings-btn');
    if (settingsBtn) {
      settingsBtn.addEventListener('click', () => {
        // Lazy-scan: run once per page load if not yet done
        if (!_discovered.length) setTimeout(_runScan, 400);
        // Check Claude status on first open
        _checkClaudeStatus();
      });
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', _init);
  else _init();
})();
