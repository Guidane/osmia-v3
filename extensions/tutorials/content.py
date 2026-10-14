"""The tutorials: one per thing Osmia does.

Each tutorial has steps (HTML), an optional GIF (static/tutorials/<gif>.gif,
recorded from the real app with ``manage.py make_tutorial_gifs``), a place to
try it (``try_url``: a URL name) and who it's for:

    everyone   anyone who logs in
    builders   people who build apps (their own, or as creators)
    admins     administrators
"""
from dataclasses import dataclass, field


@dataclass
class Tutorial:
    slug: str
    title: str
    icon: str
    category: str
    summary: str
    steps: list
    gif: str = ''
    gif_caption: str = ''
    try_url: str = ''
    try_label: str = ''
    audience: str = 'everyone'
    tips: list = field(default_factory=list)
    related: list = field(default_factory=list)


CATEGORIES = [
    ('start', 'Getting started'),
    ('spaces', 'Spaces and pages'),
    ('build', 'Building apps'),
    ('views', 'Views'),
    ('records', 'Working with records'),
    ('automations', 'Automations'),
    ('admin', 'Administration'),
    ('extensions', 'Extensions'),
]

AUDIENCES = {'everyone': 'Everyone', 'builders': 'App builders', 'admins': 'Administrators'}

TUTORIALS = [
    # -- Getting started ------------------------------------------------------------------
    Tutorial(
        'tour', 'A tour of Osmia', '🧭', 'start',
        'What apps, tables, views and records are, and where everything is on the screen.',
        [
            'Osmia is a workspace of <b>apps</b>. An app (say <i>Orders</i>) has <b>tables</b> (<i>Orders</i>, <i>Order lines</i>), '
            'a table has <b>fields</b> (columns) and <b>records</b> (rows), and you look at a table through <b>views</b>: '
            'a grid, a kanban board, a calendar, a Gantt chart and more.',
            'The <b>top bar</b> starts with the <b>app launcher</b>: click the grid of squares at the far left to see your spaces and '
            'every app you can see as tiles. Type to narrow them down and press <kbd>Enter</kbd> to open the first. '
            'Then come the search box (it searches every app you can see), 🔔 your notifications, ⚙ the administration menu '
            '(administrators only) and your name, with your profile, password and log out.',
            'Apps live in <b>spaces</b> (see <a href="/tutorials/spaces/">Spaces</a>). Inside an app, the <b>sidebar</b> shows its space '
            'and the space\'s other apps; the open app lists its tables, and below them its automations, run log, history and settings '
            '(depending on what you may do there).',
            'The <b>home page</b> has your work across the apps and your to-dos (see <a href="/tutorials/home/">Your home page</a>), '
            '<i>My apps</i> (apps you made yourself) and <i>Apps</i> (the workspace\'s and '
            'colleagues\' apps), with what you may do in each: <span class="badge">read only</span>, '
            '<span class="badge ok">can edit</span> or <span class="badge ok">yours</span>.',
        ],
        gif='tour', gif_caption='Opening an app from the launcher, then a view and a record.',
        try_url='core:home', try_label='Open the home page',
        related=['own-app', 'access', 'grid'],
    ),
    Tutorial(
        'home', 'Your home page: your own space', '🏠', 'start',
        'Your work across all apps, your to-dos, pinned pages and bookmarks; you choose what it shows.',
        [
            'Your home page is your <b>personal space</b>. <b>Your work</b> has three tabs. <b>Assigned to me</b>: open records in any '
            'app where you are in a person field (assignee, owner, manager, keeper, ...), soonest due first; late ones are red. '
            'Finished records (Done, Received, Cancelled, ...) drop off by themselves. <b>Recent</b>: the records you opened lately. '
            '<b>Starred</b>: records you starred with ☆ next to their title.',
            '<b>My to-dos</b>: type in the box and press <kbd>Enter</kbd> to add one; tick it off when it\'s done. <b>All →</b> opens '
            'them with due dates, priorities, notes and a calendar. Your to-dos and bookmarks are yours alone, administrators included.',
            '<b>My pages</b> opens your own pages (see <a href="/tutorials/pages/">Pages</a>); pin any page with 📌 to have it under '
            '<i>Pinned pages</i>.',
            '<b>⚙ Customise</b> chooses what your home page shows, and in which order: your work, to-dos, pinned pages, bookmarks, '
            'notifications, spaces and apps. There you also choose who can see your space: only you, or everyone (they see the '
            'apps you share, never your to-dos).',
            'Apps you make yourself (<b>＋ New app</b>) live in your space.',
        ],
        gif='home', gif_caption='Starring a record, adding a to-do and ticking it off, then choosing what the home page shows.',
        try_url='core:home', try_label='Open your home page',
        related=['spaces', 'own-app', 'pages'],
    ),
    Tutorial(
        'spaces', 'Spaces', '◼', 'spaces',
        'A place for the company, a department, a team or a project: what it is for, who is in it, its apps and pages.',
        [
            'Open <b>◼ Spaces</b> on your home page (or <b>All spaces →</b> in the app launcher) to see the spaces you can see. '
            'The <b>Company</b> space has the apps everyone works with; departments, teams and projects have their own.',
            'To make one (you need the <i>Can make spaces</i> permission from an administrator) click <b>＋ New space</b>: a name, a short '
            '<b>key</b> (e.g. ENG), its kind, who can see it (<i>only members</i>, or <i>everyone can look</i>) and what it\'s for. '
            'Tick apps of other spaces to use here. You become its admin.',
            'A space\'s <b>overview</b> shows what it\'s for, its pages, its apps (its own, and ↗ the ones it uses from other spaces), what '
            'it\'s linked to and its members. Its sidebar has its pages and apps.',
            'In <b>⚙ Space settings</b>, space admins choose the <b>members</b>: people and teams as viewers (look), editors (also change '
            'records) or admins (also build its apps and pages and run the space). They tick the <b>apps from other spaces</b> to use, and '
            'link the space to <b>records</b> it is about, e.g. its department in Organisation or its budget in Budgets.',
            'Apps work across spaces: an app of one space can link to tables of another (Engineering\'s test bench app linking to the '
            'company\'s Parts, for instance), and its automations can use them, as far as you may.',
        ],
        gif='spaces', gif_caption='Making a department space, using company apps in it, and adding a member.',
        try_url='core:spaces', try_label='Open the spaces',
        related=['pages', 'access'],
    ),
    Tutorial(
        'pages', 'Pages', '📄', 'spaces',
        'Write pages in a space, like Confluence: how-tos, meeting notes, decisions, plans, with live views of your apps.',
        [
            'In a space, click <b>📄 Pages</b> in its sidebar (or a template on its overview). Pick a template: <b>Blank</b>, '
            '<b>Meeting notes</b>, <b>How-to</b>, <b>Decision</b>, <b>Retrospective</b> or <b>Project plan</b>.',
            'Give the page an emoji and a title and write. The toolbar has text styles (headings, quote, code block), bold, italic, '
            'underline, strike, code, links (<kbd>Ctrl</kbd>+<kbd>K</kbd>), lists, <b>☑ task lists</b>, tables, dividers, <b>info, note, '
            'warning and success panels</b> and pictures (or paste one).',
            '<b>⊞ View</b> puts a <b>live view</b> of any app on the page: a list of the project\'s tasks, the open orders, ... Readers see '
            'it as it is when they open the page, and only if they may see that app.',
            '<b>⇄ Record</b> (or type <kbd>@</kbd> or <kbd>[[</kbd>) finds a record in any app, then puts in a <b>link</b>, a <b>card</b> '
            'with the fields you tick (double-click a card to change them), or, by clicking a value, that <b>one live value</b> in your '
            'sentence: "Part 4471 has <b>12</b> in stock". Pasting a record\'s address makes a link. They stay live, and the record\'s '
            'own page shows <b>Mentioned in</b> with the pages that mention it.',
            '<b>ƒ Calc</b> does math on that data. Give records a name when you put them on the page (e.g. <i>part</i> and '
            '<i>labour</i>), then write a formula like <code>{part.Unit cost} * {labour.Rate} + {Qty}</code>: in a page table, '
            '<code>{Qty}</code> is the cell of the same row under the heading Qty. The dialog shows the result as you type; '
            'readers see it worked out from the data as it is now. Give a calculation a name to use it in another one.',
            'Add labels and press <b>Publish</b> (or <kbd>Ctrl</kbd>+<kbd>S</kbd>). <b>＋ Page under it</b> makes a child page; the '
            '<b>page tree</b> on the left shows them all. <b>⋯</b> copies the link, moves the page under another, or deletes it.',
            'Every save is a <b>version</b>: History lists them; open an old one and <b>Restore</b> it. Readers can <b>comment</b>, and '
            '<b>📌</b> pins a page to their home page. Pages are found by the search box too.',
            'Members who can edit records in the space can write pages; everyone who can see the space can read and comment.',
        ],
        gif='pages', gif_caption='Writing a how-to with a task list and a live view of tasks, then pinning it.',
        try_url='core:spaces', try_label='Open a space',
        related=['spaces', 'home'],
    ),
    Tutorial(
        'account', 'Your account and password', '👤', 'start',
        'Change your name, email and password, or get a new password if you forgot it.',
        [
            'Click your name at the top right and pick <b>Profile</b> to change your name, email, job title and phone.',
            'Pick <b>Change password</b> to choose a new one: type the old one once and the new one twice. Osmia refuses '
            'passwords that are too short, too common, all numbers or too much like your name.',
            'Forgot it? On the login page click <b>Forgot your password?</b> and give your email address; you get a link '
            'to choose a new one. (Your administrator sets up the mail; ask them if nothing arrives.)',
            '<b>Light / dark</b> in the same menu switches the colours; Osmia remembers your choice on this computer.',
        ],
        try_url='accounts:profile', try_label='Open your profile',
    ),
    Tutorial(
        'search', 'Search and notifications', '🔎', 'start',
        'Find any record in any app, and keep up with what automations tell you.',
        [
            'Type in the <b>search box</b> in the top bar and press <kbd>Enter</kbd>: Osmia looks through every field of '
            'every table you can see, and lists the matches per table. Click one to open it.',
            'In a view, the <b>Search…</b> box at the right of the toolbar searches that table only, and keeps the view\'s filters.',
            'Automations can send you <b>notifications</b> (for example "You have a task"). The 🔔 in the top bar shows how '
            'many are unread; click it to see them all. Clicking one opens the record it\'s about and marks it read; '
            '<b>Mark all as read</b> clears the count.',
        ],
        try_url='core:notifications', try_label='See your notifications',
    ),

    # -- Building apps -------------------------------------------------------------------
    Tutorial(
        'own-app', 'Make an app of your own', '🧩', 'build',
        'Everyone can make apps on their home page, and build them as they like.',
        [
            'On the home page, under <b>My apps</b>, click <b>＋ New app</b> (or <b>＋ New app</b> at the bottom of the app launcher).',
            'Give it a name, an icon (any emoji) and a colour, and the name of its first table, e.g. <i>Machines</i>. '
            'Click <b>Make the app</b>.',
            'Osmia opens the table\'s fields, so you can add the columns you need (see <a href="/tutorials/fields/">Fields</a>). '
            'Each table starts with a <i>Name</i> field and a grid view.',
            'Only you see the app. To let colleagues look at it, open <b>⚙ App settings</b> and set <i>Who can see it</i> '
            'to <b>Everyone can look at it</b>. They can\'t change it: only an administrator can give others edit access.',
            'Add more tables with <b>＋ Table</b> in the sidebar; link them together with link fields.',
        ],
        gif='own_app', gif_caption='Making an app with a first table, then adding a field.',
        try_url='core:app_create', try_label='Make an app', audience='everyone',
        tips=['Your own app can\'t link to apps you may only read (a link adds a field to the other table), and its '
              'automations can\'t change them. Ask an administrator for edit access if you need that.'],
        related=['fields', 'links', 'access'],
    ),
    Tutorial(
        'fields', 'Fields: the columns of a table', '🔤', 'build',
        'Add, change, reorder and delete fields, and pick the right type for each.',
        [
            'Open a table and click <b>⚙ Fields</b> at the top right (you need to be able to build the app). '
            'The list shows every field with its type and settings.',
            'Click <b>＋ New field</b>, give it a name and pick a <b>type</b>. The settings below change with the type:',
            '<ul><li><b>Text</b>, <b>Long text</b>, <b>Email</b>, <b>Link (URL)</b>, <b>Phone</b>, <b>Colour</b>, <b>JSON</b></li>'
            '<li><b>Number</b>, <b>Currency</b>, <b>Percent</b> (with decimals, lowest and highest), <b>Rating</b> (stars)</li>'
            '<li><b>Checkbox</b>, <b>Date</b>, <b>Date and time</b> (default <code>today</code> / <code>now</code>)</li>'
            '<li><b>Single select</b> and <b>Multiple select</b>: type the choices and pick their colours. For a single select you can '
            'say which choice may follow which, e.g. <code>Draft: Placed, Cancelled</code>.</li>'
            '<li><b>User</b>: one or several people who log in</li>'
            '<li><b>Link to records</b>, <b>Lookup</b>, <b>Rollup</b>: see <a href="/tutorials/links/">Linking tables</a></li>'
            '<li><b>Formula</b>: see <a href="/tutorials/formulas/">Formulas</a></li>'
            '<li><b>Autonumber</b> (<code>PO-0001</code>), <b>Files</b>, <b>Button</b>, and the automatic <b>Created at / by</b>, '
            '<b>Last changed at / by</b> and <b>Record id</b></li></ul>',
            'Tick <b>Required</b> to refuse records without it, <b>Names the records</b> to use it as the record\'s title, '
            'and <b>Set by automations only</b> for fields people shouldn\'t change by hand (e.g. an order\'s status).',
            'Drag the rows of the field list to reorder them and click <b>Save the order</b>. Renaming a field keeps formulas '
            'and automations that use it working. Changing a field\'s type converts the values that fit.',
        ],
        gif='fields', gif_caption='Adding a single select with coloured choices, and a number.',
        try_url='core:home', try_label='Open an app you build', audience='builders',
        tips=['Renaming a choice of a select renames it on every record.',
              'The key shown at the right of the field list never changes; templates and automations use it.'],
        related=['links', 'formulas'],
    ),
    Tutorial(
        'links', 'Linking tables: links, lookups and rollups', '⇄', 'build',
        'Connect records of different tables, show their values and add them up.',
        [
            'A <b>Link to records</b> field connects a record to records of another (or the same) table: an order to its supplier, '
            'a task to its parent task. Pick the table to link to and whether a record can link to several. Osmia adds the '
            'matching field to the other table: <i>Supplier</i> on orders makes <i>Orders</i> on vendors.',
            'A <b>Lookup</b> shows a field of the linked records, e.g. the supplier\'s email on the order. Pick the link and the field.',
            'A <b>Rollup</b> works something out over the linked records: the <i>sum</i> of the lines\' totals, the <i>count</i> of '
            'open tasks, the <i>earliest</i> due date. The optional filter formula counts only some of them, e.g. '
            '<code>{Status} = "Done"</code>.',
            'A link to the <b>same table</b> (e.g. <i>Part of</i> on locations or budgets) nests records: show them as a '
            '<a href="/tutorials/tree/">tree</a>.',
            'On a record\'s page, linked records are shown as a table you can edit in place; <b>⇄ Link</b> picks existing ones, '
            '<b>＋ Row</b> adds a new one.',
        ],
        try_url='core:home', try_label='Open an app you build', audience='builders',
        related=['formulas', 'record-page', 'tree'],
    ),
    Tutorial(
        'formulas', 'Formulas', 'ƒ', 'build',
        'Work out values from other fields, like a spreadsheet.',
        [
            'Add a field of type <b>Formula</b> and type the formula. Put field names in braces: <code>{Quantity} * {Unit price}</code>. '
            'Click a field or a function under the box to insert it.',
            'Operators: <code>+ - * /</code>, <code>&amp;</code> joins text, <code>= != &lt; &lt;= &gt; &gt;=</code> compare, '
            '<code>&amp;&amp;</code> and <code>||</code> combine.',
            'Functions include <code>IF</code>, <code>SWITCH</code>, <code>AND</code>, <code>OR</code>, <code>SUM</code>, <code>ROUND</code>, '
            '<code>CONCAT</code>, <code>LEFT</code>, <code>TODAY</code>, <code>DATEADD</code>, <code>DAYS</code>, <code>WORKDAYS</code>, '
            '<code>ISBLANK</code>, <code>IFERROR</code> and more; the field editor lists them all with what they do.',
            'A dot follows a link: <code>{Supplier.Email}</code> on an order, <code>SUM({Lines.Total})</code> for every line\'s total.',
            'Pick how to <b>show</b> the result: number, money, percent, date, yes / no or text, and the decimals.',
            'Examples: <code>IF({Due} &lt; TODAY(), "late", "")</code> · <code>DATEADD({Calibrated on}, 12, "months")</code> · '
            '<code>IF({Amount} &gt; 0, {Spent} / {Amount} * 100, 0)</code>',
        ],
        try_url='core:home', try_label='Open an app you build', audience='builders',
        tips=['A formula with a mistake isn\'t saved; Osmia says what\'s wrong. One that can\'t be worked out for a record shows #ERROR.'],
        related=['fields', 'automations'],
    ),
    Tutorial(
        'csv', 'Importing and exporting CSV', '⬆', 'build',
        'Bring records in from a spreadsheet, or take them out.',
        [
            'In any view, open <b>⋯</b> at the top right and pick <b>⬇ Download CSV</b>: you get the records of the view, '
            'with its filters and search, one column per field.',
            'To bring records in, pick <b>⬆ Import CSV</b> and choose a file whose first row names the fields. Links take the '
            'names of the linked records (several separated by commas). Columns that match no field are left out.',
            'Tick <b>Run the table\'s automations</b> if the new records should be handled like ones added by hand. '
            'Osmia reports how many records it added, and which rows it couldn\'t, with why.',
        ],
        try_url='core:home', try_label='Open an app', audience='everyone',
    ),

    # -- Views -----------------------------------------------------------------------------
    Tutorial(
        'views', 'Views: different ways to look at a table', '👁', 'views',
        'Add views, switch between them and change their settings.',
        [
            'A table\'s views are the tabs under its name. Each view keeps its own filters, sorts, grouping and shown fields, '
            'so the same records can be a list, a board and a calendar.',
            'To add one, click <b>＋ View</b> at the end of the tabs and pick a kind: <b>Grid</b>, <b>Tree</b>, <b>Kanban</b>, '
            '<b>Gallery</b>, <b>Calendar</b>, <b>Gantt</b>, <b>Form</b> or <b>Detail</b> (and kinds that extensions add). '
            'Kinds that need a field the table doesn\'t have (a date for a calendar) aren\'t offered.',
            '<b>⋯ › View settings</b> renames it, picks its fields (kanban columns, calendar date, Gantt start and end, …), '
            'reorders the tabs, duplicates or deletes it.',
        ],
        try_url='core:home', try_label='Open an app', audience='builders',
        related=['grid', 'filter', 'kanban', 'calendar', 'gantt', 'tree', 'gallery', 'form'],
    ),
    Tutorial(
        'grid', 'The grid: a spreadsheet of records', '▦', 'views',
        'Edit cells in place, with the mouse or the keyboard.',
        [
            'Click a cell to select it, click again (or double-click, or press <kbd>Enter</kbd>) to edit it. Each type has its '
            'own editor: a text box, a date picker, a list of choices, stars, or the record picker for links.',
            'Press <kbd>Enter</kbd> to save and go down, <kbd>Tab</kbd> to save and go right, <kbd>Esc</kbd> to cancel. '
            'Arrow keys move around; just start typing to replace a text or number.',
            '<kbd>Delete</kbd> empties the cell; <kbd>Ctrl</kbd>+<kbd>C</kbd> copies it and <kbd>Ctrl</kbd>+<kbd>V</kbd> pastes '
            'into it. A checkbox changes with one click.',
            'Drag the edge of a column title to make it wider; the view remembers it. Number columns get a total at the bottom.',
            'Hover over a row number and click ⤢ to open the whole record. <b>Add a record</b> under the last row adds one.',
            'If a value isn\'t allowed (a required field left empty, a choice that may not follow the one before, an automation '
            'that refuses it) the cell turns red and Osmia says why.',
        ],
        gif='grid', gif_caption='Editing a text cell and a status in the grid.',
        try_url='core:home', try_label='Open an app',
        related=['filter', 'record-page'],
    ),
    Tutorial(
        'filter', 'Filter, sort, group and choose fields', '⚲', 'views',
        'Show just the records you want, in the order you want.',
        [
            '<b>⚲ Filter</b> in the toolbar: <b>＋ Add a filter</b>, pick a field, a condition (is, contains, is more than, is empty, '
            'is today, is me, …) and a value. Choose <i>All of these</i> or <i>Any of these</i>; a formula can be added too. '
            'Click <b>Apply</b>.',
            '<b>⇅ Sort</b>: add one or more fields, A → Z or Z → A. Empty values go last.',
            '<b>☰ Group</b> (grid and Gantt): groups the records by a field, e.g. by status or by supplier.',
            '<b>◫ Fields</b>: tick the fields to show and drag them into order.',
            'What you apply is just for you, in the address bar (you can bookmark it). People who build the app can click '
            '<b>💾 Save for everyone</b> to keep it in the view. <b>✕ Reset</b> goes back to the view as saved.',
        ],
        gif='filter', gif_caption='Filtering tasks by status, then sorting them.',
        try_url='core:home', try_label='Open an app',
        related=['grid', 'views'],
    ),
    Tutorial(
        'kanban', 'Kanban boards', '▥', 'views',
        'Cards in columns, moved on by dragging.',
        [
            'A kanban view puts each record on a card, in a column per value of a single select (e.g. <i>Status</i>), a user or a '
            'single link. Set it with <b>Columns by</b> in the view settings, with the cover picture and the fields on the cards.',
            '<b>Drag a card</b> to another column to change that field. If the change isn\'t allowed, the card goes back and Osmia '
            'says why.',
            'Click a card to open the record; <b>＋ Add</b> under a column adds one.',
        ],
        gif='kanban', gif_caption='Dragging a task from To do to In progress.',
        try_url='core:home', try_label='Open an app',
    ),
    Tutorial(
        'calendar', 'Calendars', '📅', 'views',
        'Records on the days of a month, moved by dragging.',
        [
            'A calendar view shows each record on its date (pick the <b>Date</b> field in the view settings, optionally an '
            '<b>Until</b> date for records that last several days, and a field to colour them by).',
            'Use <b>←</b>, <b>Today</b> and <b>→</b> to change month. <b>Drag a record</b> to another day to move it; one that lasts '
            'several days keeps its length.',
            'Hover over a day and click <b>＋</b> to add a record on that day.',
        ],
        gif='calendar', gif_caption='Moving a task to another day.',
        try_url='core:home', try_label='Open an app',
    ),
    Tutorial(
        'gantt', 'Gantt charts', '▤', 'views',
        'A timeline of bars from start to end, with dependencies.',
        [
            'A Gantt view draws a bar from each record\'s <b>Start</b> to its <b>End</b>. In the view settings you can also group the '
            'bars, colour them, show <b>Progress</b> as a shaded part of the bar and draw arrows from the tasks each one '
            '<b>Depends on</b>.',
            '<b>Drag a bar</b> to move it (start and end together); drag its right end to make it longer or shorter.',
            'Choose <b>Days</b>, <b>Weeks</b> or <b>Months</b>; <b>⌖ Today</b> scrolls back to today (the red line). Records without '
            'dates are listed under the chart.',
        ],
        gif='gantt', gif_caption='Moving a bar and stretching another.',
        try_url='core:home', try_label='Open an app',
    ),
    Tutorial(
        'tree', 'Trees: nested records', '🌳', 'views',
        'Budgets in budgets, shelves in racks, subtasks under tasks.',
        [
            'A tree view needs a link from the table to itself that points at the parent (e.g. <i>Part of</i>). Pick it as the '
            '<b>Parent field</b> in the view settings.',
            'Click ▸ / ▾ to open or close a level (Osmia remembers what you leave open), or use <b>⊞ Expand all</b> and '
            '<b>⊟ Collapse all</b>.',
            'When you filter or search, matching records are shown with the records above them, so you can see where they are.',
            'Rollups and formulas that go through the children (e.g. a budget\'s <i>Spent</i> including its sub-budgets) are shown per level.',
        ],
        gif='tree', gif_caption='Collapsing and opening budgets.',
        try_url='core:home', try_label='Open an app',
    ),
    Tutorial(
        'gallery', 'Gallery and detail views', '▩', 'views',
        'Cards with pictures, and a list with the whole record beside it.',
        [
            'A <b>gallery</b> shows each record as a card with its first picture (pick the <b>Cover picture</b> field) and a few '
            'fields. Good for parts, tools and devices.',
            'A <b>detail</b> view has the records in a list on the left and the selected record, with everything on its page, on the '
            'right. Click through the list to go from record to record without leaving the view.',
        ],
        try_url='core:home', try_label='Open an app',
        related=['record-page'],
    ),
    Tutorial(
        'form', 'Forms', '☰', 'views',
        'A tidy page to add records, e.g. to ask for a task.',
        [
            'Add a view of kind <b>Form</b>. In its settings choose the fields on it (and their order), a title, a text above the form, '
            'the button text and the message after sending.',
            'People who may edit the app fill it in and click the button; the record is added (and the table\'s automations run). '
            'Required fields must be filled in.',
            'Any table also has a full form under <b>＋ New</b> at the top right.',
        ],
        gif='form', gif_caption='Asking for a task with a form.',
        try_url='core:home', try_label='Open an app',
    ),

    # -- Records --------------------------------------------------------------------------------
    Tutorial(
        'record-page', 'A record\'s page', '📄', 'records',
        'Everything about one record: its fields, linked records, files, comments and history.',
        [
            'Open a record by clicking it in a kanban, gallery or calendar, or ⤢ next to its row in a grid.',
            'Its fields are listed on the left; <b>click a value to change it</b>, just like in the grid.',
            'Records linked to it (an order\'s lines, a project\'s tasks) are tables below, which you can edit in place. '
            '<b>⇄ Link</b> picks existing records, <b>＋ Row</b> adds a new one linked to this record, <b>＋ Form</b> opens the full '
            'form, ✕ unlinks one.',
            'Buttons (e.g. <i>Place order</i>) are next to the title; <b>▶ Run</b> has the automations you can run by hand.',
            'On the right: <b>Comments</b>, the <b>History</b> (who changed what, old → new, and which automation did it) and the '
            '<b>Automations</b> that ran for this record. ↑ ↓ go to the previous and next record; ⋯ deletes it.',
        ],
        gif='record', gif_caption='Changing a value on a record page and adding a comment.',
        try_url='core:home', try_label='Open an app',
        related=['files', 'buttons'],
    ),
    Tutorial(
        'files', 'Files and pictures', '📎', 'records',
        'Attach photos, PDFs, drawings and documents to records.',
        [
            'Tables can have <b>Files</b> fields (e.g. <i>Pictures</i>, <i>Shipping documents</i>). On a record\'s page each one has '
            'its own box: drop files on it, or click it to choose them.',
            'Pictures are turned upright, scaled down to at most 2000 px and stripped of camera and GPS data. Each file can be up to 20 MB.',
            'Click a file to open it (pictures and PDFs open in the browser); hover over it and click ✕ to remove it.',
            'The first picture is the record\'s cover in galleries and kanban boards.',
        ],
        try_url='core:home', try_label='Open an app',
    ),
    Tutorial(
        'buttons', 'Buttons', '▶', 'records',
        'One click to do several things, e.g. place an order or receive it into stock.',
        [
            'A <b>Button</b> field runs an automation on its record. Buttons are on the record\'s page next to the title, and in grids.',
            'Press it: the automation\'s steps run together, or not at all. Osmia tells you what it did, or why not, e.g. '
            '"PO-0004 has no lines to order" or "The record does not meet the conditions: Status is Draft".',
            'To make one: build an automation with the trigger <b>A button is pressed</b> (see <a href="/tutorials/automations/">Automations</a>), '
            'then add a <b>Button</b> field and pick it.',
        ],
        gif='button', gif_caption='Placing an order and receiving it with its buttons.',
        try_url='core:home', try_label='Open an app',
        related=['automations'],
    ),

    # -- Automations -------------------------------------------------------------------------------
    Tutorial(
        'automations', 'Automations: when, if, then', '⚡', 'automations',
        'Let Osmia do things by itself when records change, buttons are pressed or dates come.',
        [
            'Open an app you build and click <b>⚡ Automations</b> in the sidebar, then <b>＋ New automation</b>.',
            'Give it a name and pick the table it\'s about. Then, in three parts:',
            '<b>When</b>: a record is created, changed (optionally only when certain fields change), created or changed, about to be '
            'deleted, <i>starts to meet the conditions</i>, a button is pressed, a comment is added, a date in the record is reached, or on a schedule.',
            '<b>If</b>: conditions that must hold, e.g. <i>Status changed to Placed</i>, <i>Total is more than 500</i>, or a formula.',
            '<b>Then</b>: the steps, in order: change records, create a record, find or create one, delete records, stop the change '
            'with a message, notify people, send an email, call a web address, or run another automation.',
            'Click <b>Save</b>. The <b>Run log</b> shows every time it ran: what it did, or why it failed.',
        ],
        gif='automation', gif_caption='Building an automation that notifies the assignee.',
        try_url='core:home', try_label='Open an app you build', audience='builders',
        tips=['All of an automation\'s steps happen together or not at all: if one fails, the others are undone.',
              'Automations can set each other off, up to 8 deep.'],
        related=['automation-values', 'automation-triggers', 'buttons'],
    ),
    Tutorial(
        'automation-values', 'Values in automation steps', '✎', 'automations',
        'Fill fields with text, placeholders and formulas; repeat steps for linked records.',
        [
            'A value is plain text (<code>Placed</code>), text with placeholders (<code>Received with {Number}</code>) or a '
            'formula starting with <code>=</code> (<code>=NOW()</code>, <code>={Quantity} * {Unit price}</code>).',
            'In them, <code>{Field}</code> is the record the automation runs for, <code>{old.Field}</code> its value before the change, '
            '<code>{this.Field}</code> the record a step is changing, <code>{item.Field}</code> the linked record of a "for each" step '
            'and <code>{found.Field}</code> the record the last "find or create" found. A dot follows links: <code>{Part.Average cost}</code>.',
            'To link a new record to this one, set its link field to <code>=RECORD_ID()</code>; to the found record, <code>={found}</code>.',
            '<b>For each</b> repeats a step for every record linked through a field, e.g. a stock move for each order line.',
            '<b>Only if</b> skips a step unless a formula holds, e.g. stop the change only if <code>{Line count} = 0</code>.',
            '<b>Stop the change with a message</b> undoes the change that set the automation off and shows the message, '
            'e.g. "There isn\'t enough DSUB-9-PLUG at WA2".',
        ],
        try_url='core:home', try_label='Open an app you build', audience='builders',
        related=['automations', 'formulas'],
    ),
    Tutorial(
        'automation-triggers', 'Conditions met, dates and schedules', '⏰', 'automations',
        'Automations that wait for something to become true, or for a day to come.',
        [
            '<b>A record starts to meet the conditions</b> runs once when a record goes from not meeting them to meeting them, '
            'e.g. when every line of an order is received, or when stock falls to the reorder level. It is checked whenever '
            'the record, or a record linked to it, changes.',
            '<b>A date in the record is reached</b> runs on the day of a date field plus an offset (−1: the day before), at the time you set, '
            'once per record. E.g. remind the assignee the day before a task is due.',
            '<b>On a schedule</b> runs every hour, day, week or month, for each record that meets the conditions (or once, without a record).',
            'Dates and schedules need Osmia to run with <code>serve.py</code>, which checks every minute (or '
            '<code>manage.py run_automations</code> from the Task Scheduler).',
        ],
        try_url='core:home', try_label='Open an app you build', audience='builders',
        related=['automations'],
    ),

    # -- Administration ----------------------------------------------------------------------------
    Tutorial(
        'access', 'Who may do what', '🔐', 'admin',
        'Reading, editing and building apps; giving people and teams access.',
        [
            'In an app you can be a <b>viewer</b> (look at records), an <b>editor</b> (also add, change and delete records, press '
            'buttons, comment and add files) or a <b>creator</b> (also change its tables, fields, views and automations).',
            'Everyone can make apps of their own and is their creator. Every other app is <b>read only</b> until an administrator '
            'says otherwise.',
            'Administrators open the app\'s <b>⚙ App settings</b>: <i>Everyone who logs in</i> sets what everyone may do, and the '
            'table below gives teams and people another role. Administrators can do everything everywhere.',
            'The owner of an own app can only choose whether everyone may look at it.',
        ],
        try_url='accounts:team_list', try_label='Open the teams', audience='admins',
        related=['users', 'own-app'],
    ),
    Tutorial(
        'users', 'Users and teams', '👥', 'admin',
        'Add people, set their passwords, put them in teams.',
        [
            'In ⚙ pick <b>Users</b>. <b>＋ New user</b> asks for a user name and a password (twice), and optionally their name, '
            'email, job, teams and whether they\'re an administrator.',
            'On a person\'s page, <b>Edit</b> changes their details (untick <i>Can log in</i> to lock them out without deleting them), '
            'and <b>Set password</b> gives them a new password.',
            'In ⚙ pick <b>Teams</b> to make teams and choose their members. Give a team access to apps in each app\'s settings; '
            'automations can notify or email a team.',
        ],
        try_url='accounts:user_list', try_label='Open the users', audience='admins',
        related=['access'],
    ),
    Tutorial(
        'templates', 'App templates', '▤', 'admin',
        'Install ready-made apps, and move apps between Osmias.',
        [
            'In ⚙ pick <b>App templates</b>. Each template is a whole app: tables, fields, views and automations. Tick the ones you '
            'want (with sample records, to try them) and click <b>Install</b>. Templates they need are installed with them.',
            'Templates that work together link up when installed together, e.g. Orders charges its orders to Budgets and receives '
            'them into Stock if those are installed.',
            'Once installed, a template is an ordinary app: change anything.',
            'To copy an app to another Osmia, open its <b>⚙ App settings</b> and click <b>⬇ Download as template</b> (or with its '
            'records), then <b>Install a template file</b> on the other Osmia.',
        ],
        gif='templates', gif_caption='The templates page.',
        try_url='core:templates', try_label='Open the templates', audience='admins',
    ),
    Tutorial(
        'history', 'History and the run log', '↺', 'admin',
        'See every change, who made it, and what automations did.',
        [
            'Every record\'s page has its <b>History</b>: each change with who made it, the old and new values, and whether an '
            'automation made it.',
            '<b>↺ History</b> in an app\'s sidebar lists every change in the app (filter by table). Deleted records stay in the history.',
            '<b>≡ Run log</b> lists every automation run with what it did, or why it failed or was skipped. Filter by <i>Failed</i> '
            'to find problems.',
        ],
        try_url='core:home', try_label='Open an app', audience='builders',
    ),

    # -- Extensions -----------------------------------------------------------------------------------
    Tutorial(
        'extensions', 'Extensions', '◆', 'extensions',
        'Code that adds what tables, views and automations can\'t.',
        [
            'Apps are made on the website. When an app needs more, like a drawing canvas, that part is an <b>extension</b>: '
            'code in the <code>extensions/</code> folder. These tutorials are one.',
            'In ⚙ pick <b>Extensions</b> to see them and switch them on or off (it takes effect when Osmia restarts; '
            '<b>… and restart</b> does that under <code>serve.py</code>).',
            'Extensions can add view types, field types, automation actions, boxes on record pages and pages of their own, and '
            'bring app templates (e.g. Devices and Harness come with the harness designer).',
        ],
        try_url='core:extensions', try_label='Open the extensions', audience='admins',
        related=['designer'],
    ),
    Tutorial(
        'designer', 'The harness designer', '🧵', 'extensions',
        'Place devices on a canvas and wire their connectors pin to pin.',
        [
            'Devices, their connectors and pins are records in the <b>Devices</b> app: add them there (a connector\'s pins are a '
            'table on its page, and <b>Clone with its pins</b> copies a connector).',
            'Open <b>Designer</b> in the sidebar of the Devices or Harness app. Pick a device in <b>Place device</b> and click the canvas '
            'to put it there; scroll to zoom and drag empty space to move around.',
            'Click a connector, then another, to make a harness between them, and pick which pins each wire joins (or '
            '<b>Match remaining pins by signal</b>). The <b>Signal Rules</b> flag wires that aren\'t allowed.',
            'Click a harness and <b>Show pinout</b> for its wire table (export it to CSV, or <b>Order parts</b> for a draft order). '
            '<b>Save</b> keeps a new version; <b>Versions</b> goes back to an older one.',
            'Each project is a record of <b>Harness projects</b> with its pictures, notes and counts; its page opens it in the designer.',
        ],
        gif='designer', gif_caption='Placing two devices on the canvas.',
        try_url='harness:designer', try_label='Open the designer',
    ),
]

BY_SLUG = {t.slug: t for t in TUTORIALS}
