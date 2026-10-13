"""Record the tutorials' animations from the real app.

    python manage.py make_tutorial_gifs            all of them
    python manage.py make_tutorial_gifs grid gantt only these

It starts a scratch Osmia (its own database in a temporary folder, with every
template and its sample records), drives it in a headless browser (Edge or
Chrome if installed, else Playwright's Chromium) with a visible cursor and a
mark for every click, and writes static/tutorials/<name>.gif. Run it again
after changing the pages, so the animations show what people see.

Needs Playwright: pip install -r requirements-dev.txt
"""
import io
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

OUT = Path(__file__).resolve().parents[2] / 'static' / 'tutorials'
WIDTH, HEIGHT = 1280, 800      # browser size
GIF_WIDTH = 960                # animation size
ADMIN = ('admin', 'tutorial-admin-pass')

# A drawn cursor and click marks: headless screenshots don't show the mouse.
CURSOR_JS = r"""
(() => {
  const svg = encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 22 22"><path d="M3 2 L3 18 L7.5 14 L10.5 20.5 L13.2 19.3 L10.3 13 L16.5 13 Z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>');
  const start = () => {
    if (document.getElementById('tut-cursor')) return;
    const c = document.createElement('div');
    c.id = 'tut-cursor';
    c.style.cssText = `position:fixed;left:0;top:0;width:22px;height:22px;z-index:2147483647;pointer-events:none;background:url("data:image/svg+xml,${svg}") no-repeat;`;
    document.documentElement.appendChild(c);
    const place = (x, y) => { c.style.transform = `translate(${x - 3}px, ${y - 2}px)`; try { sessionStorage.setItem('tut-cursor', JSON.stringify([x, y])); } catch (e) {} };
    try { const p = JSON.parse(sessionStorage.getItem('tut-cursor') || 'null'); if (p) place(p[0], p[1]); } catch (e) {}
    ['mousemove', 'dragover', 'drag', 'mousedown'].forEach((t) => document.addEventListener(t, (e) => { if (e.clientX || e.clientY) place(e.clientX, e.clientY); }, true));
    document.addEventListener('mousedown', (e) => {
      const r = document.createElement('div');
      r.style.cssText = `position:fixed;left:${e.clientX - 18}px;top:${e.clientY - 18}px;width:36px;height:36px;border-radius:50%;background:rgba(46,125,91,.35);border:2px solid rgba(46,125,91,.9);z-index:2147483646;pointer-events:none;transition:transform .45s,opacity .45s;`;
      document.documentElement.appendChild(r);
      requestAnimationFrame(() => { r.style.transform = 'scale(1.6)'; r.style.opacity = '0'; });
      setTimeout(() => r.remove(), 600);
    }, true);
  };
  // A caption at the bottom saying what happens; it stays across page loads.
  const caption = () => {
    let el = document.getElementById('tut-caption');
    if (!el) {
      el = document.createElement('div');
      el.id = 'tut-caption';
      el.style.cssText = 'position:fixed;left:50%;bottom:22px;transform:translateX(-50%);max-width:80%;z-index:2147483645;pointer-events:none;'
        + 'background:rgba(17,24,39,.9);color:#fff;font:600 22px/1.35 system-ui,Segoe UI,sans-serif;padding:10px 20px;border-radius:12px;'
        + 'box-shadow:0 6px 24px rgba(0,0,0,.25);text-align:center;display:none;';
      document.documentElement.appendChild(el);
    }
    return el;
  };
  window.__tutSay = (text) => {
    const el = caption();
    el.textContent = text || '';
    el.style.display = text ? 'block' : 'none';
    try { sessionStorage.setItem('tut-say', text || ''); } catch (e) {}
  };
  const restore = () => { try { window.__tutSay(sessionStorage.getItem('tut-say') || ''); } catch (e) {} };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => { start(); restore(); });
  else { start(); restore(); }
})();
"""

