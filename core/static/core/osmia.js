/* Osmia: editing in place, pickers, the view toolbar and drag and drop.
 * Every change is sent to /api/records/<id>/, which goes through the same
 * service as the forms, so automations and validation apply. */
(function () {
  'use strict';

  // -- Basics ------------------------------------------------------------------------
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const el = (tag, attrs, ...kids) => {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === 'class') node.className = v;
      else if (k === 'text') node.textContent = v;
      else if (k === 'html') node.innerHTML = v;
      else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
      else if (v !== undefined && v !== null && v !== false) node.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat()) if (kid !== null && kid !== undefined) node.append(kid);
    return node;
  };
  const metaNode = document.getElementById('osmia-meta');
  const META = metaNode ? JSON.parse(JSON.parse(metaNode.textContent)) : { fields: {}, users: [] };
  window.OSMIA = { META };

  async function api(url, body, method) {
    const opts = { method: method || (body === undefined ? 'GET' : 'POST'), credentials: 'same-origin',
      headers: { 'X-CSRFToken': window.OSMIA_CSRF, 'Content-Type': 'application/json' } };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const res = await fetch(url, opts);
    let data = {};
    try { data = await res.json(); } catch (e) { data = { error: `The server answered ${res.status}.` }; }
    // Someone was put on a record they can't see (its access tags): share this one record with them?
    if (res.status === 409 && data.needs_share && body && !body.share && confirm(`${data.error}

Share it with them?`)) {
      return api(url, { ...body, share: true }, method);
    }
    if (!res.ok) throw Object.assign(new Error(data.error || data.message || `Error ${res.status}`), { data });
    return data;
  }
  window.OSMIA.api = api;

  // Tabs inside a block (e.g. My work: assigned, recent, starred)
  document.addEventListener('click', (e) => {
    const b = e.target.closest('.work-tabs button[data-side]');
    if (!b) return;
    const box = b.closest('.live-block, .card') || document;
    box.querySelectorAll('.work-tabs button').forEach((x) => x.classList.toggle('on', x === b));
    box.querySelectorAll('[data-pane]').forEach((p) => p.classList.toggle('hidden', p.dataset.pane !== b.dataset.side));
  });

  let toastTimer;
  function toast(text, error) {
    let t = $('.toast');
    if (!t) { t = el('div', { class: 'toast' }); document.body.append(t); }
    t.textContent = text;
    t.classList.toggle('error', !!error);
    t.style.display = 'block';
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.style.display = 'none'; }, error ? 7000 : 3500);
  }
  window.OSMIA.toast = toast;

  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private window */ } },
  };

  // Confirm before forms / buttons marked data-confirm
  document.addEventListener('submit', (e) => {
    const msg = e.target.dataset.confirm;
    if (msg && !confirm(msg)) e.preventDefault();
  }, true);
  document.addEventListener('click', (e) => {
    const b = e.target.closest('button[data-confirm]');
    if (b && !confirm(b.dataset.confirm)) { e.preventDefault(); e.stopPropagation(); }
  }, true);

  // App launcher: focus its filter when it opens; typing narrows the tiles, Enter opens the first
  const launcher = document.getElementById('launcher');
  if (launcher) {
    const filter = launcher.querySelector('.launcher-filter');
    launcher.addEventListener('toggle', () => { if (launcher.open) { filter.value = ''; filter.dispatchEvent(new Event('input')); filter.focus(); } });
    filter.addEventListener('input', () => {
      const q = filter.value.trim().toLowerCase();
      launcher.querySelectorAll('.launcher-tile, .launcher-space').forEach((t) => { t.style.display = !q || t.dataset.name.includes(q) ? '' : 'none'; });
      // a group whose apps are all left out goes too
      launcher.querySelectorAll('.launcher-group').forEach((g) => {
        g.style.display = [...g.querySelectorAll('.launcher-tile')].some((t) => t.style.display !== 'none') ? '' : 'none';
      });
    });
    filter.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { const first = [...launcher.querySelectorAll('.launcher-tile, .launcher-space')].find((t) => t.style.display !== 'none'); if (first) first.click(); }
      if (e.key === 'Escape') launcher.open = false;
    });
  }

  // Escape closes open menus (the app launcher, the user menu, ...)
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') $$('details.menu[open]').forEach((d) => { d.open = false; });
  });

  // Close <details> menus when clicking elsewhere
  document.addEventListener('click', (e) => {
    $$('details.menu[open]').forEach((d) => { if (!d.contains(e.target)) d.open = false; });
  });

  // -- Record JSON cache and applying server answers ------------------------------------
  const records = {};
  async function recordData(id) {
    if (!records[id]) records[id] = await api(`/api/records/${id}/`);
    return records[id];
  }
  function applyRecord(rec) {
    if (!rec) return;
    records[rec.id] = rec;
    $$(`.cell[data-record="${rec.id}"]`).forEach((cell) => {
      const c = rec.cells[cell.dataset.field];
      if (!c) return;
      const keep = cell.querySelector('.toggle');
      const pad = keep ? keep.previousElementSibling : null;
      cell.innerHTML = c.html;
      if (keep) { cell.prepend(keep); if (pad) cell.prepend(pad); }
      if (cell.hasAttribute('data-raw')) cell.dataset.raw = JSON.stringify(c.raw);
    });
    const title = $('#record-title');
    if (title && $('#props') && $(`#props .cell[data-record="${rec.id}"]`)) title.textContent = rec.label;
  }
  async function save(recordId, fieldId, value, cell) {
    if (cell) cell.classList.add('saving');
    try {
      const rec = await api(`/api/records/${recordId}/`, { values: { [fieldId]: value } });
      applyRecord(rec);
      if (cell) cell.classList.remove('bad');
      return rec;
    } catch (err) {
      toast(err.message, true);
      if (cell) cell.classList.add('bad');
      return null;
    } finally {
      if (cell) cell.classList.remove('saving');
    }
  }
  window.OSMIA.save = save;

  // -- Picker (records of a table) ---------------------------------------------------------
  function openPicker({ table, title, multiple, selected, onDone }) {
    let chosen = new Map((selected || []).map((s) => [s.id, s.name]));
    const list = el('div', { class: 'picker-list' });
    const input = el('input', { type: 'search', placeholder: 'Search…', style: 'width:100%;margin-bottom:8px' });
    const back = el('div', { class: 'o-modal-back' });
    const close = () => back.remove();
    const done = () => { close(); onDone([...chosen].map(([id, name]) => ({ id, name }))); };
    const modal = el('div', { class: 'o-modal' },
      el('header', {}, el('h3', { text: title || 'Pick' }),
        multiple ? el('button', { class: 'btn small primary', type: 'button', text: 'Done', onclick: done }) : null,
        el('button', { class: 'btn small ghost', type: 'button', text: '✕', onclick: close })),
      el('div', { class: 'body' }, input, list));
    back.append(modal);
    back.addEventListener('click', (e) => { if (e.target === back) close(); });
    document.body.append(back);
    let timer, active = -1;
    async function load() {
      const q = input.value.trim();
      const data = await api(`/api/tables/${table}/records/?limit=60&q=${encodeURIComponent(q)}`);
      list.innerHTML = '';
      active = -1;
      if (!data.records.length) list.append(el('p', { class: 'muted', text: 'Nothing found.' }));
      for (const r of data.records) {
        const a = el('a', { href: '#', class: chosen.has(r.id) ? 'on' : '', text: r.label });
        a.addEventListener('click', (e) => {
          e.preventDefault();
          if (multiple) {
            if (chosen.has(r.id)) chosen.delete(r.id); else chosen.set(r.id, r.label);
            a.classList.toggle('on');
          } else {
            chosen = new Map([[r.id, r.label]]);
            done();
          }
        });
        list.append(a);
      }
    }
    input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(load, 200); });
    input.addEventListener('keydown', (e) => {
      const items = $$('a', list);
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        active = Math.max(0, Math.min(items.length - 1, active + (e.key === 'ArrowDown' ? 1 : -1)));
        items.forEach((a, i) => a.classList.toggle('active', i === active));
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (items[active]) items[active].click(); else if (multiple) done();
      } else if (e.key === 'Escape') close();
    });
    load();
    setTimeout(() => input.focus(), 10);
  }
  window.OSMIA.openPicker = openPicker;

  // -- Cell editing -------------------------------------------------------------------------
  let selected = null;
  let editor = null;
  // Opening an editor waits for the cell's value: a second open (a double-click is two clicks) wins,
  // and what is typed meanwhile goes into the editor once it's there.
  let opening = 0;
  let typedAhead = null;
  let enterAhead = false;

  function fieldOf(cell) { return META.fields[cell.dataset.field] || null; }
  async function rawOf(cell) {
    if (cell.hasAttribute('data-raw')) {
      try { return JSON.parse(cell.dataset.raw); } catch (e) { return null; }
    }
    const rec = await recordData(cell.dataset.record);
    return rec.cells[cell.dataset.field] ? rec.cells[cell.dataset.field].raw : null;
  }
  function select(cell) {
    if (selected) selected.classList.remove('selected');
    selected = cell;
    if (cell) { cell.classList.add('selected'); cell.scrollIntoView({ block: 'nearest', inline: 'nearest' }); }
  }
  function closeEditor(commit) {
    if (!editor) return;
    const ed = editor;
    editor = null;
    if (commit && ed.commit) ed.commit();
    ed.node.remove();
    document.removeEventListener('mousedown', ed.outside, true);
  }
  function place(node, cell, minWidth) {
    const r = cell.getBoundingClientRect();
    node.style.left = `${r.left + window.scrollX}px`;
    node.style.top = `${r.top + window.scrollY}px`;
    node.style.minWidth = `${Math.max(r.width, minWidth || 180)}px`;
    document.body.append(node);
    const nr = node.getBoundingClientRect();
    if (nr.right > window.innerWidth - 8) node.style.left = `${Math.max(8, window.innerWidth - nr.width - 8 + window.scrollX)}px`;
    if (nr.bottom > window.innerHeight - 8 && r.top > nr.height) node.style.top = `${r.bottom + window.scrollY - nr.height}px`;
  }
  function openEditor(cell, firstKey) {
    const f = fieldOf(cell);
    if (!f || !f.editable || !cell.classList.contains('editable')) return;
    closeEditor(false);
    const rid = cell.dataset.record, fid = cell.dataset.field;
    const kind = f.editor;
    if (kind === 'checkbox') {
      rawOf(cell).then((v) => save(rid, fid, !v, cell));
      return;
    }
    if (kind === 'attachment') { window.location = `/r/${rid}/`; return; }
    if (kind === 'link') {
      const ticket = ++opening;
      rawOf(cell).then((v) => ticket === opening && !(opening = 0) && !$('.o-modal-back') && openPicker({
        table: f.target, title: `${f.name}: ${f.target_name}`, multiple: f.multiple, selected: v || [],
        onDone: (items) => save(rid, fid, items.map((i) => i.id), cell),
      }));
      return;
    }
    const ticket = ++opening;
    typedAhead = firstKey !== undefined ? firstKey : null;
    rawOf(cell).then((value) => {
      if (ticket !== opening) return;   // opened again since
      opening = 0;
      if (typedAhead !== null) firstKey = typedAhead;
      typedAhead = null;
      const enter = enterAhead;
      enterAhead = false;
      const node = el('div', { class: 'editor' });
      const ed = { node, commit: null };
      ed.outside = (e) => {
        if (editor !== ed) { document.removeEventListener('mousedown', ed.outside, true); return; }   // an editor already gone
        if (!node.contains(e.target)) closeEditor(true);
      };
      if (['text', 'number', 'date', 'datetime', 'color'].includes(kind)) {
        const type = { number: 'text', date: 'date', datetime: 'datetime-local', color: 'color' }[kind] || 'text';
        const input = el('input', { type });
        input.value = firstKey !== undefined ? firstKey : (value === null || value === undefined ? '' : value);
        if (kind === 'number') input.inputMode = 'decimal';
        node.append(input);
        let done = false;
        ed.commit = () => {
          if (done) return; done = true;
          const v = input.value;
          const old = value === null || value === undefined ? '' : String(value);
          if (v !== old) save(rid, fid, v === '' ? null : v, cell);
        };
        input.addEventListener('keydown', (e) => {
          if (e.key === 'Enter') { e.preventDefault(); closeEditor(true); move(cell, 0, 1); }
          else if (e.key === 'Escape') { e.preventDefault(); closeEditor(false); }
          else if (e.key === 'Tab') { e.preventDefault(); closeEditor(true); move(cell, e.shiftKey ? -1 : 1, 0); }
        });
        if (kind === 'date' || kind === 'color') input.addEventListener('change', () => closeEditor(true));
        place(node, cell);
        input.focus();
        if (firstKey === undefined && input.select) try { input.select(); } catch (e) { /* date inputs */ }
      } else if (kind === 'textarea') {
        const ta = el('textarea');
        ta.value = firstKey !== undefined ? firstKey : (value || '');
        node.append(ta, el('div', { class: 'hint', text: 'Ctrl+Enter to save, Esc to cancel' }));
        ed.commit = () => { if (ta.value !== (value || '')) save(rid, fid, ta.value === '' ? null : ta.value, cell); };
        ta.addEventListener('keydown', (e) => {
          if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); closeEditor(true); }
          else if (e.key === 'Escape') { e.preventDefault(); closeEditor(false); }
        });
        place(node, cell, 340);
        ta.focus();
      } else if (kind === 'attributes') {
        const box = attributeRows(value || [], f.names || [], firstKey);
        node.append(box.node, el('div', { class: 'hint', text: 'Enter: next · Ctrl+Enter or click outside saves · Esc cancels' }));
        const initial = JSON.stringify(box.pairs());
        if (f.expects) {   // what its category (or whatever the field names) lists to fill in
          fetch(`/api/records/${rid}/`, { credentials: 'same-origin' }).then((r) => r.json()).then((rec) => {
            const cellInfo = (rec.cells || {})[fid] || {};
            if (editor === ed) box.expect(cellInfo.expected || []);
          }).catch(() => {});
        }
        ed.commit = () => { const now = box.pairs(); if (JSON.stringify(now) !== initial) save(rid, fid, now, cell); };
        node.addEventListener('keydown', (e) => {
          if (e.key === 'Escape') { e.preventDefault(); closeEditor(false); }
          else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); closeEditor(true); }
        });
        place(node, cell, 380);
        box.focus();
      } else if (kind === 'rating') {
        const max = f.max || 5;
        const row = el('div', { class: 'stars', style: 'font-size:20px;cursor:pointer;padding:2px 6px' });
        for (let i = 1; i <= max; i++) {
          row.append(el('span', { text: '★', class: i <= (value || 0) ? '' : 'off', onclick: () => { closeEditor(false); save(rid, fid, i === value ? 0 : i, cell); } }));
        }
        node.append(row);
        place(node, cell, 120);
      } else if (kind === 'select' || kind === 'multiselect' || kind === 'user') {
        const multiple = kind === 'multiselect' || (kind === 'user' && f.multiple);
        const options = kind === 'user'
          ? META.users.map((u) => ({ value: u.id, label: u.name }))
          : (f.choices || []).map((c) => ({ value: c.value, label: c.value, color: c.color }));
        let current;
        if (kind === 'user') current = new Set((value || []).map((u) => u.id));
        else if (multiple) current = new Set(value || []);
        else current = new Set(value ? [value] : []);
        const filter = el('input', { type: 'search', placeholder: 'Find…' });
        const list = el('div', { class: 'options' });
        const render = () => {
          list.innerHTML = '';
          const q = filter.value.trim().toLowerCase();
          if (!multiple) list.append(el('div', { class: 'option muted', text: '— none', onclick: () => { closeEditor(false); save(rid, fid, null, cell); } }));
          for (const o of options) {
            if (q && !o.label.toLowerCase().includes(q)) continue;
            const on = current.has(o.value);
            const label = o.color !== undefined ? el('span', { class: 'chip', style: `background:${o.color || '#e5e7eb'}`, text: o.label }) : el('span', { text: o.label });
            list.append(el('div', { class: `option${on ? ' on' : ''}`, onclick: () => {
              if (multiple) { if (on) current.delete(o.value); else current.add(o.value); render(); }
              else { closeEditor(false); save(rid, fid, o.value, cell); }
            } }, multiple ? el('span', { text: on ? '☑' : '☐' }) : null, label));
          }
        };
        filter.addEventListener('input', render);
        filter.addEventListener('keydown', (e) => {
          if (e.key === 'Escape') closeEditor(false);
          if (e.key === 'Enter') {
            e.preventDefault();
            if (multiple) closeEditor(true);
            else { const first = $$('.option', list).find((o) => !o.classList.contains('muted')); if (first) first.click(); }
          }
        });
        node.append(filter, list);
        if (multiple) {
          const initial = JSON.stringify([...current].sort());
          ed.commit = () => { if (JSON.stringify([...current].sort()) !== initial) save(rid, fid, [...current], cell); };
          node.append(el('div', { class: 'hint', text: 'Click outside or press Enter to save' }));
        }
        render();
        place(node, cell, 220);
        filter.focus();
      } else {
        return;
      }
      editor = ed;
      setTimeout(() => { if (editor === ed) document.addEventListener('mousedown', ed.outside, true); }, 0);
      if (enter && ed.commit) { closeEditor(true); move(cell, 0, 1); }   // Enter was pressed before it opened
    });
  }

  // Name-value pairs (an attributes field): a row of two inputs per pair, and an empty row to add one.
  // Enter goes from a name to its value, and from a value to the next row.
  function attributeRows(pairs, names, typed) {
    const listId = `attr-names-${Math.random().toString(36).slice(2)}`;
    const rows = el('div', { class: 'attr-rows' });
    const node = el('div', { class: 'attr-editor' }, el('datalist', { id: listId }, names.map((n) => el('option', { value: n }))), rows);
    const addRow = (name = '', value = '') => {
      const n = el('input', { type: 'text', class: 'attr-in-name', placeholder: 'Name', list: listId, 'aria-label': 'Name' });
      const v = el('input', { type: 'text', class: 'attr-in-value', placeholder: 'Value', 'aria-label': 'Value' });
      n.value = name;
      v.value = value;
      const row = el('div', { class: 'attr-row' }, n, v,
        el('button', { type: 'button', class: 'attr-remove', title: 'Take it away', text: '✕', onclick: () => { row.remove(); node.dispatchEvent(new Event('input')); if (!rows.children.length) addRow(); } }));
      n.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.ctrlKey && !e.metaKey) { e.preventDefault(); v.focus(); } });
      v.addEventListener('keydown', (e) => {
        if (e.key !== 'Enter' || e.ctrlKey || e.metaKey) return;
        e.preventDefault();
        // to the next row: its value when its name is there already (an attribute its category lists), else its name
        const next = row.nextElementSibling;
        (next ? $(next.dataset.expected || $('.attr-in-name', next).value ? '.attr-in-value' : '.attr-in-name', next) : addRow()).focus();
      });
      rows.append(row);
      return n;
    };
    pairs.forEach((p) => addRow(p.name, p.value));
    const blank = addRow(typed !== undefined ? typed : '');
    // a row for each attribute the record should fill in and hasn't: its name, its hint as the placeholder
    const expect = (wanted) => {
      const have = new Set($$('.attr-in-name', rows).map((i) => i.value.trim().toLowerCase()));
      let first = null;
      wanted.filter((w) => !have.has(w.name.toLowerCase())).forEach((w) => {
        const name = addRow(w.name, '');
        const row = name.closest('.attr-row');
        row.dataset.expected = '1';
        const value = $('.attr-in-value', row);
        value.placeholder = w.hint || 'Value';
        rows.insertBefore(row, blank.closest('.attr-row'));
        first = first || value;
      });
      if (first && document.activeElement === blank && !blank.value) first.focus();
    };
    node.append(el('button', { type: 'button', class: 'btn small ghost attr-add', text: '＋ Add', onclick: () => addRow().focus() }));
    return {
      node,
      pairs: () => $$('.attr-row', rows).filter((r) => !(r.dataset.expected && !$('.attr-in-value', r).value.trim()))
        .map((r) => ({ name: $('.attr-in-name', r).value.trim(), value: $('.attr-in-value', r).value.trim() }))
        .filter((p) => p.name || p.value),
      expect,
      focus: () => blank.focus(),
    };
  }
  window.OSMIA_attributeRows = attributeRows;

  // In forms the pairs go into the field's text box as "Name: value" lines
  $$('textarea[data-attributes]').forEach((ta) => {
    const pairs = ta.value.split('\n').filter((l) => l.trim()).map((l) => { const i = l.indexOf(':'); return i < 0 ? { name: l.trim(), value: '' } : { name: l.slice(0, i).trim(), value: l.slice(i + 1).trim() }; });
    const box = attributeRows(pairs, JSON.parse(ta.dataset.names || '[]'));
    const sync = () => { ta.value = box.pairs().map((p) => (p.value ? `${p.name}: ${p.value}` : p.name)).join('\n'); };
    box.node.addEventListener('input', sync);
    box.node.addEventListener('click', () => setTimeout(sync, 0));
    ta.hidden = true;
    ta.after(box.node);
  });

  function gridCells(cell) {
    const table = cell.closest('table');
    if (!table) return null;
    const rows = $$('tbody tr', table).filter((r) => r.querySelector('.cell'));
    return rows.map((r) => $$('.cell', r));
  }
  function move(cell, dx, dy) {
    const grid = gridCells(cell);
    if (!grid) return;
    for (let y = 0; y < grid.length; y++) {
      const x = grid[y].indexOf(cell);
      if (x === -1) continue;
      const ny = Math.max(0, Math.min(grid.length - 1, y + dy));
      const row = grid[ny];
      const nx = Math.max(0, Math.min(row.length - 1, x + dx));
      select(row[nx]);
      return;
    }
  }

  document.addEventListener('click', (e) => {
    const cell = e.target.closest('.cell');
    if (!cell || e.target.closest('a, button')) return;
    if (cell.closest('.props')) { select(cell); openEditor(cell); return; }
    if (selected === cell && cell.classList.contains('editable')) { openEditor(cell); return; }
    select(cell);
    const f = fieldOf(cell);
    if (f && f.editor === 'checkbox' && cell.classList.contains('editable') && e.target.closest('.check')) openEditor(cell);
  });
  document.addEventListener('dblclick', (e) => {
    const cell = e.target.closest('.cell.editable');
    if (!cell || e.target.closest('a, button')) return;
    const f = fieldOf(cell);
    if (f && f.editor === 'checkbox') return;   // its clicks tick and untick it
    select(cell);
    openEditor(cell);
  });
  document.addEventListener('keydown', (e) => {
    if (opening && !editor) {   // the editor is on its way: keep what is typed for it
      if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
        e.preventDefault();
        typedAhead = (typedAhead || '') + e.key;
      } else if (e.key === 'Enter') {
        e.preventDefault();
        enterAhead = true;
      } else if (e.key === 'Escape') {
        opening = 0;
        typedAhead = null;
        enterAhead = false;
      }
      return;
    }
    if (editor || !selected || !document.body.contains(selected)) return;
    if (e.target.matches('input, textarea, select')) return;
    const arrows = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    if (arrows[e.key]) { e.preventDefault(); move(selected, ...arrows[e.key]); return; }
    if (e.key === 'Tab') { e.preventDefault(); move(selected, e.shiftKey ? -1 : 1, 0); return; }
    if (e.key === 'Enter' || e.key === 'F2') { e.preventDefault(); openEditor(selected); return; }
    if (e.key === 'Escape') { select(null); return; }
    const f = fieldOf(selected);
    if (!f || !f.editable || !selected.classList.contains('editable')) return;
    if (e.key === 'Delete' || e.key === 'Backspace') {
      e.preventDefault();
      const empty = ['multiselect', 'link'].includes(f.editor) || (f.editor === 'user' && f.multiple) ? [] : (f.editor === 'checkbox' ? false : null);
      save(selected.dataset.record, selected.dataset.field, empty, selected);
      return;
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'c') {
      navigator.clipboard && navigator.clipboard.writeText(selected.innerText.trim());
      toast('Copied');
      return;
    }
    if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey && ['text', 'number', 'textarea'].includes(f.editor)) {
      e.preventDefault();
      openEditor(selected, e.key);
    }
  });
  document.addEventListener('paste', (e) => {
    if (editor || !selected || e.target.matches('input, textarea')) return;
    const f = fieldOf(selected);
    if (!f || !f.editable || !selected.classList.contains('editable')) return;
    const text = (e.clipboardData || window.clipboardData).getData('text').trim();
    if (!['text', 'number', 'textarea', 'date', 'datetime', 'select', 'color'].includes(f.editor)) return;
    e.preventDefault();
    save(selected.dataset.record, selected.dataset.field, text, selected);
  });

  // -- Adding records, links and buttons --------------------------------------------------
  document.addEventListener('click', async (e) => {
    const add = e.target.closest('#add-record');
    if (add) {
      try {
        await api(`/api/tables/${add.dataset.table}/create/`, { values: {} });
        window.location.reload();
      } catch (err) {
        window.location = add.dataset.form;  // required fields: use the form
      }
      return;
    }
    const quick = e.target.closest('.quick-add');
    if (quick) {
      try {
        await api(`/api/tables/${quick.dataset.table}/create/`, { values: { [quick.dataset.field]: [Number(quick.dataset.record)] } });
        window.location.reload();
      } catch (err) {
        if (quick.dataset.form) window.location = quick.dataset.form; else toast(err.message, true);
      }
      return;
    }
    const linkAdd = e.target.closest('.link-add');
    if (linkAdd) {
      const rec = await recordData(linkAdd.dataset.record);
      const current = rec.cells[linkAdd.dataset.field] ? rec.cells[linkAdd.dataset.field].raw : [];
      openPicker({ table: linkAdd.dataset.target, title: `Link ${linkAdd.dataset.targetName}`, multiple: true, selected: current,
        onDone: async (items) => {
          try {
            await api(`/api/records/${linkAdd.dataset.record}/`, { values: { [linkAdd.dataset.field]: items.map((i) => i.id) } });
            window.location.reload();
          } catch (err) { toast(err.message, true); }
        } });
      return;
    }
    const unlink = e.target.closest('.unlink');
    if (unlink) {
      try {
        await api(`/api/records/${unlink.dataset.record}/link/${unlink.dataset.field}/`, { remove: Number(unlink.dataset.remove) });
        window.location.reload();
      } catch (err) { toast(err.message, true); }
      return;
    }
    const btn = e.target.closest('.run-button, .run-automation');
    if (btn) {
      e.preventDefault();
      e.stopPropagation();
      btn.disabled = true;
      const url = btn.classList.contains('run-button')
        ? `/api/records/${btn.dataset.record}/button/${btn.dataset.field}/`
        : `/api/records/${btn.dataset.record}/run/${btn.dataset.automation}/`;
      try {
        const res = await api(url, {});
        toast(res.message || 'Done', res.status === 'skipped');
        setTimeout(() => window.location.reload(), res.status === 'skipped' ? 2500 : 700);
      } catch (err) {
        toast(err.message, true);
        btn.disabled = false;
      }
    }
  });

  // -- Link fields in forms -----------------------------------------------------------------
  $$('.link-input').forEach((box) => {
    let items = [];
    try { items = JSON.parse(box.dataset.initial || '[]'); } catch (e) { items = []; }
    const multiple = box.dataset.multiple === '1';
    const render = () => {
      box.innerHTML = '';
      for (const it of items) {
        box.append(el('span', { class: 'link-chip' }, it.name, ' ',
          el('button', { type: 'button', class: 'link', text: '✕', onclick: () => { items = items.filter((x) => x.id !== it.id); render(); } })),
        el('input', { type: 'hidden', name: box.dataset.name, value: it.id }));
      }
      if (!items.length) box.append(el('input', { type: 'hidden', name: box.dataset.name, value: '' }));
      box.append(el('button', { type: 'button', class: 'btn small', text: multiple || !items.length ? '＋ Choose' : 'Change',
        onclick: () => openPicker({ table: box.dataset.target, title: 'Choose', multiple, selected: items, onDone: (chosen) => { items = chosen; render(); } }) }));
    };
    render();
  });

  // -- Record page: side tabs and uploads -------------------------------------------------------
  $$('.side-tabs button').forEach((b) => b.addEventListener('click', () => {
    const card = b.closest('.card');
    $$('.side-tabs button', card).forEach((x) => x.classList.toggle('on', x === b));
    $$('[data-pane]', card).forEach((p) => p.classList.toggle('hidden', p.dataset.pane !== b.dataset.side));
  }));
  $$('.upload-form').forEach((form) => {
    const zone = $('.dropzone', form), input = $('input[type=file]', form);
    input.addEventListener('change', () => form.submit());
    ['dragenter', 'dragover'].forEach((ev) => zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.add('over'); }));
    ['dragleave', 'drop'].forEach((ev) => zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.remove('over'); }));
    zone.addEventListener('drop', (e) => { input.files = e.dataTransfer.files; form.submit(); });
  });

  // -- Sortable lists (settings pages) -----------------------------------------------------------
  function sortable(container, itemSel) {
    let dragging = null;
    container.addEventListener('dragstart', (e) => {
      dragging = e.target.closest(itemSel);
      if (dragging) { dragging.classList.add('dragging'); e.dataTransfer.effectAllowed = 'move'; }
    });
    container.addEventListener('dragend', () => { if (dragging) dragging.classList.remove('dragging'); dragging = null; });
    container.addEventListener('dragover', (e) => {
      if (!dragging) return;
      e.preventDefault();
      const over = e.target.closest(itemSel);
      if (!over || over === dragging || over.parentNode !== dragging.parentNode) return;
      const r = over.getBoundingClientRect();
      const after = (e.clientY - r.top) > r.height / 2;
      over.parentNode.insertBefore(dragging, after ? over.nextSibling : over);
    });
  }
  $$('.sortable').forEach((c) => sortable(c, '[draggable=true]'));
  $$('.sortable-rows tbody').forEach((c) => sortable(c, 'tr'));

  // -- The view toolbar: fields, filter, sort, group ------------------------------------------------
  const toolbar = $('#toolbar');
  const tableFields = Object.entries(META.fields || {}).filter(([, f]) => f.table === META.table).map(([id, f]) => ({ id, ...f }));
  function go(params) {
    const url = new URL(window.location.href);
    for (const [k, v] of Object.entries(params)) {
      if (v === null) url.searchParams.delete(k); else url.searchParams.set(k, v);
    }
    url.searchParams.delete('page');
    window.location = url.toString();
  }
  async function saveConfig(patch) {
    try {
      await api(`/api/views/${META.view}/config/`, patch);
      return true;
    } catch (err) { toast(err.message, true); return false; }
  }
  function fieldSelect(value, filterFn) {
    const s = el('select');
    for (const f of tableFields) {
      if (filterFn && !filterFn(f)) continue;
      s.append(el('option', { value: f.key, text: f.name, selected: f.key === value }));
    }
    return s;
  }
  function popover(anchor, build) {
    $$('.popover').forEach((p) => p.remove());
    const pop = el('div', { class: 'popover' });
    build(pop);
    anchor.parentNode.append(pop);
    const off = (e) => { if (!pop.contains(e.target) && e.target !== anchor) { pop.remove(); document.removeEventListener('mousedown', off); } };
    setTimeout(() => document.addEventListener('mousedown', off), 0);
  }
  const NO_VALUE = new Set(['is_empty', 'not_empty', 'checked', 'unchecked', 'is_today', 'is_before_today', 'is_after_today', 'is_me']);

  const pops = {
    fields(pop) {
      const cfg = META.config || {};
      const shown = cfg.fields && cfg.fields.length ? cfg.fields : tableFields.map((f) => f.key);
      const ordered = [...shown.map((k) => tableFields.find((f) => f.key === k)).filter(Boolean), ...tableFields.filter((f) => !shown.includes(f.key))];
      const list = el('div', { class: 'field-list' });
      for (const f of ordered) {
        list.append(el('label', { draggable: 'true' }, el('span', { class: 'muted', text: '☰' }),
          el('input', { type: 'checkbox', value: f.key, checked: shown.includes(f.key) }), ` ${f.name}`));
      }
      sortable(list, 'label');
      pop.append(el('div', { class: 'muted small', text: 'Shown fields (drag to reorder)' }), list,
        el('div', { class: 'foot' },
          el('button', { class: 'btn small primary', type: 'button', text: 'Save for everyone', onclick: async () => {
            const keys = $$('input', list).filter((i) => i.checked).map((i) => i.value);
            if (await saveConfig({ fields: keys })) window.location.reload();
          } }),
          el('button', { class: 'btn small', type: 'button', text: 'Show all', onclick: async () => { if (await saveConfig({ fields: [] })) window.location.reload(); } })));
    },
    filter(pop) {
      const state = JSON.parse(JSON.stringify((META.state && META.state.filters) || { match: 'all', rules: [] }));
      state.rules = state.rules || [];
      const rows = el('div');
      const match = el('select', {}, el('option', { value: 'all', text: 'All of these', selected: state.match !== 'any' }),
        el('option', { value: 'any', text: 'Any of these', selected: state.match === 'any' }));
      const formula = el('input', { type: 'text', placeholder: 'Formula, e.g. {Total} > 100 (optional)', value: state.formula || '', style: 'width:100%' });
      const draw = () => {
        rows.innerHTML = '';
        state.rules.forEach((rule, i) => {
          const fs = fieldSelect(rule.field);
          const field = () => tableFields.find((f) => f.key === fs.value);
          const ops = el('select');
          const val = el('input', { type: 'text', value: rule.value || '', placeholder: 'value' });
          const fillOps = () => {
            ops.innerHTML = '';
            const f = field();
            for (const [op, label] of (META.ops[f.id] || [])) ops.append(el('option', { value: op, text: label, selected: op === rule.op }));
            val.style.display = NO_VALUE.has(ops.value) ? 'none' : '';
          };
          fs.addEventListener('change', () => { rule.field = fs.value; rule.op = ''; fillOps(); rule.op = ops.value; });
          ops.addEventListener('change', () => { rule.op = ops.value; val.style.display = NO_VALUE.has(ops.value) ? 'none' : ''; });
          val.addEventListener('input', () => { rule.value = val.value; });
          rule.field = fs.value;
          fillOps();
          rule.op = ops.value;
          rows.append(el('div', { class: 'row' }, fs, ops, val,
            el('button', { class: 'btn small ghost', type: 'button', text: '✕', onclick: () => { state.rules.splice(i, 1); draw(); } })));
        });
        if (!state.rules.length) rows.append(el('p', { class: 'muted small', text: 'No filters: every record is shown.' }));
      };
      draw();
      const result = () => ({ match: match.value, rules: state.rules.filter((r) => r.field && r.op), formula: formula.value.trim() });
      pop.append(el('div', { class: 'row' }, match), rows,
        el('button', { class: 'btn small', type: 'button', text: '＋ Add a filter', onclick: () => { state.rules.push({ field: tableFields[0].key, op: '', value: '' }); draw(); } }),
        el('div', { style: 'margin-top:8px' }, formula),
        el('div', { class: 'foot' },
          el('button', { class: 'btn small primary', type: 'button', text: 'Apply', onclick: () => go({ filters: JSON.stringify(result()) }) }),
          el('button', { class: 'btn small', type: 'button', text: 'Save for everyone', onclick: async () => {
            if (await saveConfig({ filters: result() })) window.location = window.location.pathname;
          } })));
    },
    sort(pop) {
      const sorts = JSON.parse(JSON.stringify((META.state && META.state.sorts) || []));
      const rows = el('div');
      const draw = () => {
        rows.innerHTML = '';
        sorts.forEach((s, i) => {
          const fs = fieldSelect(s.field, (f) => !['button', 'attachment'].includes(f.type));
          const dir = el('select', {}, el('option', { value: 'asc', text: 'A → Z, 1 → 9', selected: s.dir !== 'desc' }), el('option', { value: 'desc', text: 'Z → A, 9 → 1', selected: s.dir === 'desc' }));
          fs.addEventListener('change', () => { s.field = fs.value; });
          dir.addEventListener('change', () => { s.dir = dir.value; });
          s.field = fs.value;
          rows.append(el('div', { class: 'row' }, fs, dir, el('button', { class: 'btn small ghost', type: 'button', text: '✕', onclick: () => { sorts.splice(i, 1); draw(); } })));
        });
        if (!sorts.length) rows.append(el('p', { class: 'muted small', text: 'In the order they were added (or dragged).' }));
      };
      draw();
      pop.append(rows, el('button', { class: 'btn small', type: 'button', text: '＋ Sort by', onclick: () => { sorts.push({ field: tableFields[0].key, dir: 'asc' }); draw(); } }),
        el('div', { class: 'foot' },
          el('button', { class: 'btn small primary', type: 'button', text: 'Apply', onclick: () => go({ sorts: JSON.stringify(sorts) }) }),
          el('button', { class: 'btn small', type: 'button', text: 'Save for everyone', onclick: async () => {
            if (await saveConfig({ sorts })) window.location = window.location.pathname;
          } })));
    },
    group(pop) {
      const current = (META.state && META.state.group_by) || '';
      const s = fieldSelect(current, (f) => ['select', 'link', 'user', 'text', 'checkbox', 'lookup', 'formula', 'date', 'multiselect', 'rating'].includes(f.type));
      s.prepend(el('option', { value: '', text: '— no grouping', selected: !current }));
      pop.append(el('div', { class: 'row' }, s), el('div', { class: 'foot' },
        el('button', { class: 'btn small primary', type: 'button', text: 'Apply', onclick: () => go({ group_by: s.value }) }),
        el('button', { class: 'btn small', type: 'button', text: 'Save for everyone', onclick: async () => {
          if (await saveConfig({ group_by: s.value })) window.location = window.location.pathname;
        } })));
    },
  };
  if (toolbar) {
    toolbar.addEventListener('click', (e) => {
      const b = e.target.closest('[data-pop]');
      if (b && pops[b.dataset.pop]) popover(b, pops[b.dataset.pop]);
    });
    const saveView = $('#save-view');
    if (saveView) saveView.addEventListener('click', async () => {
      const s = META.state || {};
      if (await saveConfig({ filters: s.filters, sorts: s.sorts, group_by: s.group_by })) window.location = window.location.pathname;
    });
  }

  // -- Grid: column widths --------------------------------------------------------------------------
  const grid = $('#grid');
  if (grid && META.view) {
    let resizing = null;
    grid.addEventListener('mousedown', (e) => {
      const handle = e.target.closest('.resize');
      if (!handle) return;
      e.preventDefault();
      const th = handle.parentNode;
      resizing = { th, x: e.clientX, w: th.getBoundingClientRect().width };
    });
    document.addEventListener('mousemove', (e) => {
      if (!resizing) return;
      const w = Math.max(60, resizing.w + e.clientX - resizing.x);
      Object.assign(resizing.th.style, { width: `${w}px`, minWidth: `${w}px`, maxWidth: `${w}px` });
      const idx = Array.from(resizing.th.parentNode.children).indexOf(resizing.th);
      $$('tbody tr', grid).forEach((tr) => { const td = tr.children[idx]; if (td && !tr.classList.contains('group')) td.style.maxWidth = `${w}px`; });
    });
    document.addEventListener('mouseup', () => {
      if (!resizing) return;
      const widths = Object.assign({}, (META.config && META.config.widths) || {});
      widths[resizing.th.dataset.key] = Math.round(resizing.th.getBoundingClientRect().width);
      META.config.widths = widths;
      resizing = null;
      api(`/api/views/${META.view}/config/`, { widths }).catch(() => {});
    });
  }

  // -- Tree: open and close -----------------------------------------------------------------------
  if (grid && grid.classList.contains('tree')) {
    const key = grid.dataset.treeKey;
    const closed = new Set(store.get(key, []));
    const rows = $$('tbody tr[data-record]', grid);
    const children = {};
    rows.forEach((r) => { (children[r.dataset.parent] = children[r.dataset.parent] || []).push(r); });
    const apply = () => {
      const hide = (id, hidden) => (children[id] || []).forEach((r) => {
        r.classList.toggle('hidden', hidden);
        hide(r.dataset.record, hidden || closed.has(r.dataset.record));
      });
      hide('', false);
      rows.forEach((r) => {
        const t = r.querySelector('.toggle');
        if (t && !t.classList.contains('leaf')) t.textContent = closed.has(r.dataset.record) ? '▸' : '▾';
      });
      store.set(key, [...closed]);
    };
    grid.addEventListener('click', (e) => {
      const t = e.target.closest('.toggle');
      if (!t || t.classList.contains('leaf')) return;
      e.stopPropagation();
      const id = t.closest('tr').dataset.record;
      if (closed.has(id)) closed.delete(id); else closed.add(id);
      apply();
    }, true);
    $$('[data-tree]').forEach((b) => b.addEventListener('click', () => {
      closed.clear();
      if (b.dataset.tree === 'collapse') rows.forEach((r) => { if (children[r.dataset.record]) closed.add(r.dataset.record); });
      apply();
    }));
    apply();
  }

  // -- Kanban: drag cards between columns ----------------------------------------------------------
  const board = $('#board');
  if (board && board.dataset.drag === '1') {
    let card = null;
    const field = META.fields[board.dataset.field];
    board.addEventListener('dragstart', (e) => {
      card = e.target.closest('.kcard');
      if (card) { card.classList.add('dragging'); e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', card.dataset.record); }
    });
    board.addEventListener('dragend', () => { if (card) card.classList.remove('dragging'); card = null; $$('.column.over').forEach((c) => c.classList.remove('over')); });
    board.addEventListener('dragover', (e) => {
      const col = e.target.closest('.column');
      if (!card || !col) return;
      e.preventDefault();
      $$('.column.over').forEach((c) => c !== col && c.classList.remove('over'));
      col.classList.add('over');
    });
    board.addEventListener('drop', async (e) => {
      const col = e.target.closest('.column');
      if (!card || !col) return;
      e.preventDefault();
      col.classList.remove('over');
      const from = card.closest('.column');
      const moving = card;
      if (from === col) return;
      let value = col.dataset.value;
      if (field.type === 'link') value = value ? [Number(value)] : [];
      else if (field.type === 'user') value = value ? Number(value) : null;
      else if (value === '') value = null;
      $('.cards', col).prepend(moving);
      try {
        await api(`/api/records/${moving.dataset.record}/`, { values: { [board.dataset.field]: value } });
        [from, col].forEach((c) => { const n = $('header .n', c); if (n) n.textContent = $$('.kcard', c).length; });
      } catch (err) {
        toast(err.message, true);
        $('.cards', from).prepend(moving);
      }
    });
  }

  // -- Calendar: drag to another day ------------------------------------------------------------
  const calendar = $('#calendar');
  if (calendar && calendar.dataset.drag === '1') {
    let ev = null;
    const shift = (iso, days) => {
      if (!iso) return null;
      const time = iso.length > 10 ? iso.slice(10) : '';
      const d = new Date(`${iso.slice(0, 10)}T12:00:00`);
      d.setDate(d.getDate() + days);
      return d.toISOString().slice(0, 10) + time;
    };
    calendar.addEventListener('dragstart', (e) => { ev = e.target.closest('.ev'); if (ev) e.dataTransfer.setData('text/plain', ev.dataset.record); });
    calendar.addEventListener('dragover', (e) => { const day = e.target.closest('.day'); if (ev && day) { e.preventDefault(); $$('.day.over').forEach((d) => d.classList.remove('over')); day.classList.add('over'); } });
    calendar.addEventListener('drop', async (e) => {
      const day = e.target.closest('.day');
      if (!ev || !day) return;
      e.preventDefault();
      day.classList.remove('over');
      const from = ev.closest('.day').dataset.date, to = day.dataset.date;
      const days = Math.round((new Date(`${to}T12:00:00`) - new Date(`${from}T12:00:00`)) / 86400000);
      if (!days) return;
      const rec = await recordData(ev.dataset.record);
      const values = {};
      const s = calendar.dataset.field, end = calendar.dataset.end;
      values[s] = shift(rec.cells[s].raw, days);
      if (end && rec.cells[end] && rec.cells[end].raw && META.fields[end].editable) values[end] = shift(rec.cells[end].raw, days);
      try { await api(`/api/records/${ev.dataset.record}/`, { values }); window.location.reload(); } catch (err) { toast(err.message, true); }
    });
  }

  // -- Gantt: drag bars, stretch their end -----------------------------------------------------------
  const gantt = $('#gantt');
  if (gantt) {
    const chart = $('#gantt-chart'), names = $('.names-body', gantt);
    chart.addEventListener('scroll', () => { names.style.transform = `translateY(${-chart.scrollTop}px)`; });
    const today = () => { chart.scrollLeft = Math.max(0, Number(gantt.dataset.today) - chart.clientWidth / 3); };
    today();
    const tb = $('#gantt-today');
    if (tb) tb.addEventListener('click', today);
    if (gantt.dataset.drag === '1') {
      const px = Number(gantt.dataset.px);
      let drag = null, moved = false;
      chart.addEventListener('mousedown', (e) => {
        const bar = e.target.closest('.bar');
        if (!bar) return;
        e.preventDefault();
        drag = { bar, x: e.clientX, left: bar.offsetLeft, width: bar.offsetWidth, grip: !!e.target.closest('.grip') };
        moved = false;
      });
      document.addEventListener('mousemove', (e) => {
        if (!drag) return;
        const dx = e.clientX - drag.x;
        if (Math.abs(dx) > 3) moved = true;
        const days = Math.round(dx / px);
        if (drag.grip) drag.bar.style.width = `${Math.max(px - 2, drag.width + days * px)}px`;
        else drag.bar.style.left = `${drag.left + days * px}px`;
        drag.days = days;
      });
      document.addEventListener('mouseup', async () => {
        if (!drag) return;
        const d = drag;
        drag = null;
        if (!moved || !d.days) return;
        const shift = (iso, n) => { const t = new Date(`${iso}T12:00:00`); t.setDate(t.getDate() + n); return t.toISOString().slice(0, 10); };
        const values = {};
        const s = gantt.dataset.start, end = gantt.dataset.end;
        if (d.grip) {
          values[end] = shift(d.bar.dataset.end, d.days);
        } else {
          values[s] = shift(d.bar.dataset.start, d.days);
          if (end) values[end] = shift(d.bar.dataset.end, d.days);
        }
        try { await api(`/api/records/${d.bar.dataset.record}/`, { values }); window.location.reload(); }
        catch (err) { toast(err.message, true); window.location.reload(); }
      });
      chart.addEventListener('click', (e) => { if (moved && e.target.closest('.bar')) { e.preventDefault(); moved = false; } }, true);
    }
  }
})();
