"""The tutorials: one per thing Osmia does.

Each tutorial has steps (HTML), optional step-by-step pictures (static/tutorials/<pictures>/,
taken from the real app with ``manage.py make_tutorial_pictures``), a place to
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
    pictures: str = ''   # the folder of its step-by-step pictures
    try_url: str = ''
    try_label: str = ''
    audience: str = 'everyone'
    tips: list = field(default_factory=list)
    related: list = field(default_factory=list)
    keywords: str = ''   # other words people search with ("overview", "dashboard"), not shown


CATEGORIES = [
    ('howto', 'How do I…'),
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
    # -- How do I…: step by step, for something you want done ---------------------------------
    Tutorial(
        'tasks-on-home', 'Show your tasks on your home page', '☑', 'howto',
        'A live list of your open tasks at the top of your home page, soonest due first.',
        [
            'Go to your home page (🏠 <b>Home</b> at the top) and click <b>✎ Edit page</b>.',
            'Click the empty line at the end of the page, type <kbd>/view</kbd> and press <kbd>Enter</kbd> (or click '
            '<b>＋ Add</b> and choose <b>View…</b>).',
            '<b>Put a live view on the page</b> lists every view you can open. Type <kbd>My tasks</kbd> and click '
            '<b>Tasks › Tasks › My tasks</b>: the open tasks assigned to <i>whoever looks at the page</i>.',
            'To have it at the top, point at it and click <b>↑</b> in the small bar above it until it is first. Then click '
            '<b>Save</b>.',
            'On your page it is a live list: how many there are, a row per task (click one to open it), and its title opens '
            'the whole view, where you change them.',
        ],
        pictures='tasks_home',
        try_url='core:home', try_label='Open your home page',
        tips=[
            'Any view can go on a page this way: the tasks <b>Board</b>, a <b>Calendar</b> of due dates, the <b>List</b> of '
            'everyone\'s tasks. On a page each shows as a list, with a link to the view itself.',
            'Want only some of them, say just the urgent ones? Make a view of just those first: '
            '<a href="/tutorials/own-list/">Make a list of just the records you need</a>.',
            'Side by side: <kbd>/grid</kbd> makes a grid of 2, 3 or 4 columns; click in a column and type <kbd>/view</kbd> there.',
            '<b>My work › Assigned to me</b>, on the default home page, already lists your open work across every app; '
            'a view shows one table, with the columns you choose.',
        ],
        related=['arrange-page', 'own-list', 'home'],
        keywords='overview dashboard home screen start page front page to do todo list summary widget',
    ),
    Tutorial(
        'own-list', 'Make a list of just the records you need', '⚲', 'howto',
        'A view that keeps a filter, like "urgent tasks" or "my orders this month", for everyone and for pages.',
        [
            'Open the table (for tasks: the <b>Tasks</b> app). In the row of view tabs, click <b>＋ View</b> and choose '
            '<b>▦ Grid</b>: a new view called Grid opens.',
            'Click <b>⚲ Filter</b>, then <b>＋ Add a filter</b>. Choose a field, a condition and a value: <i>Priority</i> '
            '<i>is</i> <kbd>Urgent</kbd>, or <i>Assignee</i> <i>is me</i> (whoever looks), or <i>Due</i> <i>is in the next … '
            'days</i>. Add more filters if you need them, then click <b>Apply</b>.',
            'Click <b>💾 Save for everyone</b>: the view keeps the filter (and the sort and grouping, if you set them).',
            'Give it a name: <b>⋯</b> at the top right, <b>⚙ View settings</b>, change <i>Name</i> (say <kbd>Urgent tasks</kbd>) '
            'and <b>Save</b>. It now has its own tab, and you can put it on any page with <kbd>/view</kbd>.',
        ],
        try_url='core:launcher', try_label='Open an app', audience='builders',
        tips=[
            'Making views needs the right to change the app. Without it you can still filter and sort a view for yourself '
            '(until you leave it), or ask whoever builds the app.',
            'More about filters: <a href="/tutorials/filter/">Filter, sort, group and choose fields</a>.',
        ],
        related=['tasks-on-home', 'filter', 'views'],
        keywords='saved filter query report only some subset create new view',
    ),
    Tutorial(
        'project-tasks', 'See the tasks of a project or a team', '📁', 'howto',
        'A project\'s page, and a team\'s, already list their tasks, and those of the projects or teams under them.',
        [
            'Click the grid of squares at the top left, then <b>All apps →</b>. Below the apps, the Projects tree is listed: '
            'click the project.',
            'Its page starts with <b>Linked to this space</b>: its <i>Tasks</i>, and the other records it is linked to. '
            'A programme shows the tasks of all its projects.',
            'To give a project a task, open the task and pick the project in its <b>Project</b> field (or open the project\'s '
            '<b>▤ Details</b> and add the task to its <i>Tasks</i>).',
            'A team works the same way: open it in the <b>Organisation</b> tree; its page lists the tasks whose '
            '<i>Department</i> is that team.',
        ],
        try_url='core:launcher', try_label='Find a project',
        related=['spaces', 'tasks-on-home'],
        keywords='overview programme department team project page work',
    ),
    Tutorial(
        'board', 'Move tasks along a board', '▥', 'howto',
        'To do, In progress, Done: a column per status, and dragging a card changes it.',
        [
            'Open the <b>Tasks</b> app and click the <b>▥ Board</b> tab.',
            'Each column is a <i>Status</i>. Drag a card to another column to change its status; click a card to open the task.',
            'To add one, click <b>＋ New</b> at the top right.',
        ],
        pictures='kanban',
        try_url='core:launcher', try_label='Open the Tasks app',
        related=['kanban', 'tasks-on-home'],
        keywords='kanban status columns drag progress workflow',
    ),
    Tutorial(
        'arrange-page', 'Move, remove or reset what is on a page', '↕', 'howto',
        'Blocks, views and cards on your home page (or any page) go where you want them, or away.',
        [
            'Click <b>✎ Edit page</b>. Point at a block, a view, a record card, a grid, a panel or a table: a small bar shows '
            'above it.',
            '<b>↑</b> and <b>↓</b> move it up and down (out of a grid at its top or bottom); <b>←</b> and <b>→</b> move it '
            'to the grid column on the left or right; <b>✕</b> takes it away.',
            'Or click it (it gets a green outline) and press <kbd>Delete</kbd> to take it away, or <kbd>Alt</kbd>+'
            '<kbd>↑</kbd>/<kbd>↓</kbd> to move it. Headings and app cards are text: change or delete them as you type.',
            'Click <b>Save</b>. Changed your mind? <b>↺ Reset to default</b>, next to <i>✎ Edit page</i> or in the editor, '
            'puts the page back as it began.',
        ],
        try_url='core:home', try_label='Open your home page',
        related=['tasks-on-home', 'home'],
        keywords='delete remove block widget layout rearrange reorder default undo restore home screen dashboard',
    ),
    Tutorial(
        'add-tab', 'Add a tab to your Home', '📌', 'howto',
        'A page of your own next to Me: a week plan, a dashboard of one project, notes.',
        [
            'On <b>Home</b>, click <b>＋</b> at the end of the tabs.',
            'Name the tab (say <kbd>Week plan</kbd>) and click <b>Add</b>: its page opens in the editor.',
            'Type <kbd>/</kbd> to fill it: a view by its name (<kbd>/task list</kbd>), a record, notes, a checklist, blocks. '
            'Click <b>Save</b>.',
            'To rename it or take it away, open the tab and click <b>✎ Edit page</b>: change its name at the top, or click '
            '<b>✕ Remove this tab</b>. Only you see your tabs.',
        ],
        pictures='add_tab',
        try_url='core:home', try_label='Open Home',
        related=['home', 'tasks-on-home', 'arrange-page'],
        keywords='new tab page personal dashboard own add page home',
    ),
    Tutorial(
        'roles', 'Roles: the positions people hold', '💼', 'howto',
        'Lead engineer, Buyer, Warehouse operator: a role is a space in the Organisation, held by someone. Its work stays with '
        'it when someone else takes it over.',
        [
            'A role is a record of the <b>Organisation</b> tree with <i>Kind</i> <b>Role</b>, under its team or department, and '
            '<b>Held by</b> the person in it. Each role you hold is a <b>💼 tab on your Home</b>, and opens the role\'s page.',
            'Link work to the role rather than to the person (a task\'s department, a budget, a page in the role\'s space): the role\'s '
            'page shows it under <i>Linked to this space</i>.',
            'To give someone a role, open <b>Organisation</b>, add a record (or open the role) and set <i>Kind</i> to Role, '
            '<i>Part of</i> to the team and <i>Held by</i> to the person. When they change job, change <i>Held by</i>: the role, its '
            'page and everything linked to it go to the new holder.',
            'Who holds a role (and the editors of the Organisation app) change the role\'s page with <b>✎ Edit page</b>.',
        ],
        try_url='core:launcher', try_label='Open the Apps page', audience='builders',
        related=['home', 'spaces'],
        keywords='role position job title holder hand over handover organisation person people team',
    ),
    Tutorial(
        'group-apps', 'Put apps in groups', '▦', 'howto',
        'Management, Production, Purchasing, ...: the launcher and home pages show apps under their group.',
        [
            'Open the app, click <b>⋯</b> next to its tabs and <b>⚙ App settings</b>.',
            'In <b>Group</b>, type a group (or pick one that exists already) and click <b>Save</b>.',
            'The launcher, the Apps page and the <i>Apps</i> block show it under its group; apps without one come last, under '
            '<i>Other apps</i>. Apps made from a template come with a group.',
            'A home page you have changed keeps the cards it has: move them with the page editor (see '
            '<a href="/tutorials/arrange-page/">Move, remove or reset what is on a page</a>), or put the <i>Apps</i> block '
            'on it (type <kbd>/block apps</kbd>), which always shows every app by group.',
        ],
        try_url='core:launcher', try_label='Open the Apps page', audience='builders',
        related=['arrange-page', 'own-app'],
        keywords='category categories folder sort organise organize launcher menu',
    ),

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
            'as a small card, under its group (Management, Production, ...), and the top of each tree of spaces. Type to narrow them down and press <kbd>Enter</kbd> to open the first. '
            'Then come <b>Osmia</b> and 🏠 (Home: your own page and your roles), the search box (it searches every app you can see), 🔔 your '
            'notifications, ⚙ the administration menu and your name.',
            'Inside an app, its <b>tabs</b> run along the top: <b>⌂ Home</b> (the app\'s own page), then a tab per table; a table '
            'has a row of tabs for its views. <b>⋯</b> at the right has its automations, run log, history and settings, '
            'depending on what you may do there.',
        ],
        pictures='tour',
        try_url='core:home', try_label='Open Home',
        related=['home', 'own-app', 'grid'],
    ),
    Tutorial(
        'home', 'Home: your own page and your roles', '🏠', 'start',
        'Where you land: a page of your own (your work, notifications, pinned pages, apps), a tab for each role you hold, '
        'and tabs you add.',
        [
            'Home has tabs. <b>🏠 Me</b> is your own page: only you see it and change it. Then come the tabs you add yourself '
            '(📌, see <a href="/tutorials/add-tab/">Add a tab to your Home</a>), and a <b>💼 tab for each role you hold</b>: '
            '<i>Lead engineer</i> in Engineering, say (see <a href="/tutorials/roles/">Roles</a>).',
            'It starts with <b>My work</b>: <b>Assigned to me</b> (open records in any app where you are in a person field: assignee, '
            'owner, keeper, ...; soonest due first, late ones red), <b>Recent</b> (records you opened lately) and <b>Starred</b> '
            '(records you starred with ☆ next to their title). Then your notifications, pinned pages and every app you can open, '
            'under its group.',
            'Click <b>✎ Edit page</b> to change it. Type <kbd>/</kbd> anywhere (or press <b>＋ Add</b>) for the <b>slash menu</b>: '
            'headings, lists, tables and panels; <b>Grid, 2 columns</b> (type <kbd>/</kbd> again inside a cell to fill it); an app '
            'by its name (a small card that opens it); <b>View…</b> (a live table, board or calendar of any app); <b>Record…</b>; '
            'a calculation; and blocks such as <i>My work</i> and <i>Notifications</i>. Point at a block for a bar that moves it '
            '(↑ ↓ ← →) or takes it away (✕). <b>↺ Reset to default</b> puts it back as it began.',
        ],
        pictures='home',
        try_url='core:home', try_label='Open Home',
        related=['add-tab', 'roles', 'spaces', 'own-app'],
        keywords='home page start page roles tabs personal dashboard',
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
            'The people named on a space (who holds a role, its manager) and the editors of its app change its page: <b>✎ Edit page</b>, '
            'then type <kbd>/</kbd> to put apps, live views, records and blocks on it (see <a href="/tutorials/home/">Home</a>).',
            'To make a space, add a record to its tree: a project in Projects with <i>Part of</i> set to its programme, a team in '
            'Organisation under its department. A tree never goes round in a circle: Osmia refuses a parent that is under the record.',
            'Builders make any table a tree, and its records spaces, in the table\'s <b>⚙ Table settings</b>: pick the link to itself '
            'that names each record\'s parent, and tick <i>Its records are spaces</i>.',
        ],
        pictures='spaces',
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
            'Give the page an emoji and a title and write. Type <kbd>/</kbd> (or <b>＋ Add</b>) for headings, lists, <b>checklists</b>, '
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
        pictures='pages',
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
            'Click <b>＋ New app</b> at the bottom of the launcher (or on the <i>Apps</i> block of your Home).',
            'Give it a name, an icon (any emoji) and a colour, and the name of its first table, e.g. <i>Machines</i>. '
            'Click <b>Make the app</b>.',
            'Osmia opens the table\'s fields, so you can add the columns you need (see <a href="/tutorials/fields/">Fields</a>). '
            'Each table starts with a <i>Name</i> field and a grid view.',
            'Only you see the app. To let colleagues look at it, open <b>⚙ App settings</b> and set <i>Who can see it</i> '
            'to <b>Everyone can look at it</b>. They can\'t change it: only an administrator can give others edit access.',
            'Add more tables with <b>＋</b> after the app\'s tabs; link them together with link fields. <b>⌂ Home</b> is the app\'s '
            'own page: <b>⋯ → ✎ Edit the home page</b> makes it a dashboard with live views and blocks.',
        ],
        pictures='own_app',
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
            '<li><b>Attributes</b>: name-value pairs, each shown as a tag (<i>Resistance</i> 10 kΩ, <i>Power</i> 0.1 W); type a name, '
            'Enter, its value, Enter for the next. Names used before are suggested. In its settings, <i>Names to fill in, from</i> takes '
            'them from a linked record (a part\'s category lists Resistance, Power, ...): each shows as a row to fill in. '
            'A formula reads one with '
            '<kbd>ATTRIBUTE({Attributes}, "Resistance")</kbd>.</li>'
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
        pictures='fields',
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
        pictures='grid',
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
        pictures='filter',
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
        pictures='kanban',
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
        pictures='calendar',
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
        pictures='gantt',
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
        pictures='tree',
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
        pictures='form',
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
        pictures='record',
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
        pictures='button',
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
        pictures='automation',
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
        pictures='templates',
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
        pictures='designer',
        try_url='harness:designer', try_label='Open the designer',
    ),
]

BY_SLUG = {t.slug: t for t in TUTORIALS}