PREPARE = r"""
from django.contrib.auth import get_user_model
from core import blueprints
U = get_user_model()
U.objects.create_superuser('admin', 'admin@example.com', 'tutorial-admin-pass', first_name='Ada', last_name='Admin')
for name, first, last in [('alice', 'Alice', 'Martin'), ('bob', 'Bob', 'Jansen'), ('carla', 'Carla', 'Rossi')]:
    u = U(username=name, first_name=first, last_name=last); u.set_password('demo'); u.save()
blueprints.install_many(list(blueprints.available()), user=U.objects.get(username='admin'), sample=True)
"""


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class Recorder:
    """Frames of one animation: screenshots with how long each is shown."""

    def __init__(self, page):
        self.page = page
        self.frames = []
        self.x, self.y = WIDTH / 2, HEIGHT / 2
        self.say('')

    def say(self, text):
        """Show what happens next in the caption at the bottom."""
        try:
            self.page.evaluate('t => window.__tutSay && window.__tutSay(t)', text)
        except Exception:
            pass  # e.g. while a page is loading; the next page picks it up from sessionStorage

    def shot(self, ms=90):
        self.frames.append((self.page.screenshot(), ms))

    def hold(self, ms=1200):
        self.page.wait_for_timeout(150)
        self.shot(ms)

    def move_to(self, x, y, steps=8):
        for i in range(1, steps + 1):
            nx, ny = self.x + (x - self.x) * i / steps, self.y + (y - self.y) * i / steps
            self.page.mouse.move(nx, ny)
            if i % 2 == 0 or i == steps:
                self.shot(40)
        self.x, self.y = x, y

    def center(self, locator):
        locator.scroll_into_view_if_needed()
        box = locator.bounding_box()
        return box['x'] + box['width'] / 2, box['y'] + box['height'] / 2

    def click(self, target, wait=True, hold=350, say=None):
        if say:
            self.say(say)
        locator = self.page.locator(target) if isinstance(target, str) else target
        locator = locator.first
        x, y = self.center(locator)
        self.move_to(x, y)
        self.page.mouse.down()
        self.shot(60)
        self.page.mouse.up()
        if wait:
            try:
                self.page.wait_for_load_state('networkidle', timeout=5000)
            except Exception:
                pass
        self.page.wait_for_timeout(250)
        self.shot(hold)

    def type(self, text, per_word=True):
        words = text.split(' ')
        for i, w in enumerate(words):
            self.page.keyboard.type(w + (' ' if i < len(words) - 1 else ''), delay=25)
            if per_word:
                self.shot(70)
        self.shot(250)

    def fill(self, target, text, say=None):
        if say:
            self.say(say)
        self.click(target, wait=False, hold=200)
        self.page.keyboard.press('Control+a')
        self.type(text)

    def select(self, target, value=None, label=None, say=None):
        if say:
            self.say(say)
        locator = self.page.locator(target).first if isinstance(target, str) else target
        x, y = self.center(locator)
        self.move_to(x, y)
        if label is not None:
            locator.select_option(label=label)
        else:
            locator.select_option(value)
        self.page.wait_for_timeout(200)
        self.shot(450)

    def drag(self, source, dx=None, dy=None, target=None, steps=14, say=None):
        if say:
            self.say(say)
        src = self.page.locator(source).first if isinstance(source, str) else source
        x, y = self.center(src)
        self.move_to(x, y)
        if target is not None:
            tx, ty = self.center(self.page.locator(target).first if isinstance(target, str) else target)
        else:
            tx, ty = x + (dx or 0), y + (dy or 0)
        self.page.mouse.down()
        self.shot(80)
        for i in range(1, steps + 1):
            self.page.mouse.move(x + (tx - x) * i / steps, y + (ty - y) * i / steps)
            if i % 2 == 0:
                self.shot(50)
        self.page.mouse.up()
        self.x, self.y = tx, ty
        try:
            self.page.wait_for_load_state('networkidle', timeout=5000)
        except Exception:
            pass
        self.page.wait_for_timeout(900)
        self.shot(600)

    def goto(self, url, say=None):
        self.page.goto(url)
        if say is not None:
            self.say(say)
        self.page.wait_for_load_state('networkidle')
        self.shot(700)

    def save(self, name):
        from PIL import Image
        if not self.frames:
            return None
        images = [Image.open(io.BytesIO(png)).convert('RGB') for png, _ in self.frames]
        height = round(GIF_WIDTH * images[0].height / images[0].width)
        images = [im.resize((GIF_WIDTH, height), Image.LANCZOS) for im in images]
        palette = images[0].quantize(colors=192, method=Image.Quantize.MEDIANCUT)
        frames, durations = [], []
        for im, (_, ms) in zip(images, self.frames):
            q = im.quantize(palette=palette, dither=Image.Dither.NONE)
            if frames and q.tobytes() == frames[-1].tobytes():
                durations[-1] += ms  # same picture: show the previous one longer
                continue
            frames.append(q)
            durations.append(ms)
        durations[-1] = max(durations[-1], 2000)  # pause at the end before it starts over
        path = OUT / f'{name}.gif'
        frames[0].save(path, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True)
        return path


