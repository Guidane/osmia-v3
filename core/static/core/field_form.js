/* The field editor: show the settings of the chosen type. */
(function () {
  'use strict';
  const form = document.getElementById('field-form');
  if (!form) return;
  const meta = JSON.parse(JSON.parse(document.getElementById('field-meta').textContent));
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const help = document.getElementById('type-help');

  function current() {
    const checked = form.querySelector('input[name=type]:checked');
    return checked ? checked.value : 'text';
  }
  function show() {
    const type = current();
    $$('.opt-section', form).forEach((s) => s.classList.toggle('on', s.dataset.types.split(' ').includes(type)));
    $$('.opt-section [data-types]', form).forEach((s) => { s.style.display = s.dataset.types.split(' ').includes(type) ? '' : 'none'; });
    help.textContent = meta.help[type] || '';
  }
  $$('input[name=type]', form).forEach((r) => r.addEventListener('change', show));
  show();

  // Choices
  const choices = document.getElementById('choices');
  let n = choices.children.length;
  document.getElementById('add-choice').addEventListener('click', () => {
    const row = document.createElement('div');
    row.className = 'choice-row';
    const color = meta.colors[n++ % meta.colors.length];
    row.innerHTML = `<span class="muted" style="cursor:grab">☰</span><input type="text" name="choice_value"><input type="color" name="choice_color" value="${color}"><button type="button" class="btn small ghost" data-remove-row>✕</button>`;
    choices.append(row);
    row.querySelector('input').focus();
  });
  choices.addEventListener('click', (e) => { if (e.target.closest('[data-remove-row]')) e.target.closest('.choice-row').remove(); });
  choices.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && e.target.name === 'choice_value') { e.preventDefault(); document.getElementById('add-choice').click(); }
  });

  // Lookup / rollup: the link, then a field of the linked table
  const link = document.getElementById('link'), targetField = document.getElementById('target_field');
  const field = meta.field;
  for (const l of meta.links) {
    const o = document.createElement('option');
    o.value = l.id; o.textContent = `${l.name} → ${(meta.tables[l.target] || {}).name || '?'}`;
    if (field && field.options && Number(field.options.link) === l.id) o.selected = true;
    link.append(o);
  }
  function fillTargets() {
    const l = meta.links.find((x) => String(x.id) === link.value);
    const want = targetField.dataset.value;
    targetField.innerHTML = '<option value="">—</option>';
    if (!l || !meta.tables[l.target]) return;
    for (const f of meta.tables[l.target].fields) {
      const o = document.createElement('option');
      o.value = f.id; o.textContent = f.name;
      if (String(f.id) === want) o.selected = true;
      targetField.append(o);
    }
  }
  link.addEventListener('change', () => { targetField.dataset.value = ''; fillTargets(); });
  fillTargets();

  // Formula helpers
  const expr = document.getElementById('expression');
  form.addEventListener('click', (e) => {
    const b = e.target.closest('[data-insert]');
    if (!b || !expr) return;
    const text = b.dataset.insert;
    const s = expr.selectionStart || expr.value.length, t = expr.selectionEnd || s;
    expr.value = expr.value.slice(0, s) + text + expr.value.slice(t);
    expr.focus();
    expr.selectionStart = expr.selectionEnd = s + text.length;
  });
})();
