"""Take the tutorials' step-by-step pictures from the real app.

    python manage.py make_tutorial_pictures             all of them
    python manage.py make_tutorial_pictures grid gantt  only these

It starts a scratch Osmia (its own database in a temporary folder, with every
template and its sample records) and drives it in a headless browser (Edge or
Chrome if installed, else Playwright's Chromium). Every click, field filled in,
choice and drag is a step: a picture of the button or field and a little around
it, with a ring on what to click, and what to do as its caption. The steps are
written to static/tutorials/<name>/ (01.png, 02.png, ... and steps.json). Run it
again after changing the pages, so the pictures show what people see.

Needs Playwright: pip install -r requirements-dev.txt
"""
import io
import json
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
SCALE = 2                      # pictures are taken at twice the size, so they are sharp
PAD_X, PAD_Y = 110, 70         # how much is shown around what a step is about
MIN_W, MIN_H = 460, 170        # a picture is never smaller than this (CSS pixels)
ADMIN = ('admin', 'tutorial-admin-pass')

# A ring around what to click, drawn on the page just before its picture is taken
TARGET_JS = r"""
(() => {
  window.__tutRings = (boxes) => {
    document.querySelectorAll('.tut-ring').forEach((r) => r.remove());
    (boxes || []).forEach((b) => {
      const r = document.createElement('div');
      r.className = 'tut-ring';
      let place;
      if (b.width > b.height * 1.8) {   // something wide (a line, a menu entry): a rounded outline all round it
        const h = b.height + 14;
        place = `left:${b.x - 8}px;top:${b.y - 7}px;width:${b.width + 16}px;height:${h}px;border-radius:${Math.min(h / 2, 14)}px;`;
      } else {                          // a button, a box: a circle
        const d = Math.max(40, Math.min(Math.max(b.width, b.height) + 18, 96));
        place = `left:${b.x + b.width / 2 - d / 2}px;top:${b.y + b.height / 2 - d / 2}px;width:${d}px;height:${d}px;border-radius:50%;`;
      }
      r.style.cssText = `position:fixed;${place}border:3px solid #f59e0b;box-sizing:border-box;`
        + 'box-shadow:0 0 0 4px rgba(245,158,11,.25),0 0 14px rgba(245,158,11,.5);z-index:2147483646;pointer-events:none;';
      document.documentElement.appendChild(r);
    });
  };
})();
"""