class Scenarios:
    """One method per animation; each starts from a page of the scratch Osmia."""

    def __init__(self, base, page):
        self.base = base
        self.page = page

    def url(self, path):
        return self.base + path

    def _row_cell(self, r, column):
        heads = [t.strip() for t in self.page.locator('#grid thead th').all_inner_texts()]
        idx = next(i for i, h in enumerate(heads) if h.endswith(column))
        return self.page.locator('#grid tbody tr[data-record]').first.locator('td').nth(idx)

    def tour(self, r):
        r.goto(self.url('/'), say='The home page: your own apps, and the apps you can see')
        r.hold(1600)
        r.click('#launcher > summary', wait=False, hold=1100, say='Open the app launcher: the grid at the top left')
        r.click('.launcher-tile:has-text("Orders")', say='Pick an app, e.g. Orders')
        r.say('Its tables are in the sidebar, its views are the tabs')
        r.hold(1600)
        r.click('.tabs a:has-text("By status")', say='Click a tab for another view of the same records')
        r.hold(1200)
        r.click('.kcard', say='Click a record to open it')
        r.say('Everything about one record on one page')
        r.hold(2000)

    def fields(self, r):
        r.goto(self.url('/a/tools/tools/fields/'), say='⚙ Fields lists the columns of a table')
        r.hold(900)
        r.click('a.btn:has-text("New field")', say='Click ＋ New field')
        r.fill('#name', 'Condition', say='Give it a name')
        r.click('.type-pick label:has-text("Single select")', wait=False, say='Pick its type: Single select')
        r.say('Add the choices; each gets a colour')
        for choice in ['Good', 'Worn', 'Broken']:
            r.click('#add-choice', wait=False, hold=120)
            r.type(choice)
        r.click('#field-form button.primary', say='Save')
        r.hold(1200)
        r.click('a.btn:has-text("New field")', say='Another one: ＋ New field')
        r.fill('#name', 'Uses', say='Name it')
        r.click('.type-pick label:has-text("Number")', wait=False, say='Type: Number')
        r.click('#field-form button.primary', say='Save')
        r.say('Both fields are on the table now')
        r.hold(2000)

    def grid(self, r):
        r.goto(self.url('/a/tasks/tasks/'))
        r.click('.tabs a:has-text("List")', say='Open the List view: a grid')
        cell = self.page.locator('#grid tbody tr[data-record]').first.locator('td.cell.primary')
        r.click(cell, wait=False, hold=500, say='Click a cell to select it')
        r.click(cell, wait=False, hold=500, say='Click it again to edit it')
        self.page.keyboard.press('Control+a')
        r.say('Type the new text')
        r.type('Count every shelf in rack A')
        r.say('Press Enter to save')
        self.page.keyboard.press('Enter')
        self.page.wait_for_timeout(700)
        r.hold(900)
        status = self._row_cell(r, 'Status')
        r.click(status, wait=False, hold=300, say='Select a status cell')
        r.click(status, wait=False, hold=700, say='Click again: the choices open')
        r.click('.editor .option:has-text("Blocked")', wait=False, say='Pick one: Blocked')
        self.page.wait_for_timeout(700)
        r.say('Saved straight away')
        r.hold(2000)

    def filter(self, r):
        r.goto(self.url('/a/tasks/tasks/'))
        r.click('.tabs a:has-text("List")', say='Open the List view')
        r.click('[data-pop="filter"]', wait=False, say='Click ⚲ Filter')
        r.click('.popover button:has-text("Add a filter")', wait=False, say='＋ Add a filter')
        r.select('.popover .row select >> nth=1', value='status', say='Pick the field: Status')
        r.select('.popover .row select >> nth=2', value='is', say='The condition: is')
        r.fill('.popover .row input[type=text]', 'In progress', say='The value: In progress')
        r.click('.popover button:has-text("Apply")', say='Apply')
        r.say('Only tasks that are in progress')
        r.hold(1500)
        r.click('[data-pop="sort"]', wait=False, say='Now ⇅ Sort')
        r.click('.popover button:has-text("Sort by")', wait=False, say='＋ Sort by')
        r.select('.popover .row select >> nth=0', value='due', say='Pick the field: Due')
        r.select('.popover .row select >> nth=1', value='desc', say='Latest first')
        r.click('.popover button:has-text("Apply")', say='Apply')
        r.say('"Save for everyone" keeps it in the view')
        r.hold(2200)

    def kanban(self, r):
        r.goto(self.url('/a/tasks/tasks/'), say='A kanban board: a column per status')
        r.hold(1300)
        r.drag('.column[data-value="To do"] .kcard', target='.column[data-value="In progress"] .cards',
               say='Drag a card to another column')
        r.say('Its status changed to In progress')
        r.hold(2000)

    def calendar(self, r):
        r.goto(self.url('/a/tasks/tasks/'))
        r.click('.tabs a:has-text("Calendar")', say='Open the Calendar view: tasks on their due date')
        r.hold(900)
        ev = self.page.locator('.calendar .ev[draggable="true"]').first
        day = ev.locator('xpath=ancestor::div[contains(@class,"day")]').get_attribute('data-date')
        target = (date.fromisoformat(day) + timedelta(days=2)).isoformat()
        if not self.page.locator(f'.day[data-date="{target}"]').count():
            target = (date.fromisoformat(day) - timedelta(days=2)).isoformat()
        r.drag(ev, target=f'.day[data-date="{target}"]', say='Drag a task to another day')
        self.page.reload()
        r.say('Its due date moved with it')
        r.hold(2200)

    def gantt(self, r):
        r.goto(self.url('/a/tasks/tasks/'))
        r.click('.tabs a:has-text("Gantt")', say='Open the Gantt view: a bar from start to due date')
        r.hold(1000)
        bar = self.page.locator('.gantt .bar').nth(1)
        r.drag(bar, dx=32 * 3, say='Drag a bar to move the task')
        self.page.wait_for_load_state('networkidle')
        r.say('Start and due date both moved 3 days')
        r.hold(1200)
        grip = self.page.locator('.gantt .bar .grip').nth(2)
        r.drag(grip, dx=32 * 4, say='Drag the right end to make it longer')
        self.page.wait_for_load_state('networkidle')
        r.say('Only the due date changed')
        r.hold(2200)

    def tree(self, r):
        r.goto(self.url('/a/budgets/budgets/'), say='A tree: budgets nested in budgets')
        r.hold(1300)
        r.click('#grid tbody tr[data-record] .toggle:not(.leaf) >> nth=1', wait=False, hold=900, say='Click ▾ to close a level')
        r.click('#grid tbody tr[data-record] .toggle:not(.leaf) >> nth=1', wait=False, hold=900, say='Click ▸ to open it again')
        r.click('[data-tree="collapse"]', wait=False, hold=1100, say='Collapse all')
        r.click('[data-tree="expand"]', wait=False, hold=2000, say='Expand all')

    def form(self, r):
        r.goto(self.url('/a/tasks/tasks/'))
        r.click('.tabs a:has-text("New task")', say='Open the form view "New task"')
        r.click('#record-form input[type=text] >> nth=0', wait=False, hold=200, say='Fill in the title')
        r.type('Replace the broken shelf in rack B')
        r.click('#record-form textarea', wait=False, hold=200, say='Describe it')
        r.type('The second shelf from the top is bent.')
        r.select('#record-form select >> nth=0', label='High', say='Pick a priority')
        r.click('#record-form button.primary', say='Send it')
        r.say('The task is added')
        r.hold(2200)

    def record(self, r):
        r.goto(self.url('/search/?q=PO-0001'), say='Search finds a record in any app')
        r.click('.card a.link-chip', say='Open it')
        r.hold(1000)
        r.click('.props .k:has-text("Notes") + .v', wait=False, hold=500, say='Click a value to change it')
        self.page.keyboard.press('Control+a')
        r.type('Connectors for the burn-in rack, deliver to bench 2')
        r.say('Ctrl+Enter saves')
        self.page.keyboard.press('Control+Enter')
        self.page.wait_for_timeout(700)
        r.hold(900)
        r.click('.comment-form textarea', wait=False, hold=200, say='Write a comment')
        r.type('Supplier confirmed delivery for Friday.')
        r.click('.comment-form button', say='Click Comment')
        r.click('.side-tabs button:has-text("History")', wait=False, hold=2400, say='History: who changed what, old → new')

    def button(self, r):
        r.goto(self.url('/a/orders/orders/'))
        r.click('.tabs a:has-text("Order pages")', say='Open the order pages')
        r.click('.list-pane a:has-text("PO-0003")', say='Pick a draft order')
        r.hold(1100)
        r.click('button.run-button:has-text("Place order")', wait=False, hold=700, say='Press Place order')
        self.page.wait_for_timeout(1500)
        r.say('An automation checked it and placed it')
        r.hold(1500)
        r.click('button.run-button:has-text("Receive everything")', wait=False, hold=700, say='Press Receive everything')
        self.page.wait_for_timeout(1800)
        r.say('The lines are booked into stock; the order is Received')
        r.hold(2400)

    def automation(self, r):
        r.goto(self.url('/a/tasks/automations/new/'), say='⚡ Automations › ＋ New automation')
        r.fill('#a-name', 'Tell the assignee when it is urgent', say='Give it a name')
        r.select('#trigger select', value='record_updated', say='When: a record is changed')
        r.click('#trigger label:has-text("Priority")', wait=False, hold=500, say='… only when its Priority changes')
        r.click('#conditions button:has-text("Condition")', wait=False, hold=400, say='If: ＋ Condition')
        r.select('#conditions .values-row select >> nth=0', value='priority', say='If Priority …')
        r.select('#conditions .values-row select >> nth=1', value='changed_to', say='If Priority changed to …')
        r.fill('#conditions .values-row input[type=text]', 'Urgent', say='If Priority changed to Urgent')
        r.select('#add-step', value='notify', say='Then: add a step, Notify people')
        step = self.page.locator('#steps .auto-step').last
        r.click(step.locator('label:has-text("Assignee")'), wait=False, hold=500, say='Tell the person in Assignee')
        message = step.locator('.field:has(> label:text-is("Message *")) input')
        r.click(message, wait=False, hold=200, say='The message; {Title} is filled in')
        r.type('{Title} is now urgent')
        r.click('#automation-form button.primary', say='Save')
        r.say('Saved: it runs from now on')
        r.hold(2200)

    def templates(self, r):
        r.goto(self.url('/admin/templates/'), say='⚙ › App templates: ready-made apps')
        r.hold(1400)
        r.say('Tick the ones you want, with sample records, and Install')
        for _ in range(4):
            self.page.mouse.wheel(0, 260)
            self.page.wait_for_timeout(250)
            r.shot(550)
        r.hold(1600)

    def designer(self, r):
        r.goto(self.url('/x/harness/designer/'), say='The harness designer')
        self.page.wait_for_timeout(1500)
        r.hold(1000)
        canvas = self.page.locator('#canvas')
        box = canvas.bounding_box()
        for label, (fx, fy) in [('Bench power supply', (0.22, 0.4)), ('Controller unit', (0.55, 0.38)), ('CAN test box', (0.82, 0.42))]:
            r.select('#device-select', label=self._device_option(label), say=f'Pick a device: {label}')
            r.say('Click the canvas to place it')
            r.move_to(box['x'] + box['width'] * fx, box['y'] + box['height'] * fy)
            self.page.mouse.down()
            r.shot(60)
            self.page.mouse.up()
            self.page.wait_for_timeout(400)
            r.shot(800)
        r.say('Now click one connector, then another, to wire them')
        r.hold(2400)

    def spaces(self, r):
        r.goto(self.url('/spaces/'), say='Spaces: the company, departments, teams, projects')
        r.hold(1400)
        r.click('a.btn:has-text("New space")', say='Click ＋ New space')
        r.fill('#name', 'Engineering', say='Name it')
        r.select('#kind', value='department', say='It is a department')
        r.fill('#description', 'We design and test the controllers.', say='Say what it is for')
        r.click('.checklist label:has-text("Tasks")', wait=False, hold=300, say='Use apps of the Company space here')
        r.click('.checklist label:has-text("Projects")', wait=False, hold=500)
        r.click('form button.primary', say='Make the space')
        r.say('The overview: what it is for, its pages, apps and members')
        r.hold(1800)
        r.click('a.btn:has-text("Space settings")', say='⚙ Space settings')
        row = self.page.locator('tr:has-text("Alice") select')
        r.select(row, value='editor', say='Add Alice as an editor')
        r.click('form button.primary >> nth=0', say='Save')
        r.say('Alice can now work in the space and its apps')
        r.hold(2000)

    def pages(self, r):
        r.goto(self.url('/x/pages/s/ENG/'), say='📄 Pages of the Engineering space')
        r.hold(1000)
        r.click('.template-pick:has-text("How-to")', say='Start from a template: How-to')
        r.fill('.title-input', 'Testing a controller', say='Give the page a title')
        r.click('#editor .panel.note p', wait=False, hold=200, say='Click into the page and write')
        self.page.evaluate('''() => { const p = document.querySelector('#editor .panel.note p'); const r = document.createRange();
            r.selectNodeContents(p); const s = getSelection(); s.removeAllRanges(); s.addRange(r);
            document.getElementById('editor').dispatchEvent(new KeyboardEvent('keyup')); }''')
        r.type('How we test every controller before it ships.')
        self.page.evaluate('''() => { const li = document.querySelector('#editor ol li'); const r = document.createRange();
            r.selectNodeContents(li); r.collapse(false); const s = getSelection(); s.removeAllRanges(); s.addRange(r);
            document.getElementById('editor').dispatchEvent(new KeyboardEvent('keyup')); }''')
        r.say('Fill in the steps')
        r.type('Connect the bench power supply')
        self.page.evaluate('''() => { const h = [...document.querySelectorAll('#editor h2')].pop(); const p = document.createElement('p');
            p.innerHTML = '<br>'; h.after(p); const r = document.createRange(); r.setStart(p, 0); r.collapse(true);
            const s = getSelection(); s.removeAllRanges(); s.addRange(r);
            document.getElementById('editor').dispatchEvent(new KeyboardEvent('keyup')); }''')
        r.click('[data-action="tasks"]', wait=False, hold=300, say='☑ Tasks adds a task list')
        r.type('Check the power supply')
        r.click('[data-action="view"]', wait=False, hold=600, say='⊞ View puts a live view of an app on the page')
        r.fill('.o-modal input', 'tasks › list', say='Pick the Tasks list')
        r.click('.o-modal .picker-list a', wait=False, hold=500)
        r.click('.edit-foot button.primary', say='Publish')
        r.say('The tasks on the page are live: always as they are now')
        self.page.mouse.wheel(0, 300)
        r.hold(1800)
        self.page.mouse.wheel(0, -300)
        r.click('.page-actions .star', say='📌 pins the page to your home page')
        r.hold(2000)

    def _device_option(self, name):
        labels = self.page.locator('#device-select option').all_inner_texts()
        return next((label for label in labels if label.startswith(name)), labels[-1])


