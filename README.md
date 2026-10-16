# Osmia 3

A no-code workspace on Django that brings a company's ways of tracking data together: things and transactions
(parts, stock, orders), work (tasks, projects) and documentation, in one structure. Administrators build **apps** on
the website (tables, typed fields, links between tables, views and automations), with no code and no migrations.
**Trees** give it structure (the organisation, programmes and projects, locations, ...), **access tags** decide who sees
which records, and **extension apps** (code) add what tables and views can't, like the harness designer.

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

## Structure: trees and spaces

The company is a forest of trees: the organisation (company → departments → teams → people), programmes and projects,
locations, part categories, ... A **tree** is any table whose records have a parent in the same table (⚙ Table
settings → its parent field). Records don't belong to one place: they **link** to the nodes of as many trees as they
need (a task links to its project, its team and the location it is about). Parent links never go round in a circle.

- A tree of **spaces** (Table settings → *Its records are spaces*) gives each node a **page** at `/s/<id>/`, showing what
  links to it and to the spaces under it (a programme shows the tasks of all its projects), the spaces under it and
  its Documentation pages. The Organisation and Projects templates are trees of spaces.
- **Everyone lands in their home space**: the record of a space table whose *home* user field is them (the
  Organisation template's *Person*), made for them at the top of the tree the first time they log in. An administrator
  moves it under their team.
- A space's page, and an app's **⌂ Home** tab, are pages made of blocks. **✎ Edit page** opens the editor: type `/` (or
  ＋ Add) for the slash menu: text styles, lists, task lists, tables, panels, **grids** (cells side by side; type `/`
  inside a cell), an app by its name (a small card that opens it), a live **view** of any app, a **record** (link, card
  or live value), a **calculation**, and **blocks** (My work, Notifications, Apps, Spaces under this one, Linked to this
  space, Pages of this space, Pinned pages, ...). Its people (the person, the manager: any user field naming them) and
  the editors of its app change a space's page. See `core/canvas/`.
- The **launcher** (the grid at the top left, or `/apps/`) has every app you can open as a small card, and the trees of
  spaces. Inside an app, its home and its tables are **tabs** along the top; a table's views are a second row of tabs.

## Access tags

People hold **access tags**; records, spaces and pages carry them. Something carrying tags is seen only by people who
hold **every one** of them, or with whom that one record was shared. Everyone else doesn't see it at all: not in
views, links, lookups, rollups and counts, search, history, notifications, pages or the AI assistant's prompt, and
not even that it's there. Tags are not ranks: holding one gives nothing in any other, and administrators are no
exception (they build every app, and see the records their tags allow). See `core/access.py`.

- A record carries its own tags and those of what it hangs under: its parent in a tree, and the spaces it links to
  (a link field can say otherwise). Tag a project, and its tasks and sub-projects carry the tag too.
- Only people who hold a tag put it on a record or take it off. A tag's **owners** give it to people and make other
  owners; every change is logged and the other owners are told (⚙ → 🏷 Access tags).
- Putting someone in a people field of a record they can't see asks first: **share this one record** with them (until
  it's closed or they're taken off it; the tag owners are told), or pick someone else.
- Automations see every record, whoever set them off; they only notify people who can see the record.
- What someone sends never drops the links they can't see: editing a project's tasks keeps the hidden ones.

## Building an app

- **Apps** group tables. ＋ New app (an app of your own; administrators also make apps for everyone), or install a
  template (⚙ → App templates); templates it needs are listed first and installed with it. Any app can be downloaded
  as a template (with or without its records) from its settings and installed on another Osmia.
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
- **Roles**: every person can make apps of their own; they build those as they like, and only they see them unless
  they let everyone look at them. Other apps are **read only** unless an administrator gives everyone, a team or a
  person another role in the app's settings (editor: records, comments, files, buttons; creator: also tables, fields,
  views, automations and the home page). Own apps can't link to apps their owner may only read (a link adds a field
  there), and their automations can't write to such apps. Which records anyone sees is up to the access tags.
