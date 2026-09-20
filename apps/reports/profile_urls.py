from django.urls import path

from . import profile_views

app_name = "report_profiles"

urlpatterns = [
    path("", profile_views.report_profile_list, name="list"),
    path("<uuid:pk>/edit/", profile_views.report_profile_edit, name="edit"),
    path("<uuid:pk>/delete/", profile_views.report_profile_delete, name="delete"),
    path("<uuid:pk>/set-default/", profile_views.report_profile_set_default, name="set_default"),
    path("<uuid:pk>/text-blocks/", profile_views.report_profile_text_blocks, name="text_blocks"),
    path(
        "<uuid:pk>/text-blocks/<uuid:block_pk>/edit/", profile_views.report_profile_text_block_edit,
        name="profile_text_block_edit",
    ),
    path("text-blocks/<uuid:pk>/delete/", profile_views.report_text_block_delete, name="text_block_delete"),
    path("<uuid:pk>/docx-template/", profile_views.report_profile_docx_template, name="docx_template"),
    path(
        "<uuid:pk>/docx-template/styles/", profile_views.report_profile_docx_style_map, name="docx_style_map",
    ),
    path(
        "<uuid:pk>/docx-template/download/", profile_views.report_profile_docx_template_download,
        name="docx_template_download",
    ),
]