class Command(BaseCommand):
    help = 'Record the tutorial animations (GIFs) from a scratch Osmia in a headless browser.'
    AS_USER = ['home', 'own_app']  # recorded as alice, who isn't an administrator
    ORDER = ['spaces', 'pages', 'tour', 'fields', 'grid', 'filter', 'kanban', 'calendar', 'gantt', 'tree', 'form', 'record', 'button',
             'automation', 'templates', 'designer']

    def add_arguments(self, parser):
        parser.add_argument('names', nargs='*', help=f'Which animations (default all): own_app {" ".join(self.ORDER)}')
        parser.add_argument('--keep', action='store_true', help='Keep the scratch data folder (its path is printed).')

    def handle(self, *args, names=(), keep=False, **options):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise CommandError('Playwright is needed: pip install -r requirements-dev.txt')
        wanted = list(names) or self.AS_USER + self.ORDER
        unknown = [n for n in wanted if n not in self.AS_USER and n not in self.ORDER]
        if unknown:
            raise CommandError(f'No animation called {", ".join(unknown)}.')
        OUT.mkdir(parents=True, exist_ok=True)
        base_dir = Path(settings.BASE_DIR)
        data_dir = Path(tempfile.mkdtemp(prefix='osmia-tutorials-'))
        env = {**os.environ, 'OSMIA_DATA_DIR': str(data_dir), 'PYTHONIOENCODING': 'utf-8'}
        self.stdout.write(f'Preparing a scratch Osmia in {data_dir} ...')
        subprocess.run([sys.executable, 'manage.py', 'migrate', '-v0'], cwd=base_dir, env=env, check=True)
        subprocess.run([sys.executable, 'manage.py', 'shell', '-c', PREPARE], cwd=base_dir, env=env, check=True,
                       stdout=subprocess.DEVNULL)
        port = free_port()
        server = subprocess.Popen([sys.executable, 'serve.py', '--port', str(port)], cwd=base_dir, env=env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        base = f'http://127.0.0.1:{port}'
        try:
            for _ in range(60):
                try:
                    urllib.request.urlopen(base + '/accounts/login/', timeout=2)
                    break
                except Exception:
                    time.sleep(0.5)
            with sync_playwright() as p:
                browser = self.launch(p)
                mine = [n for n in self.AS_USER if n in wanted]
                if mine:
                    self.record(browser, base, ('alice', 'demo'), mine, user=True)
                rest = [n for n in self.ORDER if n in wanted]
                if rest:
                    self.record(browser, base, ADMIN, rest)
                browser.close()
        finally:
            server.terminate()
            server.wait(timeout=10)
            if keep:
                self.stdout.write(f'The scratch data is kept in {data_dir}')
            else:
                shutil.rmtree(data_dir, ignore_errors=True)

    def launch(self, p):
        last = None
        for channel in ('msedge', 'chrome', None):
            try:
                return p.chromium.launch(channel=channel) if channel else p.chromium.launch()
            except Exception as exc:
                last = exc
        raise CommandError(f'No browser to record with ({last}). Run "playwright install chromium".')

    def record(self, browser, base, login, names, user=False):
        context = browser.new_context(viewport={'width': WIDTH, 'height': HEIGHT}, device_scale_factor=1)
        context.add_init_script(CURSOR_JS)
        page = context.new_page()
        page.goto(base + '/accounts/login/')
        page.fill('#id_username', login[0])
        page.fill('#id_password', login[1])
        page.click('button.primary')
        page.wait_for_load_state('networkidle')
        scenarios = Scenarios(base, page)
        for name in names:
            recorder = Recorder(page)
            try:
                if user:
                    getattr(self, name)(scenarios, recorder)
                else:
                    getattr(scenarios, name)(recorder)
                path = recorder.save(name)
                size = path.stat().st_size // 1024
                self.stdout.write(self.style.SUCCESS(f'  {name}.gif  {len(recorder.frames)} frames, {size} KB'))
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f'  {name}: {type(exc).__name__}: {str(exc).splitlines()[0]}'))
        context.close()

    @staticmethod
    def home(scenarios, r):
        page = scenarios.page
        r.goto(scenarios.url('/'), say='Your home page: your work, your to-dos, your space')
        r.hold(1600)
        r.click('.work-row', say='Assigned to me: open records where you are the assignee, owner, ...')
        r.say('Click ☆ to star a record')
        r.click('.star-form button', say='Click ☆ to star a record')
        r.hold(900)
        r.click('#launcher > summary', wait=False, hold=800, say='Back home: the app launcher …')
        page.goto(scenarios.url('/'))
        r.say('… or the Osmia logo')
        r.hold(600)
        r.click('.work-tabs button:has-text("Starred")', wait=False, hold=1200, say='Starred records stay here')
        r.click('.work-tabs button:has-text("Recent")', wait=False, hold=1200, say='Recent: what you opened lately')
        r.click('.todo-add input', wait=False, hold=200, say='Add a to-do: type it and press Enter')
        r.type('Order spare fuses')
        page.keyboard.press('Enter')
        page.wait_for_load_state('networkidle')
        r.hold(900)
        r.click('.todo-row input[type=checkbox]', wait=False, hold=1400, say='Tick it off when it is done')
        r.click('.home-quick a:has-text("Customise")', say='⚙ Customise: choose what your home page shows')
        r.hold(1600)
        r.say('… and who can see your space')
        r.hold(2000)

    @staticmethod
    def own_app(scenarios, r):
        page = scenarios.page
        r.goto(scenarios.url('/'), say='Everyone can make apps of their own')
        r.hold(1400)
        r.click('.home-quick a:has-text("New app")', say='Click ＋ New app')
        r.fill('#name', 'Maintenance', say='Name the app')
        r.fill('#table', 'Machines', say='… and its first table')
        r.click('form button.primary', say='Make the app')
        r.say("The table's fields: it starts with Name")
        r.hold(1200)
        r.click('a.btn:has-text("New field")', say='Add a field: ＋ New field')
        r.fill('#name', 'Next service', say='Name it')
        r.click('.type-pick label:has-text("Date")', wait=False, say='Type: Date')
        r.click('#field-form button.primary', say='Save')
        r.hold(900)
        r.click('.crumbs a', say='Back to the table')
        r.hold(900)
        r.click('#add-record', hold=900, say='Add a record')
        cell = page.locator('#grid tbody tr[data-record]').first.locator('td.cell.primary')
        r.click(cell, wait=False, hold=200, say='Click its name to fill it in')
        r.click(cell, wait=False, hold=300)
        r.type('Lathe')
        page.keyboard.press('Enter')
        page.wait_for_timeout(700)
        r.say('Your app is ready; only you see it')
        r.hold(2200)
