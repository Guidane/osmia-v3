"""Page templates: what a new page starts with."""

TEMPLATES = {
    'blank': ('Blank page', '📄', ''),
    'meeting': ('Meeting notes', '🗓', """
<div class="panel info"><p><b>Date:</b> &nbsp; <b>Attendees:</b> </p></div>
<h2>Goals</h2><ul><li></li></ul>
<h2>Discussion</h2><table><thead><tr><th>Topic</th><th>Who</th><th>Notes</th></tr></thead><tbody><tr><td></td><td></td><td></td></tr><tr><td></td><td></td><td></td></tr></tbody></table>
<h2>Action items</h2><ul class="tasks"><li class="task" data-checked="false"></li></ul>
<h2>Decisions</h2><ul><li></li></ul>"""),
    'howto': ('How-to', '🛠', """
<div class="panel note"><p>What this is for, in one sentence.</p></div>
<h2>Before you start</h2><ul><li></li></ul>
<h2>Steps</h2><ol><li></li><li></li><li></li></ol>
<div class="panel warning"><p>What to watch out for.</p></div>
<h2>Related</h2><ul><li></li></ul>"""),
    'decision': ('Decision', '⚖', """
<table><tbody><tr><th>Status</th><td>Proposed</td></tr><tr><th>Owner</th><td></td></tr><tr><th>Decided on</th><td></td></tr></tbody></table>
<h2>Background</h2><p></p>
<h2>Options</h2><table><thead><tr><th>Option</th><th>For</th><th>Against</th></tr></thead><tbody><tr><td></td><td></td><td></td></tr><tr><td></td><td></td><td></td></tr></tbody></table>
<h2>Decision</h2><div class="panel success"><p></p></div>
<h2>Consequences</h2><ul><li></li></ul>"""),
    'retro': ('Retrospective', '🔁', """
<h2>What went well</h2><ul><li></li></ul>
<h2>What could be better</h2><ul><li></li></ul>
<h2>What we'll try next</h2><ul class="tasks"><li class="task" data-checked="false"></li></ul>"""),
    'project': ('Project plan', '📁', """
<div class="panel info"><p><b>Goal:</b> </p></div>
<h2>Scope</h2><p><b>In:</b> </p><p><b>Out:</b> </p>
<h2>Milestones</h2><table><thead><tr><th>Milestone</th><th>Date</th><th>Owner</th></tr></thead><tbody><tr><td></td><td></td><td></td></tr></tbody></table>
<h2>Risks</h2><table><thead><tr><th>Risk</th><th>Likelihood</th><th>What we do about it</th></tr></thead><tbody><tr><td></td><td></td><td></td></tr></tbody></table>
<h2>Tasks</h2><p>Type <b>/view</b> to put the project's tasks here, live.</p>"""),
}
