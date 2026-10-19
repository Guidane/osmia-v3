from django.urls import path

from . import admin_views, api, build_views, space_views, views
from .canvas import views as editor_views

app_name = 'core'

urlpatterns = [
    path('', space_views.home, name='home'),
    path('home/edit/', space_views.home_edit, name='home_edit'),
    path('home/new/', space_views.home_tab_new, name='home_tab_new'),
    path('home/<int:pk>/', space_views.home, name='home_page'),
    path('home/<int:pk>/edit/', space_views.home_edit, name='home_page_edit'),
    path('apps/', space_views.launcher, name='launcher'),
    path('setup/', views.setup, name='setup'),
    path('search/', views.search, name='search'),
    path('s/<int:pk>/', space_views.space_page, name='space'),
    path('s/<int:pk>/edit/', space_views.space_edit, name='space_edit'),
    path('notifications/', views.notifications, name='notifications'),
    path('notifications/<int:pk>/', views.notification_open, name='notification_open'),

    # the page editor
    path('editor/records/', editor_views.records_for_link, name='editor_records'),
    path('editor/records/<int:pk>/', editor_views.record_for_link, name='editor_record'),
    path('editor/calc/', editor_views.calc_preview, name='editor_calc'),

    # administration
    path('admin/templates/', admin_views.templates, name='templates'),
    path('admin/templates/export/<slug:app_slug>/', admin_views.template_export, name='template_export'),
    path('admin/extensions/', admin_views.extensions, name='extensions'),
    path('admin/extensions/<str:name>/', admin_views.extension_switch, name='extension_switch'),
    path('admin/trees/', admin_views.trees, name='trees'),
    path('admin/tags/', admin_views.tags, name='tags'),
    path('admin/tags/<int:pk>/', admin_views.tag_detail, name='tag'),
    path('apps/new/', build_views.app_create, name='app_create'),

    # records and files
    path('r/<int:pk>/', views.record_page, name='record'),
    path('r/<int:pk>/delete/', views.record_delete, name='record_delete'),
    path('r/<int:pk>/star/', views.record_star, name='record_star'),
    path('r/<int:pk>/comment/', views.record_comment, name='record_comment'),
    path('r/<int:pk>/tags/', views.record_tags, name='record_tags'),
    path('r/<int:pk>/files/<int:field_id>/', views.record_upload, name='record_upload'),
    path('files/<int:pk>/', views.attachment_file, name='attachment'),
    path('files/<int:pk>/delete/', views.attachment_delete, name='attachment_delete'),

    # JSON
    path('api/tables/<int:table_id>/', api.table_schema, name='api_table'),
    path('api/tables/<int:table_id>/records/', api.table_records, name='api_records'),
    path('api/tables/<int:table_id>/create/', api.record_create, name='api_create'),
    path('api/records/<int:pk>/', api.record_api, name='api_record'),
    path('api/records/<int:pk>/delete/', api.record_delete, name='api_delete'),
    path('api/records/<int:pk>/move/', api.record_move, name='api_move'),
    path('api/records/<int:pk>/link/<int:field_id>/', api.record_link, name='api_link'),
    path('api/records/<int:pk>/button/<int:field_id>/', api.record_button, name='api_button'),
    path('api/records/<int:pk>/run/<int:automation_id>/', api.record_run, name='api_run'),
    path('api/views/<int:view_id>/config/', api.view_config, name='api_view_config'),

    # apps
    path('a/<slug:app_slug>/', space_views.app_home, name='app'),
    path('a/<slug:app_slug>/home/edit/', space_views.app_home_edit, name='app_home_edit'),
    path('a/<slug:app_slug>/settings/', build_views.app_settings, name='app_settings'),
    path('a/<slug:app_slug>/history/', build_views.app_history, name='app_history'),
    path('a/<slug:app_slug>/new-table/', build_views.table_create, name='table_create'),
    path('a/<slug:app_slug>/automations/', build_views.automation_list, name='automations'),
    path('a/<slug:app_slug>/automations/new/', build_views.automation_edit, name='automation_create'),
    path('a/<slug:app_slug>/automations/<int:automation_id>/', build_views.automation_edit, name='automation_edit'),
    path('a/<slug:app_slug>/automations/runs/', build_views.automation_runs, name='automation_runs'),
    path('a/<slug:app_slug>/<slug:table_slug>/', views.table_page, name='table'),
    path('a/<slug:app_slug>/<slug:table_slug>/new/', views.record_new, name='record_new'),
    path('a/<slug:app_slug>/<slug:table_slug>/csv/', views.table_csv, name='table_csv'),
    path('a/<slug:app_slug>/<slug:table_slug>/import/', views.table_import, name='table_import'),
    path('a/<slug:app_slug>/<slug:table_slug>/settings/', build_views.table_settings, name='table_settings'),
    path('a/<slug:app_slug>/<slug:table_slug>/fields/', build_views.fields, name='fields'),
    path('a/<slug:app_slug>/<slug:table_slug>/fields/new/', build_views.field_edit, name='field_create'),
    path('a/<slug:app_slug>/<slug:table_slug>/fields/<int:field_id>/', build_views.field_edit, name='field_edit'),
    path('a/<slug:app_slug>/<slug:table_slug>/views/new/', build_views.view_create, name='view_create'),
    path('a/<slug:app_slug>/<slug:table_slug>/v/<int:view_id>/', views.view_page, name='view'),
    path('a/<slug:app_slug>/<slug:table_slug>/v/<int:view_id>/settings/', build_views.view_settings, name='view_settings'),
]
