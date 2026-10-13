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
        insert(`<div class="embed-view" data-view="${item.id}" data-title="${esc(item.label)}">⊞ ${esc(item.label)}</div><p><br></p>`);
      });
    } else if (action === 'record') {
      keep();
      pick('Link a record', null, (item) => {
        insert(`<a class="record-ref" data-record="${item.id}" href="/r/${item.id}/">${esc(item.label)}</a>&nbsp;`);
      });
    }
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
  // Pasting a picture
  editor.addEventListener('paste', (e) => {
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
  function pick(title, items, onPick) {
    const back = document.createElement('div');
    back.className = 'o-modal-back';
    back.innerHTML = `<div class="o-modal"><header><h3>${esc(title)}</h3><button type="button" class="btn small ghost">✕</button></header>
      <div class="body"><input type="search" placeholder="${items ? 'Find…' : 'Search every app…'}" style="width:100%;margin-bottom:8px"><div class="picker-list"></div></div></div>`;
    document.body.append(back);
    const input = back.querySelector('input'), list = back.querySelector('.picker-list');
    const close = () => back.remove();
    back.querySelector('header button').onclick = close;
    back.addEventListener('click', (e) => { if (e.target === back) close(); });
    const show = (rows) => {
      list.innerHTML = '';
      if (!rows.length) list.innerHTML = '<p class="muted">Nothing found.</p>';
      rows.slice(0, 60).forEach((r) => {
        const a = document.createElement('a');
        a.href = '#';
        a.innerHTML = `${esc(r.label)}${r.where ? ` <span class="muted small">${esc(r.where)}</span>` : ''}`;
        a.onclick = (e) => { e.preventDefault(); close(); onPick(r); };
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