# Where a step without a target of its own is: the slash menu, a dialog, a pop-up, or the caret
FOCUS_JS = r"""
() => {
  const box = (e) => { if (!e) return null; const r = e.getBoundingClientRect();
    return r.width && r.height ? {x: r.x, y: r.y, width: r.width, height: r.height} : null; };
  const shown = (s) => [...document.querySelectorAll(s)].find((e) => !e.hidden && e.offsetParent !== null);
  const menu = shown('.slash-menu');
  if (menu) return {box: box(menu), ring: box(menu.querySelector('.on'))};
  const modal = shown('.o-modal');
  if (modal) return {box: box(modal)};
  const pop = shown('.popover');
  if (pop) return {box: box(pop)};
  const a = document.activeElement;
  if (a && a.isContentEditable) {
    const s = getSelection();
    let r = s.rangeCount ? box(s.getRangeAt(0)) : null;
    if (!r && s.anchorNode) r = box(s.anchorNode.nodeType === 1 ? s.anchorNode : s.anchorNode.parentElement);
    if (r) return {box: r};
  }
  if (a && a !== document.body) return {box: box(a)};
  return null;
}
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


def union(*boxes):
    boxes = [b for b in boxes if b]
    x0, y0 = min(b['x'] for b in boxes), min(b['y'] for b in boxes)
    x1 = max(b['x'] + b['width'] for b in boxes)
    y1 = max(b['y'] + b['height'] for b in boxes)
    return {'x': x0, 'y': y0, 'width': x1 - x0, 'height': y1 - y0}


class Recorder:
    """The steps of one tutorial: a picture of what to click (or what changed) and what to do, in order.

    ``say`` gives the caption of the next step; ``click``, ``fill``, ``select`` and ``drag`` each make a step of
    their target (with a ring on it); a caption not used by one of them (``hold``, the end) makes a step of what
    the page shows: what was just changed, or the slash menu, a dialog, the caret."""

    def __init__(self, page):
        self.page = page
        self.steps = []          # (caption, png bytes, width, height)
        self.pending = ''        # the caption for the next step
        self.last = None         # the last thing clicked or filled in, to show what became of it
        self.typing = None       # (step number, field) of a click into a field: its picture is taken again once typed in

    # -- making steps ----------------------------------------------------------------------

    def _locator(self, target):
        return (self.page.locator(target) if isinstance(target, str) else target).first

    def _to_middle(self, locator):
        locator.evaluate("e => e.scrollIntoView({block: 'center', inline: 'center'})")
        self.page.wait_for_timeout(120)
        return locator.bounding_box()

    def _row(self, locator, box):
        """The box of the form row ``locator`` is in (its name and help with it), else ``box``."""
        row = locator.evaluate("""e => { const f = e.closest('.form .field'); if (!f) return null;
            const r = f.getBoundingClientRect(); return {x: r.x, y: r.y, width: r.width, height: r.height}; }""")
        return union(box, row) if row else box

    def _picture(self, around, rings=(), caption=None):
        """A step: the part of the page ``around`` a box, with rings on ``rings``."""
        caption = caption if caption is not None else self.pending
        self.pending = ''
        if not caption or not around:
            return
        x = around['x'] - PAD_X
        y = around['y'] - PAD_Y
        w = around['width'] + 2 * PAD_X
        h = around['height'] + 2 * PAD_Y
        if w < MIN_W:
            x, w = x - (MIN_W - w) / 2, MIN_W
        if h < MIN_H:
            y, h = y - (MIN_H - h) / 2, MIN_H
        # inside the window: moved in rather than cut off
        w, h = min(w, WIDTH), min(h, HEIGHT)
        x, y = min(max(0, x), WIDTH - w), min(max(0, y), HEIGHT - h)
        self.page.evaluate('b => window.__tutRings && window.__tutRings(b)', list(rings))
        png = self.page.screenshot(clip={'x': x, 'y': y, 'width': w, 'height': h})
        self.page.evaluate('() => window.__tutRings && window.__tutRings([])')
        self.steps.append((caption, png, round(w), round(h)))
        self.typing = None

    def _settle(self):
        """Wait for a page still loading (after a click that sends a form), so a picture isn't taken mid-way."""
        for state in ('load', 'networkidle'):
            try:
                self.page.wait_for_load_state(state, timeout=5000)
            except Exception:
                pass

    def _result(self):
        """A step of what the page shows now, for a caption no action used."""
        if not self.pending:
            return
        self._settle()
        try:
            focus = self.page.evaluate(FOCUS_JS)
        except Exception:   # the page changed under it: once more, on the new one
            self._settle()
            focus = self.page.evaluate(FOCUS_JS)
        if focus and focus.get('box'):
            self._picture(focus['box'], [focus['ring']] if focus.get('ring') else [])
            return
        if self.last is not None:
            try:
                if self.last.is_visible():
                    self._picture(self._to_middle(self.last))
                    return
            except Exception:
                pass
        # nothing in particular: the top of the page's content
        content = self.page.locator('.content, .main').first
        box = content.bounding_box() if content.count() else None
        if box:
            top = max(box['y'], 0)
            self._picture({'x': box['x'] + PAD_X, 'y': top + PAD_Y, 'width': min(box['width'], WIDTH) - 2 * PAD_X,
                           'height': min(380, HEIGHT - top) - PAD_Y})

    # -- what the scenarios do ---------------------------------------------------------------

    def say(self, text):
        """The caption of the next step (a caption still waiting gets a picture of its own first)."""
        if self.pending and text:
            self._result()
        self.pending = text or ''

    def hold(self, *_, show=None, **__):
        """A step of what the page shows now (``show``: the part to show, else what was just changed)."""
        if show is not None:
            self._settle()
            self.last = self._locator(show)
        self._result()

    shot = hold

    def click(self, target, wait=True, hold=None, say=None, show=None):
        """A step of ``target`` (and of ``show`` too: what the click acts on), then the click."""
        if say:
            self.say(say)
        locator = self._locator(target)
        box = self._to_middle(locator)
        around = union(box, self._locator(show).bounding_box()) if show is not None and self.pending else box
        field = locator.evaluate("e => e.matches('input, textarea') || e.isContentEditable")   # before: a click may leave the page
        self._picture(around, [box])
        made = len(self.steps)
        self.page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
        if made and field:
            self.typing = (made - 1, locator)
        self.page.wait_for_timeout(300)
        if wait:
            self._settle()
        self.last = locator

    def point(self, target, say=None):
        """A step showing what to click, without clicking it."""
        if say:
            self.say(say)
        box = self._to_middle(self._locator(target))
        self._picture(box, [box])

    def click_at(self, x, y, say=None):
        """A click on a spot of the page (a canvas) rather than on an element."""
        if say:
            self.say(say)
        spot = {'x': x - 10, 'y': y - 10, 'width': 20, 'height': 20}
        self._picture(spot, [spot])
        self.page.mouse.click(x, y)
        self.page.wait_for_timeout(400)

    def type(self, text, per_word=True):
        self.page.keyboard.type(text, delay=15)
        self.page.wait_for_timeout(200)
        if self.typing and not self.pending:
            # the field was just clicked: its step shows it with what was typed
            index, field = self.typing
            caption = self.steps[index][0]
            box = field.bounding_box()
            if box:
                self._picture(box, [box], caption=caption)
                self.steps[index] = self.steps.pop()
            self.typing = None
            return
        self._result()

    def fill(self, target, text, say=None):
        if say:
            self.say(say)
        locator = self._locator(target)
        box = self._to_middle(locator)
        self.page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
        self.page.keyboard.press('Control+a')
        self.page.keyboard.type(text, delay=15)
        self.page.wait_for_timeout(200)
        box = locator.bounding_box() or box
        self._picture(self._row(locator, box), [box])
        self.last = locator

    def select(self, target, value=None, label=None, say=None):
        if say:
            self.say(say)
        locator = self._locator(target)
        box = self._to_middle(locator)
        caption = self.pending
        self._picture(box, [box])          # before: what to open
        before = self.steps.pop() if self.steps and caption else None
        chosen = locator.select_option(label=label) if label is not None else locator.select_option(value)
        self.page.wait_for_timeout(250)
        if locator.is_visible() and locator.evaluate('e => e.value') in chosen:
            box = self._to_middle(locator)
            self._picture(self._row(locator, box), [box], caption=caption)   # after: what was chosen in it
        elif before:
            self.steps.append(before)      # it went back to its first entry (+ Add a step…): keep the one before
        self.last = locator

    def drag(self, source, dx=None, dy=None, target=None, steps=20, say=None):
        if say:
            self.say(say)
        src = self._locator(source)
        self._to_middle(src)
        if target is not None:
            dest = self._locator(target)
            dbox = dest.bounding_box()
        sbox = src.bounding_box()
        x, y = sbox['x'] + sbox['width'] / 2, sbox['y'] + sbox['height'] / 2
        if target is not None:
            tx, ty = dbox['x'] + dbox['width'] / 2, dbox['y'] + min(dbox['height'] / 2, 60)
        else:
            tx, ty = x + (dx or 0), y + (dy or 0)
        spot = {'x': tx - 10, 'y': ty - 10, 'width': 20, 'height': 20}
        self._picture(union(sbox, spot), [sbox, spot])
        self.page.mouse.move(x, y)
        self.page.mouse.down()
        for i in range(1, steps + 1):
            self.page.mouse.move(x + (tx - x) * i / steps, y + (ty - y) * i / steps)
        self.page.mouse.up()
        try:
            self.page.wait_for_load_state('networkidle', timeout=5000)
        except Exception:
            pass
        self.page.wait_for_timeout(900)
        self.last = None

    def move_to(self, x, y, steps=8):
        self.page.mouse.move(x, y, steps=steps)

    def center(self, locator):
        box = self._to_middle(locator)
        return box['x'] + box['width'] / 2, box['y'] + box['height'] / 2

    def goto(self, url, say=None):
        self.page.goto(url)
        self.page.wait_for_load_state('networkidle')
        self.last = None
        if say is not None:
            self.say(say)

    def save(self, name):
        """Write the steps to static/tutorials/<name>/: 01.png, 02.png, ... and steps.json."""
        from PIL import Image
        self._result()
        folder = OUT / name
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
        index = []
        for i, (caption, png, w, h) in enumerate(self.steps, 1):
            image = Image.open(io.BytesIO(png)).convert('RGB')
            # few colours: screens of an app keep their look and the files stay small
            image.quantize(colors=256, method=Image.Quantize.MEDIANCUT).save(folder / f'{i:02}.png', optimize=True)
            index.append({'image': f'{i:02}.png', 'caption': caption, 'width': w, 'height': h})
        (folder / 'steps.json').write_text(json.dumps(index, ensure_ascii=False, indent=1), 'utf-8')
        return folder


