"""What the harness designer adds to Osmia (see core.extensions)."""
from django.template.loader import render_to_string
from django.urls import reverse

from core.extensions import Panel
from core.viewtypes import ViewType


class DesignerView(ViewType):
    """A view of the Harness projects table that is the designer itself."""
    key, label, icon, template = 'harness_designer', 'Harness designer', '🧵', 'harness/view_designer.html'
    help = 'The wire harness designer, on a tab of the Harness projects table.'
    uses_records = False
    toolbar = False

    def available(self, table, data):
        return table.app.blueprint == 'harness' and table.key == 'projects'

    def context(self, request, view, data, records, state):
        project = request.GET.get('project', '')
        return {'designer_url': reverse('harness:designer') + '?embed=1' + (f'&project={project}' if project.isdigit() else '')}


def device_panel(request, record, data):
    """On a device's page: the harness projects that use it."""
    from .drawing import Apps
    apps = Apps(request.user)
    if not apps.ready:
        return None
    projects = apps.projects_using(record.pk)
    html = render_to_string('harness/_device_panel.html', {'projects': [(p, apps.data.label(p)) for p in projects],
                                                          'designer': reverse('harness:designer')}, request=request)
    return Panel('🧵 Used in harness projects', html, order=50)


def project_panel(request, record, data):
    """On a harness project's page: open it in the designer, and its versions."""
    from .models import DrawingVersion
    html = render_to_string('harness/_project_panel.html', {
        'url': reverse('harness:designer') + f'?project={record.pk}',
        'versions': DrawingVersion.objects.filter(record_id=record.pk).select_related('created_by')[:10],
    }, request=request)
    return Panel('🧵 Designer', html, order=10)


def register(registry):
    registry.app('Harness designer', 'harness:designer', '🧵', 'Place devices on a canvas and wire their connectors pin to pin.',
                 color='#c2410c', extension='harness', group='Production')
    registry.view_type(DesignerView)
    registry.page('Designer', 'harness:designer', '✏️', app='harness', extension='harness')
    registry.page('Designer', 'harness:designer', '✏️', app='devices', extension='harness')
    registry.record_panel(device_panel, tables=[('devices', 'devices')])
    registry.record_panel(project_panel, tables=[('harness', 'projects')])