- **Nothing is removed while something uses it.** Deleting an app, a table, a field, a view or an automation is refused
  while anything else needs it (lookups, rollups, formulas, links, automations, view filters and the fields views are
  built on, a tree's parent, pages showing it, apps whose template needs it, switched-on extensions), and the message
  lists what. What goes *with* something isn't in the way: the other half of a link, and what an app added to other
  apps' tables that only works with it. The plain fields an app added to other apps' tables stay there, with their
  values, as those tables' own (`Field.origin`). See `core/dependencies.py`.
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

## Extension apps

An extension is a Django app in `extensions/<name>/` with an `extension.json`. It is an **extension app**: made in code,
with fixed screens of its own, shown in the launcher like any app. It keeps its data in ordinary tables (often from the
templates it brings in `blueprints/`), and reads and writes them only through `core.data` and `core.service`, so
access tags, validation, history and automations apply. In its `extension.py` it can add a card to the launcher,
blocks for the slash menu, tabs to apps made from a template, view types, field types, automation actions, boxes on
record pages and search results. See `core/extensions.py`.

`extension.json` names what it **requires**: a template (`parts`), one of its tables (`parts.parts`) or a field
(`parts.parts.manufacturer`), by template keys, so renaming never breaks it. ⚙ → Extensions → **Switch on…** lists
what is missing and installs it with the extension, or nothing at all; while it is on, nothing it requires can be
removed. **Switch off…** removes only its code: everything it stored stays, as ordinary apps and fields, and switching
it on again brings its screens back over the same data. Switching off is refused while something uses what it brings
(a view of its view type, a field of its field type, an automation step of its action, its block on a page).

`extensions/docs` is the **Documentation** app: pages for people to read, with a section for each space, a page tree,
the slash editor (headings, tables, task lists, info/note/warning/success panels, pictures, links), **live views of any
app**, and records inside pages: a link, a **card** with the fields you pick, or **one live value in a sentence** ("we
have €12,400 left"), found with `/record`, by typing `@` or `[[`, or by pasting a record's address. A record's own page
lists the pages that mention it. `/calculation` puts a calculation anywhere on a page, also in a page table's cell: a
formula over records put on the page with a name (`{budget.Remaining}`), the cells of its own table row by their
heading (`{Qty}`) and other named calculations. Readers always see the data as it is now, and only what they may see. A
page stays cheap with big tables: it works out at most 500 rows of a table and 1,000 calculations, follows at most
10,000 linked records in one step, and never loads a table of more than 50,000 records whole (see
`core/canvas/calc.py`). Then templates (meeting notes, how-to, decision, retrospective, project plan), labels, comments,
version history with restore, and pins. A page carries its space's access tags, and can have its own. Page HTML is
cleaned against an allowlist when it's saved. Data belongs in apps: pages explain it and show it live.

`extensions/harness` is the wire harness designer from Osmia 2, unchanged in the browser. It reads and writes the
Devices app (devices, connectors, pins, signals, pin maps) and the Harness app (projects, signal rules) through the
same service, so their history and automations apply. It adds a card in the launcher, Designer tabs, a "Harness
designer" view type, and panels on device and project pages.

`extensions/assistant` (✨ AI assistant in the launcher) changes Osmia with any AI chat, without an API key: you describe
a change; Osmia writes a prompt around it (the answer format, the field types, and the trees of spaces, apps, fields
and pages you may see, records only if you tick the box) for you to paste into the AI; you paste its JSON answer back.
Osmia then tries every change inside a transaction with automations paused and undoes it, shows you each change with ✓
or the exact problem (and a message to send back to the AI), and makes them only when you say so, all or none, with
your own permissions. It can add spaces, make apps (tables, fields with links, lookups, rollups and formulas, views,
records), tables, fields, views and pages, and change apps, fields, records and pages; it never deletes anything.
Changes go through the same code as the website and show "AI assistant" in the history; every request and what it
changed is kept (`assistant.Run`). See `extensions/assistant/plan.py` for the answer format.

### Tutorials

`extensions/tutorials` has a tutorial for everything Osmia does (📖 Tutorials in the launcher), grouped from getting
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
| Workspace models (apps, tables, fields, records, links, views, automations, history, tags, layouts) | `core/models.py` |
| Trees, spaces and home spaces | `core/trees.py`, `core/space.py`, `core/space_views.py` |
| Access tags | `core/access.py` |
| What uses what (removal checks) | `core/dependencies.py` |
| Pages made of blocks: editor, sanitizer, rendering, calculations, blocks | `core/canvas/`, `core/static/core/editor.js` |
| Field types | `core/fieldtypes.py` |
| Formula language | `core/formula.py` |
| Reading values (computed fields, paths, caching) | `core/data.py` |
| All changes | `core/service.py` |
| Automations | `core/automation.py` |
| View types | `core/viewtypes.py` |
| Schema changes (paired links, renames, type changes) | `core/schema.py` |
| Templates (install / export) | `core/blueprints.py`, `blueprints/*.json` |
| Pages, builder, administration, API | `core/views.py`, `core/build_views.py`, `core/admin_views.py`, `core/api.py` |
| Accounts | `accounts/` |

Records keep their stored values in a JSON column and computed values are worked out when read, so a table is
comfortable up to some tens of thousands of records on SQLite.