class Scenarios:
    """One method per tutorial; each starts from a page of the scratch Osmia."""

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
        r.goto(self.url('/'), say='You land on Home: your own page, and a tab for each role you hold')
        r.hold(1600)
        r.click('#launcher > summary', wait=False, hold=1100, say='The launcher: every app, and the trees of spaces')
        r.click('.launcher-tile:has-text("Orders")', say='Pick an app, e.g. Orders')
        r.say('Its home and its tables are tabs along the top')
        r.hold(1600)
        r.click('.app-tabs a:has-text("Orders")', say='A table')
        r.click('.tabs a:has-text("By status")', say='… and its views, one more row of tabs')
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

    def harness(self, r):
        r.goto(self.url('/search/?q=Burn-in rack loom'), say='Find the harness (or open it in the Harnesses app)')
        r.click('.card a.link-chip:has-text("Burn-in rack loom")', say='Open the harness')
        wires = self.page.locator('[id^="section-"]').filter(has_text='A contact')
        r.say('Its wires: side A and side B, the contacts side by side in the middle, then the wire details')
        r.hold(show=wires)
        head = wires.locator('.sub-group-head').first
        r.click(head.locator('.sub-group-add'), say='＋ on a sub-header adds a wire between those two connectors', show=head)
        r.fill('.field:has(> label:text-is("A function")) input', 'Fan', say='What it carries at the A end')
        r.fill('.field:has(> label:text-is("A contact")) input', '4', say='The contact on the A connector')
        r.fill('.field:has(> label:text-is("B contact")) input', '9', say='The contact on the B connector')
        r.fill('.field:has(> label:text-is("B function")) input', 'Fan in', say='What it carries at the B end')
        r.select('.field:has(> label:text-is("Set type")) select', value='Straight', say='Set type: straight, twisted, shielded')
        r.select('.field:has(> label:text-is("Colour")) select', value='yellow', say='Colour')
        r.fill('.field:has(> label:text-is("AWG")) input', '24', say='AWG')
        r.fill('.field:has(> label:text-is("Length (mm)")) input', '450', say='Length')
        r.click('#record-form button.primary', say='Save')
        r.say('The wire is in its place in the pinout')
        r.hold(show=self.page.locator('[id^="section-"]').filter(has_text='A contact'))

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
        r.point('input[name=templates] >> nth=0', say='Tick the templates you want')
        r.point('input[name=sample]', say='With sample records, to try them out')
        r.point('button.primary:has-text("Install the ticked templates")', say='… and install them')

    def spaces(self, r):
        r.goto(self.url('/apps/'), say='The trees of spaces: the organisation, programmes and projects')
        r.hold(1400)
        r.click('.space-row:has-text("Product development")', say='A programme is a space')
        r.say('Its page shows what links to it, and the spaces under it')
        r.hold(1800)
        r.click('a.btn:has-text("Edit page")', say='✎ Edit page')
        self.page.evaluate("""() => { const e = document.getElementById('editor'); const p = document.createElement('p');
            p.innerHTML = '<br>'; e.prepend(p); e.focus(); const r = document.createRange(); r.setStart(p, 0); r.collapse(true);
            const s = getSelection(); s.removeAllRanges(); s.addRange(r); }""")
        r.type('/heading 2', per_word=False)
        r.say('Type / for the slash menu')
        r.hold(700)
        self.page.keyboard.press('Enter')
        self.page.wait_for_timeout(300)
        r.type('Our dashboard')
        self.page.keyboard.press('Enter')
        r.type('/grid 2', per_word=False)
        r.say('A grid: cells side by side')
        r.hold(700)
        self.page.keyboard.press('Enter')
        self.page.wait_for_timeout(300)
        r.type('/tasks', per_word=False)
        r.say('In a cell, / again: an app as a small card')
        r.hold(700)
        self.page.keyboard.press('Enter')
        self.page.wait_for_timeout(300)
        self.page.evaluate("""() => { const c = document.querySelectorAll('#editor .grid-cell p')[1]; const r = document.createRange();
            r.setStart(c, 0); r.collapse(true); const s = getSelection(); s.removeAllRanges(); s.addRange(r); }""")
        r.type('/notifications', per_word=False)
        r.say('Blocks: My work, Notifications, Linked to this space, ...')
        r.hold(700)
        self.page.keyboard.press('Enter')
        self.page.wait_for_timeout(300)
        r.click('.edit-foot button.primary', say='Save')
        r.say('The space\'s own page')
        r.hold(2200)

    def pages(self, r):
        r.goto(self.url('/x/docs/'), say='📄 Documentation: a section for every space')
        r.hold(1000)
        r.click('.page-tree .tree-row:has-text("Engineering")', say='Engineering\'s pages')
        r.click('.template-pick:has-text("How-to")', say='Start from a template: How-to')
        r.fill('.title-input', 'Testing a controller', say='Give the page a title')
        r.click('#editor .panel.note p', wait=False, hold=200, say='Click into the page and write')
        self.page.evaluate("""() => { const p = document.querySelector('#editor .panel.note p'); const r = document.createRange();
            r.selectNodeContents(p); const s = getSelection(); s.removeAllRanges(); s.addRange(r);
            document.getElementById('editor').dispatchEvent(new KeyboardEvent('keyup')); }""")
        r.type('How we test every controller before it ships.')
        self.page.evaluate("""() => { const h = [...document.querySelectorAll('#editor h2')].pop(); const p = document.createElement('p');
            p.innerHTML = '<br>'; h.after(p); const r = document.createRange(); r.setStart(p, 0); r.collapse(true);
            const s = getSelection(); s.removeAllRanges(); s.addRange(r);
            document.getElementById('editor').dispatchEvent(new KeyboardEvent('keyup')); }""")
        r.type('/checklist', per_word=False)
        r.say('Type / for a checklist, a table, a panel, ...')
        r.hold(700)
        self.page.keyboard.press('Enter')
        self.page.wait_for_timeout(300)
        r.type('Check the power supply')
        self.page.keyboard.press('Enter')
        self.page.keyboard.press('Enter')
        r.type('/view', per_word=False)
        r.say('/view puts a live view of an app on the page')
        r.hold(700)
        self.page.keyboard.press('Enter')
        self.page.wait_for_timeout(300)
        r.fill('.o-modal input', 'tasks › list', say='Pick the Tasks list')
        r.click('.o-modal .picker-list a', wait=False, hold=500)
        r.click('.edit-foot button.primary', say='Publish')
        r.say('The tasks on the page are live: always as they are now')
        self.page.mouse.wheel(0, 300)
        r.hold(1800)
        self.page.mouse.wheel(0, -300)
        r.click('.page-actions .star', say='📌 pins the page: the Pinned pages block shows it')
        r.hold(2000)



