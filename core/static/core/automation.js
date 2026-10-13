/* The automation builder: When <trigger> · If <conditions> · Then <steps>.
 * Edits one JSON object, sent in the hidden "spec" field. */
(function () {
  'use strict';
  const meta = JSON.parse(JSON.parse(document.getElementById('builder-meta').textContent));
  const spec = JSON.parse(JSON.parse(document.getElementById('builder-initial').textContent));
  spec.trigger_config = spec.trigger_config || {};
  spec.conditions = spec.conditions || { match: 'all', rules: [] };
  spec.conditions.rules = spec.conditions.rules || [];
  spec.actions = spec.actions || [];
  const form = document.getElementById('automation-form');
  const $ = (s, r) => (r || document).querySelector(s);
  const el = (tag, attrs, ...kids) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === 'class') n.className = v;
      else if (k === 'text') n.textContent = v;
      else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
      else if (v !== undefined && v !== null && v !== false) n.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat()) if (kid !== null && kid !== undefined) n.append(kid);
    return n;
  };
  const NO_VALUE = new Set(meta.no_value);
  const CHANGE_OPS = [['changed', 'changed'], ['changed_to', 'changed to'], ['changed_from', 'changed from']];

  const table = (id) => meta.tables[Number(id)] || { fields: [], name: '?' };
  const fields = (id, pred) => table(id).fields.filter(pred || (() => true));
  const select = (options, value, onchange, blank) => {
    const s = el('select', { onchange: (e) => onchange(e.target.value) });
    if (blank !== undefined) s.append(el('option', { value: '', text: blank }));
    for (const [v, l] of options) s.append(el('option', { value: v, text: l, selected: String(v) === String(value ?? '') }));
    return s;
  };
  const field = (label, control, help) => el('div', { class: 'field' }, el('label', { text: label }), control, help ? el('div', { class: 'help', text: help }) : null);

  // -- Simple inputs ------------------------------------------------------------------
  form.querySelectorAll('[data-bind]').forEach((input) => {
    const key = input.dataset.bind;
    if (input.type === 'checkbox') input.checked = spec[key] !== false;
    else input.value = spec[key] ?? '';
    input.addEventListener(input.tagName === 'SELECT' ? 'change' : 'input', () => {
      spec[key] = input.type === 'checkbox' ? input.checked : (key === 'table' ? Number(input.value) : input.value);
      if (key === 'table') { spec.conditions.rules = []; render(); }
    });
  });
  if (!spec.table) spec.table = Number($('#a-table').value);

  // -- When ---------------------------------------------------------------------------
  function renderTrigger() {
    const box = $('#trigger');
    box.innerHTML = '';
    const cfg = spec.trigger_config;
    box.append(select(Object.entries(meta.triggers), spec.trigger, (v) => { spec.trigger = v; spec.trigger_config = {}; render(); }));
    if (meta.trigger_help[spec.trigger]) box.append(el('div', { class: 'help', text: meta.trigger_help[spec.trigger] }));
    if (spec.trigger === 'record_updated') {
      const chosen = new Set(cfg.fields || []);
      const list = el('div', { class: 'checklist', style: 'margin-top:8px' });
      for (const f of fields(spec.table, (f) => f.editable || ['attachment'].includes(f.type))) {
        list.append(el('label', {}, el('input', { type: 'checkbox', checked: chosen.has(f.key), onchange: (e) => {
          if (e.target.checked) chosen.add(f.key); else chosen.delete(f.key);
          cfg.fields = [...chosen];
        } }), ` ${f.name}`));
      }
      box.append(el('div', { class: 'help', text: 'Only when one of these changes (none ticked: any change):' }), list);
    }
    if (spec.trigger === 'date_reached') {
      box.append(el('div', { class: 'form grid2', style: 'margin-top:8px' },
        field('Date field', select(fields(spec.table, (f) => ['date', 'datetime', 'formula', 'lookup', 'rollup'].includes(f.type)).map((f) => [f.key, f.name]), cfg.field, (v) => { cfg.field = v; }, '—')),
        field('Days after the date (negative: before)', el('input', { type: 'number', value: cfg.offset || 0, oninput: (e) => { cfg.offset = Number(e.target.value); } })),
        field('At', el('input', { type: 'time', value: cfg.at || '08:00', oninput: (e) => { cfg.at = e.target.value; } }))));
    }
    if (spec.trigger === 'schedule') {
      cfg.every = cfg.every || 'day';
      box.append(el('div', { class: 'form grid2', style: 'margin-top:8px' },
        field('Every', select([['hour', 'hour'], ['day', 'day'], ['week', 'week'], ['month', 'month']], cfg.every, (v) => { cfg.every = v; renderTrigger(); })),
        cfg.every !== 'hour' ? field('At', el('input', { type: 'time', value: cfg.at || '08:00', oninput: (e) => { cfg.at = e.target.value; } })) : null,
        cfg.every === 'week' ? field('On', select([[1, 'Monday'], [2, 'Tuesday'], [3, 'Wednesday'], [4, 'Thursday'], [5, 'Friday'], [6, 'Saturday'], [7, 'Sunday']], cfg.weekday || 1, (v) => { cfg.weekday = Number(v); })) : null,
        cfg.every === 'month' ? field('On day', el('input', { type: 'number', min: 1, max: 28, value: cfg.day || 1, oninput: (e) => { cfg.day = Number(e.target.value); } })) : null),
      el('label', { class: 'inline' }, el('input', { type: 'checkbox', checked: cfg.per_record !== false, onchange: (e) => { cfg.per_record = e.target.checked; } }),
        ' Run for each record that meets the conditions (otherwise: once, without a record)'));
    }
  }

  // -- If -------------------------------------------------------------------------------
  function renderConditions() {
    const box = $('#conditions');
    box.innerHTML = '';
    const c = spec.conditions;
    const rows = el('div');
    c.rules.forEach((rule, i) => {
      const flds = fields(spec.table, (f) => f.type !== 'button');
      if (!rule.field && flds.length) rule.field = flds[0].key;
      const f = flds.find((x) => x.key === rule.field) || flds[0];
      let ops = (f ? f.ops : []).slice();
      if (['record_updated', 'record_created_or_updated'].includes(spec.trigger)) ops = ops.concat(CHANGE_OPS);
      if (!ops.find(([o]) => o === rule.op)) rule.op = ops.length ? ops[0][0] : 'is';
      const value = el('input', { type: 'text', value: rule.value || '', placeholder: 'value, or =formula', oninput: (e) => { rule.value = e.target.value; } });
      if (NO_VALUE.has(rule.op)) value.style.display = 'none';
      if (f && f.choices && f.choices.length && !NO_VALUE.has(rule.op)) value.setAttribute('list', `choices-${i}`);
      rows.append(el('div', { class: 'values-row', style: 'grid-template-columns:1fr 1fr 1fr 28px' },
        select(flds.map((x) => [x.key, x.name]), rule.field, (v) => { rule.field = v; rule.op = ''; renderConditions(); }),
        select(ops, rule.op, (v) => { rule.op = v; renderConditions(); }),
        value,
        el('button', { type: 'button', class: 'btn small ghost', text: '✕', onclick: () => { c.rules.splice(i, 1); renderConditions(); } }),
        f && f.choices ? el('datalist', { id: `choices-${i}` }, f.choices.map((ch) => el('option', { value: ch }))) : null));
    });
    if (!c.rules.length) rows.append(el('p', { class: 'muted small', text: 'Always (no conditions).' }));
    box.append(c.rules.length > 1 ? select([['all', 'All of these hold'], ['any', 'Any of these holds']], c.match, (v) => { c.match = v; }) : el('span'), rows,
      el('button', { type: 'button', class: 'btn small', text: '＋ Condition', onclick: () => { c.rules.push({ field: '', op: '', value: '' }); renderConditions(); } }),
      field('And this formula is true (optional)', el('input', { type: 'text', value: c.formula || '', placeholder: '{Part.On hand} < {Part.Reorder level}', oninput: (e) => { c.formula = e.target.value; } })));
  }

  // -- Then -----------------------------------------------------------------------------
  const linkFields = (tableId) => fields(tableId, (f) => f.type === 'link');

  function valuesTable(step, i) {
    const a = meta.actions[step.type];
    if (['create_record', 'find_or_create'].includes(step.type)) return step.table || null;
    if (step.type === 'update_record') {
      const t = step.target || 'this';
      if (t === 'this') return spec.table;
      if (t === 'item') { const l = linkFields(spec.table).find((f) => f.key === step.for_each); return l ? l.target : null; }
      if (t === 'found') {
        for (let j = i - 1; j >= 0; j--) {
          const prev = spec.actions[j];
          if (['create_record', 'find_or_create'].includes(prev.type)) return prev.table;
        }
        return null;
      }
      if (t.startsWith('link:item.')) {
        const l = linkFields(spec.table).find((f) => f.key === step.for_each);
        const inner = l ? linkFields(l.target).find((f) => f.key === t.slice(10)) : null;
        return inner ? inner.target : null;
      }
      if (t.startsWith('link:')) { const l = linkFields(spec.table).find((f) => f.key === t.slice(5)); return l ? l.target : null; }
    }
    return a ? spec.table : null;
  }

  function targetOptions(step) {
    const opts = [['this', 'This record']];
    for (const l of linkFields(spec.table)) opts.push([`link:${l.key}`, `Its ${l.name} (${table(l.target).name})`]);
    if (step.for_each) {
      opts.push(['item', 'Each linked record (for each)']);
      const l = linkFields(spec.table).find((f) => f.key === step.for_each);
      if (l) for (const inner of linkFields(l.target)) opts.push([`link:item.${inner.key}`, `Each linked record's ${inner.name}`]);
    }
    opts.push(['found', 'The record found or created in an earlier step']);
    return opts;
  }

  function valuesEditor(step, i, name) {
    step[name] = step[name] || {};
    const values = step[name];
    const tid = valuesTable(step, i);
    const box = el('div');
    if (!tid) { box.append(el('p', { class: 'muted small', text: 'Pick the table (or which records) first.' })); return box; }
    const flds = fields(tid, (f) => f.editable);
    for (const [key, value] of Object.entries(values)) {
      const f = flds.find((x) => x.key === key);
      const input = el('input', { type: 'text', value, placeholder: f && f.type === 'link' ? '=RECORD_ID() or ={Part}' : 'value, {Field} or =formula',
        oninput: (e) => { values[key] = e.target.value; } });
      if (f && f.choices && f.choices.length) {
        input.setAttribute('list', `vc-${i}-${key}`);
      }
      box.append(el('div', { class: 'values-row' },
        select(flds.map((x) => [x.key, `${x.name} (${x.type})`]), key, (v) => {
          const val = values[key]; delete values[key]; values[v] = val; renderSteps();
        }),
        input,
        el('button', { type: 'button', class: 'btn small ghost', text: '✕', onclick: () => { delete values[key]; renderSteps(); } }),
        f && f.choices ? el('datalist', { id: `vc-${i}-${key}` }, f.choices.map((ch) => el('option', { value: ch }))) : null));
    }
    const unused = flds.filter((f) => !(f.key in values));
    if (unused.length) {
      box.append(select(unused.map((f) => [f.key, f.name]), '', (v) => { if (v) { values[v] = ''; renderSteps(); } }, '＋ Set a field…'));
    }
    return box;
  }

  function checklist(items, chosen, onchange) {
    const set = new Set((chosen || []).map(String));
    const box = el('div', { class: 'checklist' });
    for (const [v, l] of items) {
      box.append(el('label', {}, el('input', { type: 'checkbox', checked: set.has(String(v)), onchange: (e) => {
        if (e.target.checked) set.add(String(v)); else set.delete(String(v));
        onchange([...set]);
      } }), ` ${l}`));
    }
    if (!items.length) box.append(el('span', { class: 'muted small', text: 'None.' }));
    return box;
  }

  function param(step, i, p) {
    const v = step[p.name];
    const set = (x) => { step[p.name] = x; };
    switch (p.type) {
      case 'target': return select(targetOptions(step), v || 'this', (x) => { set(x); renderSteps(); });
      case 'values': return valuesEditor(step, i, p.name);
      case 'table': return select(Object.values(meta.tables).filter((t) => t.writable).map((t) => [t.id, t.label]), v, (x) => { set(Number(x)); step.values = {}; step.match = {}; renderSteps(); }, '—');
      case 'link': return select(linkFields(spec.table).filter((f) => !f.multiple).map((f) => [f.key, f.name]), v, set, '— none');
      case 'user_fields': return checklist(fields(spec.table, (f) => ['user', 'created_by', 'modified_by'].includes(f.type)).map((f) => [f.key, f.name]), v, set);
      case 'users': return checklist(meta.users.map((u) => [u.id, u.name]), v, set);
      case 'teams': return checklist(meta.teams.map((t) => [t.id, t.name]), v, set);
      case 'automation': return select(meta.automations.filter((a) => a.name !== spec.name).map((a) => [a.id, `${a.name} (${table(a.table).name})`]), v, (x) => set(Number(x)), '—');
      case 'select': return select(p.choices, v, set, '—');
      case 'bool': return el('input', { type: 'checkbox', checked: !!v, onchange: (e) => set(e.target.checked) });
      case 'template':
        if (p.name === 'body') return el('textarea', { rows: 4, oninput: (e) => set(e.target.value) }, v || '');
        return el('input', { type: 'text', value: v || '', oninput: (e) => set(e.target.value) });
      default: return el('input', { type: 'text', value: v || '', oninput: (e) => set(e.target.value) });
    }
  }

  function renderSteps() {
    const box = $('#steps');
    box.innerHTML = '';
    spec.actions.forEach((step, i) => {
      const a = meta.actions[step.type];
      const body = el('div', { class: 'body form' });
      if (!a) {
        body.append(el('p', { class: 'error', text: `"${step.type}" is not available (an extension that is switched off?).` }));
      } else {
        if (a.help) body.append(el('p', { class: 'help', text: a.help }));
        if (step.type !== 'block' && linkFields(spec.table).some((f) => f.multiple)) {
          body.append(field('For each', select(linkFields(spec.table).filter((f) => f.multiple).map((f) => [f.key, `linked ${f.name.toLowerCase()} ({item.Field})`]),
            step.for_each, (x) => { step.for_each = x || undefined; renderSteps(); }, '— once'), 'Repeat this step for each record linked through a field.'));
        }
        for (const p of a.params) body.append(field(p.label + (p.required ? ' *' : ''), param(step, i, p), p.help));
        body.append(field('Only if (formula, optional)', el('input', { type: 'text', value: step.if || '', placeholder: '{Line count} = 0',
          oninput: (e) => { step.if = e.target.value || undefined; } }), 'Skip this step when the formula is not true.'));
      }
      box.append(el('div', { class: 'auto-step' },
        el('header', {}, el('span', { class: 'n', text: i + 1 }), el('b', { text: a ? `${a.icon} ${a.label}` : step.type, style: 'flex:1' }),
          el('button', { type: 'button', class: 'btn small ghost', text: '↑', disabled: i === 0, onclick: () => { spec.actions.splice(i - 1, 0, spec.actions.splice(i, 1)[0]); renderSteps(); } }),
          el('button', { type: 'button', class: 'btn small ghost', text: '↓', disabled: i === spec.actions.length - 1, onclick: () => { spec.actions.splice(i + 1, 0, spec.actions.splice(i, 1)[0]); renderSteps(); } }),
          el('button', { type: 'button', class: 'btn small ghost', text: '✕', onclick: () => { spec.actions.splice(i, 1); renderSteps(); } })),
        body));
    });
    if (!spec.actions.length) box.append(el('p', { class: 'muted small', text: 'No steps yet.' }));
  }

  const add = $('#add-step');
  for (const [k, a] of Object.entries(meta.actions)) add.append(el('option', { value: k, text: `${a.icon} ${a.label}` }));
  add.addEventListener('change', () => {
    if (!add.value) return;
    const step = { type: add.value };
    if (add.value === 'update_record') step.target = 'this';
    spec.actions.push(step);
    add.value = '';
    renderSteps();
  });

  function render() { renderTrigger(); renderConditions(); renderSteps(); }
  render();
  form.addEventListener('submit', () => {
    spec.table = Number($('#a-table').value);
    document.getElementById('spec').value = JSON.stringify(spec);
  });
})();
