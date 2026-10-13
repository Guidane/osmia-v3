from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def get(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.filter
def initials(user):
    name = (user.get_full_name() or user.username) if user else '?'
    return ''.join(p[0] for p in name.split()[:2]).upper()


@register.simple_tag
def app_icon(app, size=22):
    return format_html('<span class="app-icon" style="background:{}22;color:{}">{}</span>', app.color, app.color, app.icon or '▦')


@register.filter
def align(field):
    return 'num' if field.kind.align == 'num' or (field.type == 'formula' and field.opt('format') in ('number', 'currency', 'percent')) else ''


@register.inclusion_tag('core/_diff.html')
def diff(changes):
    return {'changes': changes}