class Command(BaseCommand):
    help = "Take the tutorials' step-by-step pictures from a scratch Osmia in a headless browser."
    AS_USER = ['home', 'tasks_home', 'add_tab', 'own_app']  # recorded as alice, who isn't an administrator
    ORDER = ['spaces', 'pages', 'tour', 'fields', 'grid', 'filter', 'kanban', 'calendar', 'gantt', 'tree', 'form', 'record', 'button',
             'automation', 'templates', 'harness']

    def add_arguments(self, parser):
        parser.add_argument('names', nargs='*', help=f'Which tutorials (default all): {" ".join(self.AS_USER + self.ORDER)}')
        parser.add_argument('--keep', action='store_true', help='Keep the scratch data folder (its path is printed).')

    def handle(self, *args, names=(), keep=False, **options):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise CommandError('Playwright is needed: pip install -r requirements-dev.txt')
        wanted = list(names) or self.AS_USER + self.ORDER
        unknown = [n for n in wanted if n not in self.AS_USER and n not in self.ORDER]
        if unknown:
            raise CommandError(f'No pictures called {", ".join(unknown)}.')
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
        context = browser.new_context(viewport={'width': WIDTH, 'height': HEIGHT}, device_scale_factor=SCALE)
        context.add_init_script(TARGET_JS)
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
                folder = recorder.save(name)
                size = sum(f.stat().st_size for f in folder.iterdir()) // 1024
                self.stdout.write(self.style.SUCCESS(f'  {name}/  {len(recorder.steps)} steps, {size} KB'))
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f'  {name}: {type(exc).__name__}: {str(exc).splitlines()[0]}'))
        context.close()

    @staticmethod
    def home(scenarios, r):
        page = scenarios.page
        r.goto(scenarios.url('/'), say='Home: your own page, with your work, notifications and apps')
        r.hold(1600)
        r.click('.work-row', say='Assigned to me: open records where you are the assignee, owner, ...')
        r.click('.star-form button', say='Click ☆ to star a record')
        r.hold(900)
        r.click('a.brand', say='Back home: Osmia, at the top left')
        r.click('.work-tabs button:has-text("Starred")', wait=False, hold=1200, say='Starred records stay here')
        r.click('.work-tabs button:has-text("Recent")', wait=False, hold=1200, say='Recent: what you opened lately')
        r.click('a.btn:has-text("Edit page")', say='Make it your own: ✎ Edit page')
        page.evaluate("""() => { const e = document.getElementById('editor'); const p = document.createElement('p');
            p.innerHTML = '<br>'; e.prepend(p); e.focus(); const r = document.createRange(); r.setStart(p, 0); r.collapse(true);
            const s = getSelection(); s.removeAllRanges(); s.addRange(r); }""")
        r.type('/projects', per_word=False)
        r.say('Type / and an app\'s name: a card that opens it')
        r.hold(900)
        page.keyboard.press('Enter')
        r.click('.edit-foot button.primary', say='Save')
        r.hold(2000)

    @staticmethod
    def tasks_home(scenarios, r):
        page = scenarios.page
        r.goto(scenarios.url('/'), say='Your tasks on your home page')
        r.hold(1200)
        r.click('a.btn:has-text("Edit page")', say='Click ✎ Edit page')
        r.click(page.locator('#editor > p').last, wait=False, say='Click the empty line at the end')
        r.type('/view', per_word=False)
        r.say('Type /view and press Enter')
        r.hold(900)
        page.keyboard.press('Enter')
        page.wait_for_timeout(300)
        r.shot(500)
        r.say('Find My tasks: the open tasks of whoever looks')
        r.type('My tasks', per_word=False)
        r.click('.picker-list a', wait=False, hold=700)
        view = page.locator('#editor .embed-view')
        r.move_to(*r.center(view))
        r.say('Point at it: ↑ in the bar above it moves it up, to the top')
        for _ in range(12):
            if page.evaluate("document.querySelector('#editor').firstElementChild.classList.contains('embed-view')"):
                break
            r.click('.piece-bar [data-move="up"]', wait=False, show=view)
        r.hold(600)
        r.click('.edit-foot button.primary', say='Click Save')
        r.say('Your tasks are at the top of your home page, always as they are now')
        r.hold()

    @staticmethod
    def add_tab(scenarios, r):
        page = scenarios.page
        r.goto(scenarios.url('/'), say='Home: your own page, and a tab for each role you hold')
        r.hold()
        r.click('.home-tab-add summary', wait=False, say='Click ＋ at the end of the tabs')
        r.fill('.home-tab-add input[name=title]', 'Week plan', say='Name the tab')
        r.click('.home-tab-add button', say='Click Add: its page opens in the editor')
        r.click(page.locator('#editor p').first, wait=False, say='Click into the page')
        r.type('/task list', per_word=False)
        r.say('Type / and what you want on it, e.g. /task list, and press Enter')
        r.hold()
        page.keyboard.press('Enter')
        page.wait_for_timeout(300)
        r.click('.edit-foot button.primary', say='Click Save')
        r.say('Your tab, next to Me; ✎ Edit page renames it or takes it away')
        r.hold()

    @staticmethod
    def own_app(scenarios, r):
        page = scenarios.page
        r.goto(scenarios.url('/'), say='Everyone can make apps of their own')
        r.hold(1400)
        r.click('#launcher > summary', wait=False, hold=900, say='Open the launcher')
        r.click('.launcher-foot a:has-text("New app")', say='Click ＋ New app')
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
