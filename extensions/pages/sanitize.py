"""Cleaning page HTML: only what the editor makes survives.

An allowlist of tags and attributes; everything else is dropped (the text of
unknown tags is kept, ``script`` and ``style`` go with their content). Links
may only go to http(s), mail, phone or Osmia's own pages; pictures only come
from Osmia itself.
"""
import re
from html import escape
from html.parser import HTMLParser

ALLOWED = {
    'p': (), 'br': (), 'hr': (), 'h1': (), 'h2': (), 'h3': (), 'h4': (),
    'strong': (), 'b': (), 'em': (), 'i': (), 'u': (), 's': (), 'strike': (), 'sub': (), 'sup': (), 'code': (), 'pre': (),
    'blockquote': (), 'ul': ('class',), 'ol': (), 'li': ('class', 'data-checked'),
    'a': ('href', 'class', 'data-record', 'title'),
    'table': (), 'thead': (), 'tbody': (), 'tr': (), 'th': ('colspan', 'rowspan'), 'td': ('colspan', 'rowspan'),
    'img': ('src', 'alt', 'width'),
    'div': ('class', 'data-view', 'data-title'), 'span': ('class',),
}
VOID = {'br', 'hr', 'img'}
DROP_WITH_CONTENT = {'script', 'style', 'iframe', 'object', 'embed', 'svg', 'math', 'template', 'noscript', 'head', 'title'}
CLASSES = {'panel', 'info', 'note', 'warning', 'success', 'embed-view', 'record-ref', 'tasks', 'task', 'done', 'mention'}
SAFE_HREF = re.compile(r'^(https?://|mailto:|tel:|/|#)', re.I)
SAFE_SRC = re.compile(r'^/(x/pages/files|files)/\d+/', re.I)


class _Cleaner(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.stack = []
        self.dropping = 0

    def handle_starttag(self, tag, attrs):
        if tag in DROP_WITH_CONTENT:
            if tag not in VOID:
                self.dropping += 1
            return
        if self.dropping or tag not in ALLOWED:
            return
        kept = []
        for name, value in attrs:
            value = value or ''
            if name not in ALLOWED[tag]:
                continue
            if name == 'class':
                value = ' '.join(c for c in value.split() if c in CLASSES)
                if not value:
                    continue
            if name == 'href' and not SAFE_HREF.match(value.strip()):
                continue
            if name == 'src' and not SAFE_SRC.match(value.strip()):
                continue
            if name in ('data-view', 'data-record', 'colspan', 'rowspan', 'width') and not value.strip().isdigit():
                continue
            if name == 'data-checked' and value not in ('true', 'false'):
                continue
            kept.append(f' {name}="{escape(value.strip(), quote=True)}"')
        if tag == 'img' and not any(k.startswith(' src=') for k in kept):
            return
        if tag == 'a':
            kept.append(' rel="noopener"')
        self.out.append(f'<{tag}{"".join(kept)}>')
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID and self.stack and self.stack[-1] == tag:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in DROP_WITH_CONTENT:
            self.dropping = max(0, self.dropping - 1)
            return
        if self.dropping or tag not in ALLOWED or tag in VOID or tag not in self.stack:
            return
        while self.stack:  # close what was left open inside it
            open_tag = self.stack.pop()
            self.out.append(f'</{open_tag}>')
            if open_tag == tag:
                break

    def handle_data(self, data):
        if not self.dropping:
            self.out.append(escape(data, quote=False))


def clean(html):
    parser = _Cleaner()
    parser.feed(html or '')
    parser.close()
    out = ''.join(parser.out) + ''.join(f'</{t}>' for t in reversed(parser.stack))
    return out.strip()


def text_of(html):
    """The page's words, for search and previews."""
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html or '')).strip()
