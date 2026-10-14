/* The page editor: a contenteditable body with a toolbar, like Confluence's.
 * What it makes is cleaned again on the server (see sanitize.py). */
(function () {
  'use strict';
  const form = document.getElementById('page-form');
  if (!form) return;
  const editor = document.getElementById('editor');
  const body = document.getElementById('body');
  const choices = JSON.parse(document.getElementById('embed-choices').textContent);
  let dirty = false;
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  document.execCommand('defaultParagraphSeparator', false, 'p');
  if (!editor.innerHTML.trim()) editor.innerHTML = '<p><br></p>';
  // Live parts are placeholders while writing: whole pieces, not text to type into
  editor.querySelectorAll('.embed-view, .record-ref, .record-card, .record-value, .page-calc').forEach((el) => el.setAttribute('contenteditable', 'false'));
  editor.querySelectorAll('.page-calc').forEach((el) => { el.title = 'A calculation: double-click to change it'; });
  editor.addEventListener('input', () => { dirty = true; });

  // Remember where the caret was, so toolbar dialogs insert in the right place
  let saved = null;
  const keep = () => {
    const sel = window.getSelection();
    if (sel.rangeCount && editor.contains(sel.anchorNode)) saved = sel.getRangeAt(0).cloneRange();
  };
  const restore = () => {
    editor.focus();
    if (saved) { const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(saved); }
  };
  editor.addEventListener('keyup', keep);
  editor.addEventListener('mouseup', keep);
  editor.addEventListener('blur', keep);
  const insert = (html) => { restore(); document.execCommand('insertHTML', false, html); dirty = true; keep(); };
  // Blocks (task lists, tables, panels, views) go after the block the caret is in, at the top level,
  // never inside a list item or a paragraph (the browser would merge them into it).
  const afterCurrentBlock = () => {
    restore();
    const sel = window.getSelection();
    let node = sel.rangeCount ? sel.getRangeAt(0).startContainer : null;
    if (!node || !editor.contains(node) || node === editor) return;
    while (node.parentNode && node.parentNode !== editor) node = node.parentNode;
    const blank = node.nodeType === 1 && node.tagName === 'P' && !node.textContent.trim();
    const range = document.createRange();
    if (blank) range.selectNode(node); else range.setStartAfter(node);
    if (!blank) range.collapse(true);
    sel.removeAllRanges();
    sel.addRange(range);
    keep();
  };
  // Insert a block, then put the caret in the part marked data-focus (selecting its placeholder text)
  const insertInto = (html) => {
    afterCurrentBlock();
    insert(html);
    const target = editor.querySelector('[data-focus]');
    if (!target) return;
    target.removeAttribute('data-focus');
    const range = document.createRange();
    range.selectNodeContents(target);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    keep();
  };

  // Toolbar
  form.querySelector('.editor-toolbar').addEventListener('mousedown', (e) => { if (e.target.closest('button')) e.preventDefault(); });
  form.querySelector('[data-block]').addEventListener('change', (e) => {
    restore();
    document.execCommand('formatBlock', false, `<${e.target.value}>`);
    e.target.value = 'p';
    dirty = true;
  });
  form.querySelector('.editor-toolbar').addEventListener('click', async (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    if (b.dataset.cmd) { restore(); document.execCommand(b.dataset.cmd, false, null); dirty = true; return; }
    if (b.dataset.panel) {
      const text = window.getSelection().toString() || 'Write here';
      insertInto(`<div class="panel ${b.dataset.panel}"><p data-focus="1">${esc(text)}</p></div><p><br></p>`);
      return;
    }
    const action = b.dataset.action;
    if (action === 'code') {
      const text = window.getSelection().toString() || 'code';
      insert(`<code>${esc(text)}</code>&nbsp;`);
    } else if (action === 'link') {
      keep();
      const url = prompt('Link to (https://..., or an Osmia address like /r/12/):');
      if (url) { restore(); document.execCommand('createLink', false, url); dirty = true; }
    } else if (action === 'tasks') {
      insertInto('<ul class="tasks"><li class="task" data-checked="false" data-focus="1">To do</li></ul><p><br></p>');
    } else if (action === 'table') {
      const row = (cell, first) => `<tr>${[1, 2, 3].map((n) => `<${cell}${first && n === 1 ? ' data-focus="1"' : ''}>${first && n === 1 ? 'Heading' : '<br>'}</${cell}>`).join('')}</tr>`;
      insertInto(`<table><thead>${row('th', true)}</thead><tbody>${row('td')}${row('td')}</tbody></table><p><br></p>`);
    } else if (action === 'image') {
      keep();
      document.getElementById('image-file').click();
    } else if (action === 'view') {
      keep();
      pick('Put a live view on the page', choices.map(([label, id]) => ({ label, id })), (item) => {
        afterCurrentBlock();
        insert(`<div class="embed-view" data-view="${item.id}" data-title="${esc(item.label)}" contenteditable="false">⊞ ${esc(item.label)}</div><p><br></p>`);
      });
    } else if (action === 'record') {
      keep();
      pick('Link a record', null, (item) => recordDialog(item.id));
    } else if (action === 'calc') {
      keep();
      calcDialog();
    }
  });

  // A record: a link, a card with some of its fields, or one field's value in the text.
  // `card` is a card already on the page, to change which fields it shows.
  // Live pieces go in with a range, not insertHTML: browsers split the paragraph around a
  // contenteditable=false piece, or leave the caret before a block. The caret goes after the
  // piece, or into the empty paragraph that follows a block.
  const place = (html) => {
    restore();
    const sel = window.getSelection();
    if (!sel.rangeCount) return;
    const range = sel.getRangeAt(0);
    range.deleteContents();
    const tpl = document.createElement('template');
    tpl.innerHTML = html;
    const last = tpl.content.lastChild;
    range.insertNode(tpl.content);
    const caret = document.createRange();
    if (last.nodeName === 'P') caret.setStart(last, 0); else caret.setStartAfter(last);
    sel.removeAllRanges();
    sel.addRange(caret);
    dirty = true;
    keep();
  };
  const recordLink = (r, named = '') => `<a class="record-ref" data-record="${r.id}"${named} href="/r/${r.id}/" contenteditable="false">${esc(r.label)}</a>&nbsp;`;
  const fetchRecord = async (id) => {
    const res = await fetch(`${form.dataset.records}${id}/`, { credentials: 'same-origin' });
    if (!res.ok) throw new Error(res.status === 403 ? 'You have no access to that record.' : 'That record is gone.');
    return res.json();
  };
  // Names records and calculations go by in formulas: {budget.Remaining}, {total}
  const NAME = /^[A-Za-z_][A-Za-z0-9_]{0,30}$/;
  const nameProblem = (name, recordId, self) => {
    if (!name) return '';
    if (!NAME.test(name)) return 'A name is letters, digits and _, starting with a letter, e.g. budget or part_1.';
    const taken = [...editor.querySelectorAll('[data-name]')].find((x) => x !== self && x.dataset.name === name
      && !(recordId && x.dataset.record === String(recordId)));
    return taken ? `Something else on this page is already called ${name}.` : '';
  };
  async function recordDialog(id, card) {
    let r;
    try { r = await fetchRecord(id); } catch (err) { OSMIA.toast(err.message, true); return; }
    const ticked = new Set(card ? (card.dataset.fields || '').split(',') : []);
    const known = card ? card.dataset.name : (editor.querySelector(`[data-record="${r.id}"][data-name]`) || { dataset: {} }).dataset.name;
    const back = document.createElement('div');
    back.className = 'o-modal-back';
    back.innerHTML = `<div class="o-modal"><header><h3>${esc(r.icon)} ${esc(r.label)} <span class="muted small">${esc(r.where)}</span></h3><button type="button" class="btn small ghost">✕</button></header>
      <div class="body"><p class="muted small">Tick fields to show them on a card, or click a value to put it in your text. Both stay live: readers see the record as it is now.</p>
      <div class="record-pick">${r.fields.map((f) => `<label><input type="checkbox" value="${f.id}"${ticked.has(String(f.id)) ? ' checked' : ''}> ${esc(f.name)}</label>
        <button type="button" class="link" data-value="${f.id}" title="Put this value in the text">${esc(f.text || '—')}</button>`).join('')}</div>
      <label class="small record-name">Name for calculations (optional) <input class="calc-name" value="${esc(known || '')}" placeholder="e.g. budget" maxlength="31"></label>
      <div class="actions">${card ? '' : '<button type="button" class="btn" data-do="link">⇄ Insert link</button>'}
        <button type="button" class="btn primary" data-do="card">▤ ${card ? 'Update card' : 'Insert card'}</button></div></div></div>`;
    document.body.append(back);
    const close = () => back.remove();
    back.querySelector('header button').onclick = close;
    back.addEventListener('click', (e) => { if (e.target === back) close(); });
    back.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(); });
    back.querySelector('.body').addEventListener('click', (e) => {
      const b = e.target.closest('button');
      if (!b) return;
      const name = back.querySelector('.calc-name').value.trim();
      const problem = nameProblem(name, r.id, card);
      if (problem) { OSMIA.toast(problem, true); return; }
      const named = name ? ` data-name="${esc(name)}"` : '';
      if (b.dataset.value) {
        const f = r.fields.find((x) => String(x.id) === b.dataset.value);
        close();
        place(`<span class="record-value" data-record="${r.id}" data-field="${f.id}"${named} contenteditable="false">${esc(r.label)} › ${esc(f.name)}</span>&nbsp;`);
      } else if (b.dataset.do === 'link') {
        close();
        place(recordLink(r, named));
      } else if (b.dataset.do === 'card') {
        const ids = [...back.querySelectorAll('.record-pick input:checked')].map((i) => i.value);
        const names = r.fields.filter((f) => ids.includes(String(f.id))).map((f) => f.name);
        const html = `<div class="record-card" data-record="${r.id}" data-fields="${ids.join(',')}"${named} contenteditable="false">▤ ${esc(r.label)}${names.length ? ` — ${esc(names.join(', '))}` : ''}</div>`;
        close();
        if (card) { card.outerHTML = html; dirty = true; return; }
        afterCurrentBlock();
        place(`${html}<p><br></p>`);
      }
    });
    setTimeout(() => (back.querySelector('.record-pick input') || back.querySelector('.actions button')).focus(), 10);
  }
  // A calculation: a formula over records named on the page, the cells of its own table row
  // (by their heading) and other named calculations. Worked out when the page is read; the
  // dialog previews it on the server with the page as it is in the editor.
  const calcLabel = (el) => {
    el.textContent = `ƒ ${el.dataset.name ? `${el.dataset.name} = ` : ''}${el.dataset.formula}`;
    el.title = 'A calculation: double-click to change it';
  };
  function calcDialog(el) {
    const isNew = !el;
    if (isNew) {
      place('<span class="page-calc" data-formula="" data-editing="1" contenteditable="false">ƒ</span>&nbsp;');
      el = editor.querySelector('[data-editing]');
      if (!el) return;
      el.removeAttribute('data-editing');
    }
    const old = { formula: el.dataset.formula || '', name: el.dataset.name || '' };
    // What the formula can use: this row's other cells, named records, named calculations
    const row = el.closest('tr'), table = el.closest('table');
    let columns = [];
    if (row && table && table.querySelector('tr') !== row) {
      const own = [...row.children].indexOf(el.closest('td, th'));
      columns = [...table.querySelector('tr').children].map((c, i) => (i === own ? '' : c.textContent.trim().replace(/\s+/g, ' '))).filter(Boolean);
    }
    const records = {};
    editor.querySelectorAll('[data-name][data-record]').forEach((x) => { records[x.dataset.name] = records[x.dataset.name] || x.dataset.record; });
    const calcs = [...editor.querySelectorAll('.page-calc[data-name]')].filter((x) => x !== el && !x.closest('table')).map((x) => x.dataset.name);
    const chip = (t) => `<button type="button" class="calc-chip" data-ins="${esc(t)}">${esc(t)}</button>`;
    const back = document.createElement('div');
    back.className = 'o-modal-back';
    back.innerHTML = `<div class="o-modal calc-dialog"><header><h3>ƒ Calculation</h3><button type="button" class="btn small ghost">✕</button></header>
      <div class="body">
        <textarea class="calc-formula" rows="3" spellcheck="false" placeholder="e.g. {budget.Remaining} - {part.Unit cost} * {Qty}">${esc(old.formula)}</textarea>
        <div class="calc-preview"><span class="muted small">Result:</span> <span class="calc-out">…</span></div>
        <label class="small">Name, to use the result in other calculations (optional) <input class="calc-name" value="${esc(old.name)}" placeholder="e.g. total" maxlength="31"${row ? ' disabled title="Calculations in a table are used by their column heading"' : ''}></label>
        ${columns.length ? `<div class="calc-names"><b class="small">This row</b> ${columns.map((c) => chip(`{${c}}`)).join('')}</div>` : ''}
        ${Object.keys(records).length ? `<div class="calc-names"><b class="small">Records on this page</b> ${Object.keys(records).map((n) => `<button type="button" class="link small" data-rec="${esc(n)}">▸ ${esc(n)}</button><span class="calc-fields" data-for="${esc(n)}"></span>`).join(' ')}</div>` : ''}
        ${calcs.length ? `<div class="calc-names"><b class="small">Calculations</b> ${calcs.map((c) => chip(`{${c}}`)).join('')}</div>` : ''}
        ${!columns.length && !Object.keys(records).length ? '<p class="muted small">To use a record’s fields, put it on the page with a name: <b>⇄ Record</b> → <i>Name for calculations</i>.</p>' : ''}
        <p class="muted small">Same as formula fields: + − * /, SUM, ROUND(x, 2), IF(…), MIN, MAX, … A table cell under the heading “Qty” is {Qty}.</p>
        <div class="actions"><button type="button" class="btn primary" data-do="save">Save</button>${isNew ? '' : '<button type="button" class="btn ghost" data-do="remove">Remove</button>'}</div>
      </div></div>`;
    document.body.append(back);
    const ta = back.querySelector('.calc-formula'), nameInput = back.querySelector('.calc-name'), out = back.querySelector('.calc-out');
    let done = false;
    const finish = (keep) => {
      if (done) return;
      done = true;
      back.remove();
      if (keep) return;
      if (isNew) el.remove(); else { el.dataset.formula = old.formula; if (old.name) el.dataset.name = old.name; else delete el.dataset.name; }
    };
    let timer;
    const preview = () => {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        if (!ta.value.trim()) { out.textContent = '…'; return; }
        el.dataset.formula = ta.value.trim();
        const fd = new FormData();
        fd.append('body', editor.innerHTML);
        fd.append('index', [...editor.querySelectorAll('.page-calc')].indexOf(el));
        try {
          const res = await fetch(form.dataset.calc, { method: 'POST', body: fd, credentials: 'same-origin', headers: { 'X-CSRFToken': window.OSMIA_CSRF } });
          out.innerHTML = (await res.json()).html || '—';   // escaped on the server
        } catch (err) { out.textContent = '?'; }
      }, 300);
    };
    ta.addEventListener('input', preview);
    back.querySelector('header button').onclick = () => finish(false);
    back.addEventListener('click', (e) => { if (e.target === back) finish(false); });
    back.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') finish(false);
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) back.querySelector('[data-do=save]').click();
    });
    back.querySelector('.body').addEventListener('click', async (e) => {
      const b = e.target.closest('button');
      if (!b) return;
      if (b.dataset.ins) {
        ta.setRangeText(b.dataset.ins, ta.selectionStart, ta.selectionEnd, 'end');
        ta.focus();
        preview();
      } else if (b.dataset.rec) {
        const box = back.querySelector(`.calc-fields[data-for="${b.dataset.rec}"]`);
        if (box.innerHTML) { box.innerHTML = ''; return; }
        try {
          const r = await fetchRecord(records[b.dataset.rec]);
          box.innerHTML = r.fields.map((f) => chip(`{${b.dataset.rec}.${f.name}}`)).join('');
        } catch (err) { OSMIA.toast(err.message, true); }
      } else if (b.dataset.do === 'remove') {
        finish(true);
        el.remove();
        dirty = true;
      } else if (b.dataset.do === 'save') {
        const formula = ta.value.trim(), name = row ? '' : nameInput.value.trim();
        const problem = nameProblem(name, null, el);
        if (problem) { OSMIA.toast(problem, true); return; }
        finish(true);
        if (!formula) { el.remove(); dirty = true; return; }
        el.dataset.formula = formula;
        if (name) el.dataset.name = name; else delete el.dataset.name;
        calcLabel(el);
        dirty = true;
      }
    });
    preview();
    setTimeout(() => ta.focus(), 10);
  }

  // Double-clicking a card changes which fields it shows; a calculation, its formula
  editor.addEventListener('dblclick', (e) => {
    const card = e.target.closest('.record-card');
    if (card) { e.preventDefault(); recordDialog(card.dataset.record, card); return; }
    const calc = e.target.closest('.page-calc');
    if (calc) { e.preventDefault(); calcDialog(calc); }
  });

  // Typing @ (after a space) or [[ looks for a record to put there; closing the search puts the typing back
  editor.addEventListener('input', (e) => {
    if (e.inputType !== 'insertText' || !['@', '['].includes(e.data)) return;
    const sel = window.getSelection();
    const node = sel.rangeCount ? sel.anchorNode : null;
    if (!node || node.nodeType !== Node.TEXT_NODE) return;
    const at = sel.anchorOffset;
    const before = node.textContent.slice(0, at);
    const typed = e.data === '@' ? (/(^|[\s ])@$/.test(before) ? '@' : '') : (before.endsWith('[[') ? '[[' : '');
    if (!typed) return;
    const range = document.createRange();
    range.setStart(node, at - typed.length);
    range.setEnd(node, at);
    range.deleteContents();
    keep();
    pick('Link a record', null, (item) => recordDialog(item.id), () => place(esc(typed)));
  });

  // Ticking tasks while editing
  editor.addEventListener('click', (e) => {
    const li = e.target.closest('li.task');
    if (li && e.offsetX < 24) {
      li.dataset.checked = li.dataset.checked === 'true' ? 'false' : 'true';
      dirty = true;
    }
  });

  // Pictures and files
  document.getElementById('image-file').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const fd = new FormData();
    fd.append('file', file);
    try {
      const res = await fetch(form.dataset.upload, { method: 'POST', body: fd, credentials: 'same-origin', headers: { 'X-CSRFToken': window.OSMIA_CSRF } });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Upload failed');
      insert(data.image ? `<p><img src="${data.url}" alt="${esc(data.name)}"></p>` : `<p><a href="${data.url}">📎 ${esc(data.name)}</a></p>`);
    } catch (err) { OSMIA.toast(err.message, true); }
    e.target.value = '';
  });
  // Pasting a picture, or the address of a record in this Osmia (which becomes a link to it)
  const RECORD_URL = /^\s*(?:https?:\/\/([^/\s]+))?\/r\/(\d+)\/?\s*$/;
  editor.addEventListener('paste', async (e) => {
    const text = e.clipboardData ? e.clipboardData.getData('text/plain') : '';
    const m = RECORD_URL.exec(text);
    if (m && (!m[1] || m[1] === location.host)) {
      e.preventDefault();
      keep();
      try { place(recordLink(await fetchRecord(m[2]))); } catch (err) { restore(); document.execCommand('insertText', false, text); }
      return;
    }
    const item = [...(e.clipboardData || {}).items || []].find((i) => i.type.startsWith('image/'));
    if (!item) return;
    e.preventDefault();
    const input = document.getElementById('image-file');
    const dt = new DataTransfer();
    dt.items.add(item.getAsFile());
    input.files = dt.files;
    keep();
    input.dispatchEvent(new Event('change'));
  });

  // A small picker: a fixed list (views), or a search (records)
  function pick(title, items, onPick, onCancel) {
    const back = document.createElement('div');
    back.className = 'o-modal-back';
    back.innerHTML = `<div class="o-modal"><header><h3>${esc(title)}</h3><button type="button" class="btn small ghost">✕</button></header>
      <div class="body"><input type="search" placeholder="${items ? 'Find…' : 'Search every app…'}" style="width:100%;margin-bottom:8px"><div class="picker-list"></div></div></div>`;
    document.body.append(back);
    const input = back.querySelector('input'), list = back.querySelector('.picker-list');
    let picked = false;
    const close = () => { back.remove(); if (!picked && onCancel) onCancel(); };
    back.querySelector('header button').onclick = close;
    back.addEventListener('click', (e) => { if (e.target === back) close(); });
    const show = (rows) => {
      list.innerHTML = '';
      if (!rows.length) list.innerHTML = '<p class="muted">Nothing found.</p>';
      rows.slice(0, 60).forEach((r) => {
        const a = document.createElement('a');
        a.href = '#';
        a.innerHTML = `${esc(r.label)}${r.where ? ` <span class="muted small">${esc(r.where)}</span>` : ''}`;
        a.onclick = (e) => { e.preventDefault(); picked = true; close(); onPick(r); };
        list.append(a);
      });
    };
    let timer;
    input.addEventListener('input', () => {
      const q = input.value.trim().toLowerCase();
      if (items) { show(items.filter((i) => i.label.toLowerCase().includes(q))); return; }
      clearTimeout(timer);
      timer = setTimeout(async () => {
        if (!q) { show([]); return; }
        const res = await fetch(`${form.dataset.records}?q=${encodeURIComponent(q)}`, { credentials: 'same-origin' });
        show((await res.json()).records);
      }, 200);
    });
    input.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(); if (e.key === 'Enter') { e.preventDefault(); const a = list.querySelector('a'); if (a) a.click(); } });
    if (items) show(items); else list.innerHTML = '<p class="muted small">Type to search records in every app you can see.</p>';
    setTimeout(() => input.focus(), 10);
  }

  // Keyboard: Ctrl+S saves, Ctrl+K links
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); form.requestSubmit(); }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k' && editor.contains(document.activeElement)) {
      e.preventDefault();
      form.querySelector('[data-action="link"]').click();
    }
  });

  form.addEventListener('submit', () => { body.value = editor.innerHTML; dirty = false; });
  form.addEventListener('input', (e) => { if (e.target !== editor) dirty = true; });
  window.addEventListener('beforeunload', (e) => { if (dirty) { e.preventDefault(); e.returnValue = ''; } });
})();
