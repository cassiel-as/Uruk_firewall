(function () {
  'use strict';

  const state = {
    payload: null,
    events: [],
    links: [],
    cutoff: 0,
    selectedId: '',
    search: '',
    layers: { historical: true, news: true, projected: true, links: true },
    miniMap: null,
    atlasMap: null,
    miniData: null,
    atlasData: null,
    playTimer: null,
    tileErrors: 0,
  };

  const qs = id => document.getElementById(id);
  const escapeHtmlSafe = value => String(value == null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');

  function eventLayer(event) {
    if (event.projected || event.temporal_state === 'projected') return 'projected';
    if (event.type === 'news_observation' || event.temporal_state === 'news') return 'news';
    return 'historical';
  }

  function colorFor(event) {
    if (typeof window.worldGeoColorForType === 'function') return window.worldGeoColorForType(event.type);
    if (eventLayer(event) === 'news') return '#2787d8';
    if (eventLayer(event) === 'projected') return '#111827';
    return '#e35d3f';
  }

  function validCoordinate(event) {
    return Number.isFinite(Number(event.lat)) && Number.isFinite(Number(event.lon));
  }

  function searchMatches(event) {
    if (!state.search) return true;
    const haystack = [event.title, event.location, event.type, event.summary, ...(event.tags || [])].join(' ').toLowerCase();
    return haystack.includes(state.search);
  }

  function visibleEvents() {
    return state.events.filter((event, index) => (
      index <= state.cutoff
      && state.layers[eventLayer(event)]
      && searchMatches(event)
      && validCoordinate(event)
    ));
  }

  function visibleLinks(events) {
    if (!state.layers.links) return [];
    const ids = new Set(events.map(event => event.id));
    return state.links.filter(link => ids.has(link.source) && ids.has(link.target));
  }

  function tileLayer() {
    const layer = window.L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap contributors</a>',
      crossOrigin: true,
    });
    layer.on('tileerror', () => {
      state.tileErrors += 1;
      if (state.tileErrors === 1) setMapStatus('Base tiles unavailable; the coordinate and causal overlays remain active.');
    });
    return layer;
  }

  function makeMap(id, options) {
    if (!window.L || !qs(id)) return null;
    const map = window.L.map(id, {
      zoomControl: options.zoomControl,
      attributionControl: true,
      worldCopyJump: true,
      preferCanvas: true,
      minZoom: 1,
      maxBounds: [[-85, -360], [85, 360]],
    }).setView([24, 10], 2);
    tileLayer().addTo(map);
    if (options.scale) window.L.control.scale({ imperial: false, position: 'bottomleft' }).addTo(map);
    return map;
  }

  function ensureMiniMap() {
    if (!state.miniMap) state.miniMap = makeMap('world-geo-map', { zoomControl: true, scale: false });
    return state.miniMap;
  }

  function ensureAtlasMap() {
    if (!state.atlasMap) state.atlasMap = makeMap('world-atlas-map', { zoomControl: true, scale: true });
    return state.atlasMap;
  }

  function clearDataLayer(map, layer) {
    if (map && layer) map.removeLayer(layer);
  }

  function projectedIcon(event) {
    const color = colorFor(event);
    return window.L.divIcon({
      className: 'world-projection-icon-wrap',
      html: `<span class="world-projection-marker" style="--marker-color:${escapeHtmlSafe(color)}"></span>`,
      iconSize: [18, 18],
      iconAnchor: [9, 9],
    });
  }

  function popupHtml(event) {
    const stateLabel = eventLayer(event);
    return `
      <div class="world-atlas-popup-title">${escapeHtmlSafe(event.title || event.id)}</div>
      <div class="world-atlas-popup-meta">${escapeHtmlSafe(event.date || '')} · ${escapeHtmlSafe(event.location || '')}</div>
      <div class="world-atlas-popup-body">${escapeHtmlSafe(event.summary || '')}</div>
      <div class="world-atlas-popup-meta">${stateLabel} · confidence ${Math.round((Number(event.confidence) || 0) * 100)}%</div>
    `;
  }

  function markerFor(event, compact) {
    const latlng = [Number(event.lat), Number(event.lon)];
    let marker;
    if (eventLayer(event) === 'projected') {
      marker = window.L.marker(latlng, { icon: projectedIcon(event), riseOnHover: true });
    } else {
      marker = window.L.circleMarker(latlng, {
        radius: compact ? 5 : Math.max(5, Math.min(9, 4 + (Number(event.confidence) || 0.5) * 5)),
        color: '#ffffff',
        weight: 1.2,
        opacity: 0.9,
        fillColor: colorFor(event),
        fillOpacity: 0.9,
      });
    }
    marker.bindPopup(popupHtml(event), { maxWidth: 300 });
    marker.bindTooltip(event.title || event.id, { direction: 'top', opacity: 0.92 });
    marker.on('click', () => selectEvent(event.id, { pan: false }));
    return marker;
  }

  function linkLatLngs(source, target) {
    const sourceLon = Number(source.lon);
    let targetLon = Number(target.lon);
    if (Math.abs(targetLon - sourceLon) > 180) targetLon += targetLon > sourceLon ? -360 : 360;
    return [[Number(source.lat), sourceLon], [Number(target.lat), targetLon]];
  }

  function linkStyle(link) {
    const evidence = link.evidence_type || 'curated';
    if (evidence === 'model_projection') return { color: '#ffffff', dashArray: '2 7', weight: 1.6, opacity: 0.76 };
    if (evidence === 'inferred_tag_overlap') return { color: '#687b94', dashArray: '6 6', weight: 1.2, opacity: 0.62 };
    return { color: '#e25f43', weight: 1.7, opacity: Math.max(0.35, Number(link.weight) || 0.5) };
  }

  function buildDataLayer(map, compact) {
    const events = visibleEvents();
    const links = visibleLinks(events);
    const byId = new Map(events.map(event => [event.id, event]));
    const group = window.L.layerGroup();
    links.forEach(link => {
      const source = byId.get(link.source);
      const target = byId.get(link.target);
      if (!source || !target) return;
      const line = window.L.polyline(linkLatLngs(source, target), linkStyle(link));
      line.bindTooltip(`${link.source_title || source.title} → ${link.target_title || target.title}<br>${escapeHtmlSafe(link.explanation || link.kind)}`);
      group.addLayer(line);
    });
    events.forEach(event => group.addLayer(markerFor(event, compact)));
    group.addTo(map);
    return { group, events, links };
  }

  function fitMap(map, events, maxZoom) {
    if (!map || !events.length) return;
    const bounds = window.L.latLngBounds(events.map(event => [Number(event.lat), Number(event.lon)]));
    if (events.length === 1) map.setView(bounds.getCenter(), Math.min(maxZoom, 6));
    else map.fitBounds(bounds, { padding: [24, 24], maxZoom });
  }

  function renderMaps(options) {
    if (!state.payload || !window.L) return false;
    const mini = ensureMiniMap();
    const atlas = ensureAtlasMap();
    if (!mini || !atlas) return false;
    clearDataLayer(mini, state.miniData && state.miniData.group);
    clearDataLayer(atlas, state.atlasData && state.atlasData.group);
    state.miniData = buildDataLayer(mini, true);
    state.atlasData = buildDataLayer(atlas, false);
    if (options && options.fit) {
      fitMap(mini, state.miniData.events, 5);
      if (qs('world-atlas-dialog')?.open && qs('world-atlas-map')?.clientWidth > 100) {
        fitMap(atlas, state.atlasData.events, 7);
      }
    }
    updateMapStatus(state.atlasData.events, state.atlasData.links);
    window.setTimeout(() => {
      mini.invalidateSize(false);
      atlas.invalidateSize(false);
      if (options && options.fit && qs('world-atlas-dialog')?.open) {
        fitMap(atlas, state.atlasData.events, 7);
      }
    }, 80);
    return true;
  }

  function updateMapStatus(events, links) {
    if (state.tileErrors) return;
    const projected = events.filter(event => eventLayer(event) === 'projected').length;
    setMapStatus(`${events.length} visible coordinates · ${links.length} visible links · ${projected} projected`);
  }

  function setMapStatus(text) {
    const el = qs('world-atlas-map-status');
    if (el) el.textContent = text;
  }

  function syncRangeControls() {
    const max = Math.max(0, state.events.length - 1);
    const value = Math.max(0, Math.min(max, state.cutoff));
    state.cutoff = value;
    ['world-time-range', 'world-atlas-time-range'].forEach(id => {
      const input = qs(id);
      if (!input) return;
      input.max = String(max);
      input.value = String(value);
      input.disabled = state.events.length === 0;
    });
    const current = state.events[value];
    const currentDate = current ? current.date : '--';
    if (qs('world-time-label')) qs('world-time-label').textContent = currentDate;
    if (qs('world-atlas-date-current')) qs('world-atlas-date-current').textContent = currentDate;
    if (qs('world-atlas-date-start')) qs('world-atlas-date-start').textContent = state.events[0]?.date || '--';
    if (qs('world-atlas-date-end')) qs('world-atlas-date-end').textContent = state.events[max]?.date || '--';
  }

  function setCutoff(value) {
    state.cutoff = Math.max(0, Math.min(state.events.length - 1, Number(value) || 0));
    syncRangeControls();
    renderMaps({ fit: false });
    renderTimeline();
  }

  function stopPlayback() {
    if (state.playTimer) window.clearInterval(state.playTimer);
    state.playTimer = null;
    ['world-time-play', 'world-atlas-play'].forEach(id => {
      const button = qs(id);
      if (button) button.textContent = 'Play';
    });
  }

  function togglePlayback() {
    if (state.playTimer) {
      stopPlayback();
      return;
    }
    if (!state.events.length) return;
    if (state.cutoff >= state.events.length - 1) setCutoff(0);
    ['world-time-play', 'world-atlas-play'].forEach(id => {
      const button = qs(id);
      if (button) button.textContent = 'Pause';
    });
    state.playTimer = window.setInterval(() => {
      if (state.cutoff >= state.events.length - 1) {
        stopPlayback();
        return;
      }
      setCutoff(state.cutoff + 1);
    }, 750);
  }

  function renderTimeline() {
    const host = qs('world-atlas-timeline');
    if (!host) return;
    host.innerHTML = state.events.map((event, index) => {
      const visible = index <= state.cutoff && state.layers[eventLayer(event)] && searchMatches(event);
      return `
        <button class="world-atlas-timeline-item ${event.id === state.selectedId ? 'active' : ''} ${visible ? '' : 'filtered'}" type="button" data-event-id="${escapeHtmlSafe(event.id)}">
          <span class="world-atlas-timeline-date">${escapeHtmlSafe(event.date || '')}</span>
          <span class="world-atlas-timeline-dot" style="background:${escapeHtmlSafe(colorFor(event))}"></span>
          <span><span class="world-atlas-timeline-title">${escapeHtmlSafe(event.title || event.id)}</span><span class="world-atlas-timeline-place">${escapeHtmlSafe(event.location || '')}</span></span>
        </button>
      `;
    }).join('') || '<div class="vessel-empty">No events.</div>';
    host.querySelectorAll('[data-event-id]').forEach(button => {
      button.addEventListener('click', () => selectEvent(button.dataset.eventId, { pan: true }));
    });
  }

  function renderEventDetail() {
    const host = qs('world-atlas-event-detail');
    if (!host) return;
    const event = state.events.find(item => item.id === state.selectedId);
    if (!event) {
      host.textContent = 'Select a point or timeline event.';
      return;
    }
    const connections = state.links.filter(link => link.source === event.id || link.target === event.id);
    const connectionHtml = connections.slice(0, 8).map(link => {
      const outgoing = link.source === event.id;
      const other = outgoing ? link.target_title : link.source_title;
      return `<div class="world-atlas-link"><strong>${outgoing ? 'To' : 'From'}: ${escapeHtmlSafe(other || '')}</strong><br>${escapeHtmlSafe(link.explanation || link.kind)}<br>${Number(link.distance_km || 0).toLocaleString()} km · ${link.time_gap_days == null ? 'time n/a' : `${Number(link.time_gap_days).toLocaleString()} days`}</div>`;
    }).join('');
    host.innerHTML = `
      <div class="world-atlas-event-title">${escapeHtmlSafe(event.title || event.id)}</div>
      <div class="world-atlas-event-meta">${escapeHtmlSafe(event.date || '')} · ${escapeHtmlSafe(event.location || '')}<br>${Number(event.lat).toFixed(4)}, ${Number(event.lon).toFixed(4)} · ${escapeHtmlSafe(event.temporal_state || eventLayer(event))} · confidence ${Math.round((Number(event.confidence) || 0) * 100)}%</div>
      <div>${escapeHtmlSafe(event.summary || '')}</div>
      <div class="world-atlas-event-tags">${(event.tags || []).map(tag => `<span class="world-atlas-tag">${escapeHtmlSafe(tag)}</span>`).join('')}</div>
      ${event.source_ref ? `<div class="world-atlas-link"><strong>Source</strong><br>${escapeHtmlSafe(event.source_ref)}</div>` : ''}
      ${connectionHtml || '<div class="world-atlas-link">No visible causal connection.</div>'}
    `;
  }

  function renderCorrection() {
    const host = qs('world-atlas-correction');
    if (!host) return;
    const correction = state.payload?.forecast_correction || {};
    const baseline = correction.baseline || {};
    const corrected = correction.corrected || {};
    const deltas = correction.scenario_deltas || {};
    host.innerHTML = `
      <div class="world-atlas-correction-grid">
        <div class="world-atlas-correction-state"><span>Baseline</span><strong>${escapeHtmlSafe(baseline.primary_scenario || 'none')}</strong></div>
        <div class="world-atlas-correction-arrow">→</div>
        <div class="world-atlas-correction-state"><span>News corrected</span><strong>${escapeHtmlSafe(corrected.primary_scenario || 'none')}</strong></div>
      </div>
      ${Object.entries(deltas).map(([name, value]) => {
        const number = Number(value) || 0;
        return `<div class="world-atlas-delta-row"><span>${escapeHtmlSafe(name)}</span><strong class="${number >= 0 ? 'positive' : 'negative'}">${number >= 0 ? '+' : ''}${number.toFixed(4)}</strong></div>`;
      }).join('') || '<div class="vessel-empty">No scenario shift.</div>'}
    `;
  }

  function renderRevisions() {
    const host = qs('world-atlas-revision-list');
    if (!host) return;
    const revisions = Array.isArray(state.payload?.revision_history) ? state.payload.revision_history.slice().reverse() : [];
    host.innerHTML = revisions.map(revision => `
      <div class="world-atlas-revision-item">
        <strong>${escapeHtmlSafe((revision.corrected || {}).primary_scenario || 'none')}</strong> · ${escapeHtmlSafe(revision.correction_strength || 'weak')}<br>
        ${escapeHtmlSafe(revision.generated_at || '')} · ${revision.news_summary?.source_count || 0} sources · max shift ${Number(revision.max_absolute_shift || 0).toFixed(4)}
      </div>
    `).join('') || '<div class="vessel-empty">No saved revision yet.</div>';
  }

  function selectEvent(id, options) {
    const event = state.events.find(item => item.id === id);
    if (!event) return;
    state.selectedId = id;
    renderEventDetail();
    renderTimeline();
    document.querySelectorAll(`.world-event-card[data-event-id="${window.CSS?.escape ? CSS.escape(id) : id}"]`).forEach(card => card.classList.add('selected'));
    document.querySelectorAll('.world-event-card').forEach(card => {
      if (card.dataset.eventId !== id) card.classList.remove('selected');
    });
    if (options?.pan !== false && validCoordinate(event)) {
      const latlng = [Number(event.lat), Number(event.lon)];
      state.miniMap?.setView(latlng, Math.max(state.miniMap.getZoom(), 4));
      state.atlasMap?.setView(latlng, Math.max(state.atlasMap.getZoom(), 5));
    }
  }

  function render(payload) {
    if (!payload || !Array.isArray(payload.events)) return false;
    state.payload = payload;
    state.events = payload.events.slice().sort((a, b) => String(a.date || '').localeCompare(String(b.date || '')));
    state.links = Array.isArray(payload.links) ? payload.links.slice() : [];
    state.cutoff = Math.max(0, state.events.length - 1);
    state.selectedId = state.events[state.events.length - 1]?.id || '';
    state.tileErrors = 0;
    showGeo();
    syncRangeControls();
    renderTimeline();
    renderEventDetail();
    renderCorrection();
    renderRevisions();
    const graph = payload.graph || {};
    const summary = qs('world-atlas-summary');
    if (summary) summary.textContent = `${graph.event_count ?? state.events.length} coordinates · ${graph.link_count ?? state.links.length} links · ${payload.temporal_bounds?.start || '--'} to ${payload.temporal_bounds?.end || '--'}`;
    return renderMaps({ fit: true });
  }

  function showGeo() {
    qs('world-canvas')?.classList.add('hidden');
    qs('world-geo-map')?.classList.remove('hidden');
    qs('world-time-controls')?.classList.remove('hidden');
  }

  function showSimulation() {
    stopPlayback();
    qs('world-geo-map')?.classList.add('hidden');
    qs('world-time-controls')?.classList.add('hidden');
    qs('world-canvas')?.classList.remove('hidden');
  }

  function open() {
    const dialog = qs('world-atlas-dialog');
    if (!dialog || !state.payload) return false;
    if (!dialog.open) dialog.showModal();
    renderMaps({ fit: true });
    renderTimeline();
    renderEventDetail();
    return true;
  }

  function close() {
    stopPlayback();
    const dialog = qs('world-atlas-dialog');
    if (dialog?.open) dialog.close();
  }

  function setup() {
    ['world-time-range', 'world-atlas-time-range'].forEach(id => {
      qs(id)?.addEventListener('input', event => setCutoff(event.target.value));
    });
    ['world-time-play', 'world-atlas-play'].forEach(id => qs(id)?.addEventListener('click', togglePlayback));
    qs('world-atlas-close')?.addEventListener('click', close);
    qs('world-atlas-fit')?.addEventListener('click', () => {
      fitMap(state.miniMap, state.miniData?.events || [], 5);
      fitMap(state.atlasMap, state.atlasData?.events || [], 7);
    });
    qs('world-atlas-dialog')?.addEventListener('cancel', event => {
      event.preventDefault();
      close();
    });
    const layerInputs = {
      'world-layer-history': 'historical',
      'world-layer-news': 'news',
      'world-layer-projected': 'projected',
      'world-layer-links': 'links',
    };
    Object.entries(layerInputs).forEach(([id, layer]) => {
      qs(id)?.addEventListener('change', event => {
        state.layers[layer] = Boolean(event.target.checked);
        renderMaps({ fit: false });
        renderTimeline();
      });
    });
    qs('world-atlas-search')?.addEventListener('input', event => {
      state.search = String(event.target.value || '').trim().toLowerCase();
      renderMaps({ fit: false });
      renderTimeline();
    });
  }

  window.WorldAtlas = {
    setup,
    render,
    open,
    close,
    selectEvent,
    showSimulation,
    hasPayload: () => Boolean(state.payload),
  };
})();
