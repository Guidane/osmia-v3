# Osmia 3

A no-code workspace in the spirit of NocoDB, built on Django. Administrators build **apps** on the website (tables,
typed fields, links between tables, views and automations), with no code and no migrations. Apps that need more
graphics than tables and views can offer get an **extension** (code), like the harness designer.

The apps from Osmia 2 (`example software/`) come along as **app templates**: Organisation, Tasks, Projects, Budgets,
Tools, Vendors, Parts, Stock, Orders and Assemblies, plus Devices and Harness with the harness extension. Their
behaviour (placing and receiving orders, booking stock at average cost, refusing to issue more than is on the shelf,
raising an assembly's revision, …) is built with automations, so you can read and change it on the website.

## Quick start (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python serve.py
```

Open http://127.0.0.1:8000. The first time, Osmia asks for the administrator account and which templates to
install (with sample records and demo users `alice`, `bob`, `carla`, password `demo`, if you like).

`serve.py` applies migrations, serves Osmia with waitress, runs scheduled automations every minute and restarts
Osmia after an extension is switched on or off. For real use set `OSMIA_DEBUG=0`, `OSMIA_SECRET_KEY` and
`OSMIA_ALLOWED_HOSTS`, and run `serve.py --host 0.0.0.0`. Everything Osmia keeps is in `data\` (or `OSMIA_DATA_DIR`):
the database and uploaded files.

Accounts and passwords are Django's: hashed passwords, password validation, password change and reset by email
(set `OSMIA_EMAIL_HOST`, `OSMIA_EMAIL_USER`, `OSMIA_EMAIL_PASSWORD`, `OSMIA_EMAIL_FROM`; without them the reset mail
is printed on the console). Administrators manage users and teams under ⚙.

## Spaces

Like Confluence or Jira, Osmia is organised in **spaces**: one for the company, and others for departments, teams and
projects. A space has a name, a short key (`ENG`), a kind, what it's for, who can see it (only its members, or everyone
who logs in), its members with their role (viewer, editor, space admin), its apps, its pages, and links to the records
it is about (its department, its budget, ...).

- Apps live in a space; other spaces add them as shortcuts, and tables link across spaces, so a department's own app
  can work with the company's Parts or Budgets. Templates are installed into the **Company** space (or a space you pick).
- A space role carries over to its apps: editors change records, space admins build its apps and pages and run the space.
- Making spaces needs the **Can make spaces** permission (⚙ → Users or Teams), or being an administrator.
- **Everyone's home page is their personal space**: their work across the apps (assigned to them, recently opened,
  starred), their to-dos and bookmarks, pinned pages, notifications, spaces and own apps. **⚙ Customise** chooses what it
  shows and who can see the space. Their to-dos and bookmarks are theirs alone, administrators included.

## Building an app

- **Apps** group tables and live in a space. ＋ New app (in your own space, or in a space you're an admin of), or install a template (⚙ → App templates). Any app can be downloaded as a
  template (with or without its records) from its settings and installed on another Osmia.
- **Fields**: text, long text, email, URL, phone, colour, number, currency, percent, rating, checkbox, date, date and
  time, single and multiple select (with optional rules for which choice may follow which), user, **link to records**
  (two-way: the other table gets the matching field), **lookup**, **rollup** (sum, count, average, min/max, … with an
  optional filter), **formula**, autonumber (`PO-0001`), files, created/changed at/by, record id, JSON and **button**
  (runs an automation). A field can be "set by automations only".
- **Views**: grid (edit cells in place, keyboard, copy/paste, group, totals, column widths), tree (nested by a parent
  link), kanban (drag cards between columns), gallery, calendar (drag to another day), gantt (drag bars, stretch their
  end, dependency arrows, progress), form, and detail (list and full record side by side). Filters, sorts, grouping and
  shown fields are set from the toolbar; "Save for everyone" keeps them in the view.
- **Record pages** show every field (click to edit), linked records as editable sub-tables (link, add a row, unlink),
  files, buttons, comments, the full history and the automations that ran.
- **Access**: every person can make apps in their own space; they build those as they like, and only they see them
  unless they let everyone look at them. Other apps are **read only** unless the person's role in the app's space, or a
  role an administrator gives them in the app's settings, lets them write (records, comments, files, buttons). Own apps can't link to apps their owner may only read (a link adds a field
  there), and their automations can't write to such apps (checked when saved and when they run).
- **Formulas** look like a spreadsheet's: `{Quantity} * {Unit price}`, `IF({Due} < TODAY(), "late", "")`; a path
  follows links: `{Part.Average cost}`, `SUM({Lines.Total})`. The field editor lists the functions.

## Automations

Every change goes through one service (`core/service.py`): grid edits, forms, the API, imports, buttons, extensions
and automations themselves. It validates the change, saves it with its links, writes the history and hands it to the
automation engine (`core/automation.py`).

- **When**: a record is created, changed (optionally: one of these fields), created or changed, about to be deleted,
  starts to meet conditions (e.g. "all its lines are received", "on hand at or below the reorder level"), a button is
  pressed, a comment is added, a date is reached (with an offset), or on a schedule.
- **If**: conditions on fields (including "changed to" / "changed from") and/or a formula.
- **Then** (in order, all or nothing): change records (this one, or linked ones), create a record, find or create a
  record, delete records, **stop the change with a message** (undoes the change that set it off), notify people, send
  an email, call a webhook, run another automation. Each step can repeat for each linked record and have an "only if"
  formula.

The Run log shows what every automation did, or why it failed. Automations setting each other off stop at 8 deep.
Without `serve.py`, run `manage.py run_automations` every minute (e.g. from Task Scheduler) for schedules and dates.

## Extensions

An extension is a Django app in `extensions/<name>/` with an `extension.json`; every one found is loaded unless
switched off on ⚙ → Extensions. In its `extension.py` it can register view types, field types, automation actions,
boxes on record pages and pages of its own, and it can bring templates in `blueprints/`. See `core/extensions.py`.

Extensions can also add sections to spaces' overviews and to people's home pages, links in a space's sidebar, and
search results.

`extensions/pages` is pages like Confluence's in every space: a page tree, a rich editor (headings, tables, task lists,
info/note/warning/success panels, pictures, links), **live views of any app**, and records inside pages: a link, a
**card** with the fields you pick (a budget's amount, spent and remaining), or **one live value in a sentence** ("we have
€12,400 left"), found with **⇄ Record**, by typing `@` or `[[`, or by pasting a record's address. A record's own page lists
the pages that mention it. **ƒ Calc** puts a calculation anywhere on a page, also in a page table's cell: a formula
(the same language as formula fields) over records put on the page with a name (`{budget.Remaining}`,
`{part.Unit cost}`), the cells of its own table row by their heading (`{Qty}`) and other named calculations, e.g.
`{part.Unit cost} * {labour.Rate} + {Qty}`. Readers always see the data as it is now, and only what they may see.
A page stays cheap with big tables: it works out at most 500 rows of a table and 1,000 calculations, follows at most
10,000 linked records in one step, and never loads a table of more than 50,000 records whole (see
`extensions/pages/calc.py`). Then
templates (meeting notes, how-to, decision, retrospective, project plan), labels, comments, version history with
restore, and pinning pages to your home page. Page HTML is cleaned against an allowlist when it's saved.

`extensions/harness` is the wire harness designer from Osmia 2, unchanged in the browser. It reads and writes the
Devices app (devices, connectors, pins, signals, pin maps) and the Harness app (projects, signal rules) through the
same service, so their history and automations apply. It adds a Designer page, a "Harness designer" view type, and
panels on device and project pages.

`extensions/assistant` (✨ AI in the top bar, and in each space's sidebar) changes Osmia with any AI chat, without an
API key: you describe a change; Osmia writes a prompt around it (the answer format, the field types, and the spaces,
apps, fields and pages you may see, records only if you tick the box) for you to paste into the AI; you paste its JSON
answer back. Osmia then tries every change inside a transaction with automations paused and undoes it, shows you each
change with ✓ or the exact problem (and a message to send back to the AI), and makes them only when you say so, all
or none, with your own permissions. It can make spaces, apps (tables, fields with links, lookups, rollups and
formulas, views, records), tables, fields, views and pages, and change apps, fields, records and pages; it never
deletes anything. Changes go through the same code as the website and show "AI assistant" in the history; every
request and what it changed is kept (`assistant.Run`). See `extensions/assistant/plan.py` for the answer format.

### Tutorials

`extensions/tutorials` has a tutorial for everything Osmia does (📖 Tutorials in the top bar), grouped from getting
started to administration; administrators' tutorials are shown to administrators only. The animations are recorded
from the app itself: after changing pages, run

```powershell
.\.venv\Scripts\python -m pip install -r requirements-dev.txt     # once: Playwright
.\.venv\Scripts\python manage.py make_tutorial_gifs                # or e.g. make_tutorial_gifs grid gantt
```

It starts a scratch Osmia with every template and its sample records, drives it in a headless browser (Edge or Chrome,
else `playwright install chromium`) and writes `extensions/tutorials/static/tutorials/*.gif`. The tutorials' text is
in `extensions/tutorials/content.py`.

## Developing

```powershell
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py install_templates --sample   # or: install_templates tasks orders
.\.venv\Scripts\python manage.py runserver
.\.venv\Scripts\python manage.py test
```

| Piece | Where |
|---|---|
| Workspace models (apps, tables, fields, records, links, views, automations, history) | `core/models.py` |
| Field types | `core/fieldtypes.py` |
| Formula language | `core/formula.py` |
| Reading values (computed fields, paths, caching) | `core/data.py` |
| All changes | `core/service.py` |
| Automations | `core/automation.py` |
| View types | `core/viewtypes.py` |
| Schema changes (paired links, renames, type changes) | `core/schema.py` |
| Templates (install / export) | `core/blueprints.py`, `blueprints/*.json` |
| Pages, builder, API | `core/views.py`, `core/build_views.py`, `core/api.py` |
| Accounts | `accounts/` |

Records keep their stored values in a JSON column and computed values are worked out when read, so a table is
comfortable up to some tens of thousands of records on SQLite.
