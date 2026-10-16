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
    ('spaces', 'Spaces, pages and access'),
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
        'Apps hold the data, trees of spaces give it structure, pages explain it. Where everything is on the screen.',
        [
            'Osmia is a workspace of <b>apps</b>. An app (say <i>Orders</i>) has <b>tables</b> (<i>Orders</i>, <i>Order lines</i>), '
            'a table has <b>fields</b> (columns) and <b>records</b> (rows), and you look at a table through <b>views</b>: '
            'a grid, a kanban board, a calendar, a Gantt chart and more.',
            'The company\'s structure is a forest of <b>trees</b>: the organisation (company, departments, teams, people), programmes '
            'and projects, locations, ... A tree\'s nodes can be <b>spaces</b>, each with a page. Records don\'t belong to one place: '
            'a task links to its project, its team and the part it is about (see <a href="/tutorials/spaces/">Spaces and trees</a>).',
            'The <b>top bar</b> starts with the <b>launcher</b>: click the grid of squares at the far left for every app you can open '
            'as a small card, and the top of each tree of spaces. Type to narrow them down and press <kbd>Enter</kbd> to open the first. '
            'Then come <b>Osmia</b> and 🏠 (your home space), the search box (it searches every app you can see), 🔔 your '
            'notifications, ⚙ the administration menu and your name.',
            'Inside an app, its <b>tabs</b> run along the top: <b>⌂ Home</b> (the app\'s own page), then a tab per table; a table '
            'has a row of tabs for its views. <b>⋯</b> at the right has its automations, run log, history and settings, '
            'depending on what you may do there.',
        ],
        gif='tour', gif_caption='Opening an app from the launcher, then a table, a view and a record.',
        try_url='core:home', try_label='Open your home space',
        related=['home', 'own-app', 'grid'],
    ),
    Tutorial(
        'home', 'Your home space', '🏠', 'start',
        'Where you land: your work across all apps, notifications, pinned pages and your apps; you make it your own.',
        [
            'Your home space is your node in the <b>Organisation</b> tree, made for you the first time you log in. An administrator '
            'moves it under your team.',
            'It starts with <b>My work</b>: <b>Assigned to me</b> (open records in any app where you are in a person field: assignee, '
            'owner, keeper, ...; soonest due first, late ones red), <b>Recent</b> (records you opened lately) and <b>Starred</b> '
            '(records you starred with ☆ next to their title). Then your notifications, pinned pages and every app you can open.',
            'Click <b>✎ Edit page</b> to change it. Type <kbd>/</kbd> anywhere (or press <b>＋ Add</b>) for the <b>slash menu</b>: '
            'headings, lists, tables and panels; <b>Grid, 2 columns</b> (type <kbd>/</kbd> again inside a cell to fill it); an app '
            'by its name (a small card that opens it); <b>View…</b> (a live table, board or calendar of any app); <b>Record…</b>; '
            'a calculation; and blocks such as <i>My work</i> and <i>Notifications</i>. <b>↺ Start over</b> puts it back as it began.',
        ],
        gif='home', gif_caption='Starring a record, then putting an app on the home space with the slash menu.',
        try_url='core:home', try_label='Open your home space',
        related=['spaces', 'own-app', 'pages'],
    ),
    Tutorial(
        'spaces', 'Spaces and trees', '🌳', 'spaces',
        'Any table can be a tree; the nodes of a tree of spaces have a page with everything linked to them.',
        [
            'A <b>tree</b> is a table whose records have a parent in the same table: the organisation, programmes and projects, '
            'locations in a warehouse, part categories. Records of every other table link to a tree\'s nodes like to any record, '
            'as many trees as they need: a task links to a project, a team and a location at once.',
            'A tree of <b>spaces</b> gives each node a <b>page</b>. Open one from the launcher, a link, or <b>◼ Space page</b> on its '
            'record. It starts with what <b>links to it</b> (and to the spaces under it: a programme shows the tasks of all its projects), '
            'the spaces under it and its Documentation pages.',
            'The people named on a space (its person, its manager) and the editors of its app change its page: <b>✎ Edit page</b>, '
            'then type <kbd>/</kbd> to put apps, live views, records and blocks on it (see <a href="/tutorials/home/">Your home space</a>).',
            'To make a space, add a record to its tree: a project in Projects with <i>Part of</i> set to its programme, a team in '
            'Organisation under its department. A tree never goes round in a circle: Osmia refuses a parent that is under the record.',
            'Builders make any table a tree, and its records spaces, in the table\'s <b>⚙ Table settings</b>: pick the link to itself '
            'that names each record\'s parent, and tick <i>Its records are spaces</i>.',
        ],
        gif='spaces', gif_caption='Opening a programme’s space, then adding a heading, a grid, an app and a block with the slash menu.',
        try_url='core:launcher', try_label='Open the launcher',
        related=['pages', 'tags', 'home'],
    ),
    Tutorial(
        'pages', 'Documentation pages', '📄', 'spaces',
        'Write pages for people to read in the Documentation app: how-tos, meeting notes, decisions, with live data from your apps.',
        [
            'Open <b>📄 Documentation</b> in the launcher. Every space has its section; pick one, or use <i>Pages of this space</i> on '
            'a space\'s page. Pick a template: <b>Blank</b>, <b>Meeting notes</b>, <b>How-to</b>, <b>Decision</b>, '
            '<b>Retrospective</b> or <b>Project plan</b>.',
            'Give the page an emoji and a title and write. Type <kbd>/</kbd> (or <b>＋ Add</b>) for headings, lists, <b>task lists</b>, '
            'tables, dividers, <b>info, note, warning and success panels</b>, grids, pictures (or paste one), and live data.',
            'Pages are for explaining; <b>data belongs in apps</b>. A page shows it live: <b>/view</b> puts a live view of any app on '
            'the page; <b>/record</b> (or <kbd>@</kbd>) puts a <b>link</b>, a <b>card</b> with the fields you tick, or <b>one live '
            'value</b> in a sentence ("Part 4471 has <b>12</b> in stock"). The record\'s own page shows <b>Mentioned in</b>.',
            '<b>/calculation</b> does math on that data: name records when you put them on the page (e.g. <i>part</i>), then write '
            '<code>{part.Unit cost} * {Qty}</code>; in a page table, <code>{Qty}</code> is the cell of the same row under the heading Qty.',
            'Add labels and press <b>Publish</b> (or <kbd>Ctrl</kbd>+<kbd>S</kbd>). <b>＋ Page under it</b> makes a child page; the '
            '<b>page tree</b> on the left shows them all. Every save is a <b>version</b>: open an old one and <b>Restore</b> it. '
            'Readers can <b>comment</b>, and <b>📌</b> pins a page to the <i>Pinned pages</i> block.',
            'Whoever can see the space reads its pages; the people who may edit the space\'s page write them. A page carries its '
            'space\'s <b>access tags</b>, and can have its own.',
        ],
        gif='pages', gif_caption='Writing a how-to with a task list and a live view of tasks, then pinning it.',
        try_url='docs:index', try_label='Open Documentation',
        related=['spaces', 'tags'],
    ),
    Tutorial(
        'tags', 'Access tags: who sees what', '🏷', 'spaces',
        'Records, pages and spaces with access tags are seen only by people holding every one of those tags.',
        [
            'An <b>access tag</b> (say <i>Payroll</i>) is held by some people. A record carrying it is seen only by them: everyone '
            'else doesn\'t see it at all, not in views, links, totals, search, pages or the AI assistant, not even that it exists.',
            'Tags are not ranks: holding one gives nothing in any other. A record with two tags needs both. Administrators are no '
            'exception: they build every app, but see only what their tags allow.',
            'Tags come along: a record carries the tags of its <b>parent</b> in a tree and of the <b>spaces it links to</b>. Tag a '
            'project, and its tasks and sub-projects are hidden with it.',
            'On a record\'s page, <b>🏷 Who sees it</b> shows its tags; tick the tags you hold to put them on (nobody can put on a tag '
            'they don\'t hold). <b>🏷 Access tags</b> in the top bar lists the tags; <b>owners</b> give a tag to people and make other '
            'owners, and the other owners are told each time.',
            'Putting someone in a person field of a record they can\'t see (assigning a <i>Payroll</i> task to Bob) asks first: '
            '<b>share this one record</b> with them, or pick someone else. The share ends when the record is closed or they\'re '
            'taken off it; the tag\'s owners are told.',
        ],
        try_url='core:tags', try_label='Open the access tags',
        related=['access', 'spaces'],
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
        'Everyone can make apps of their own, and build them as they like.',
        [
            'Click <b>＋ New app</b> at the bottom of the launcher (or on the <i>Apps</i> block of your home space).',
            'Give it a name, an icon (any emoji) and a colour, and the name of its first table, e.g. <i>Machines</i>. '
            'Click <b>Make the app</b>.',
            'Osmia opens the table\'s fields, so you can add the columns you need (see <a href="/tutorials/fields/">Fields</a>). '
            'Each table starts with a <i>Name</i> field and a grid view.',
            'Only you see the app. To let colleagues look at it, open <b>⚙ App settings</b> and set <i>Who can see it</i> '
            'to <b>Everyone can look at it</b>. They can\'t change it: only an administrator can give others edit access.',
            'Add more tables with <b>＋</b> after the app\'s tabs; link them together with link fields. <b>⌂ Home</b> is the app\'s '
            'own page: <b>⋯ → ✎ Edit the home page</b> makes it a dashboard with live views and blocks.',
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
            'Open an app you build and pick <b>⚡ Automations</b> under <b>⋯</b> at the right of its tabs, then <b>＋ New automation</b>.',
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
            'table below gives teams and people another role. Administrators build every app.',
            'The owner of an own app can only choose whether everyone may look at it.',
            'Which <b>records</b> someone sees is the other half: <a href="/tutorials/tags/">access tags</a>. A role lets you look '
            'at or change an app; the tags decide which of its records are there for you.',
        ],
        try_url='accounts:team_list', try_label='Open the teams', audience='admins',
        related=['users', 'own-app', 'tags'],
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
            'want (with sample records, to try them) and click <b>Install</b>. If they need templates that aren\'t installed, Osmia '
            'lists them first and installs them together, or nothing at all.',
            'Templates that work together link up when installed together, e.g. Orders charges its orders to Budgets and receives '
            'them into Stock if those are installed.',
            'Once installed, a template is an ordinary app: change anything.',
            '<b>Nothing is removed while something uses it.</b> Deleting an app, a table, a field, a view or an automation that '
            'something else needs (a formula, a link, an automation, a view\'s filter, a page, another app or an extension) is '
            'refused, and Osmia lists what uses it. Deleting an app leaves the plain fields it added to other apps\' tables there, '
            'with their values; what only worked with it goes with it.',
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
            '<b>↺ History</b> under an app\'s <b>⋯</b> lists every change in the app (filter by table). Deleted records stay in the '
            'history. Changes to records you can\'t see (access tags) aren\'t listed.',
            '<b>≡ Run log</b> lists every automation run with what it did, or why it failed or was skipped. Filter by <i>Failed</i> '
            'to find problems.',
        ],
        try_url='core:home', try_label='Open an app', audience='builders',
    ),

    # -- Extensions -----------------------------------------------------------------------------------
    Tutorial(
        'extensions', 'Extension apps', '◆', 'extensions',
        'Apps made in code, with screens of their own, that keep their data in ordinary apps.',
        [
            'Apps are made on the website. An <b>extension app</b> is made in code and has fixed screens of its own, like the harness '
            'designer\'s canvas, Documentation or these tutorials. It shows up in the launcher like any app.',
            'Its data is in ordinary tables: the harness designer works on the Devices and Harness apps. It can also add to every '
            'app: blocks for the slash menu, tabs, boxes on record pages, field types, view types and automation actions.',
            'In ⚙ pick <b>Extensions</b>. <b>Switch on…</b> lists what the extension needs that isn\'t there and installs it with it, '
            'or not at all. While it is on, nothing it needs can be removed.',
            '<b>Switch off…</b> removes only its code: everything it stored stays, as ordinary apps and fields, and switching it on again '
            'brings its screens back over the same data. It is refused while something uses what it brings (a view of its view type, '
            'its block on a page, ...). Either takes effect when Osmia restarts; <b>… and restart</b> does that under <code>serve.py</code>.',
        ],
        try_url='core:extensions', try_label='Open the extensions', audience='admins',
        related=['designer', 'templates'],
    ),
    Tutorial(
        'designer', 'The harness designer', '🧵', 'extensions',
        'Place devices on a canvas and wire their connectors pin to pin.',
        [
            'Devices, their connectors and pins are records in the <b>Devices</b> app: add them there (a connector\'s pins are a '
            'table on its page, and <b>Clone with its pins</b> copies a connector).',
            'Open <b>🧵 Harness designer</b> in the launcher (or the <b>Designer</b> tab of the Devices or Harness app). Pick a device in <b>Place device</b> and click the canvas '
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
