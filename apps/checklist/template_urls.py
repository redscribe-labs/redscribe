from django.urls import path

from . import template_views

app_name = "checklist_templates"

urlpatterns = [
    path("", template_views.template_list, name="list"),
    path("upload/", template_views.template_upload, name="upload"),
    path("create/", template_views.template_create, name="create"),
    path("<uuid:pk>/", template_views.template_detail, name="detail"),
    path("<uuid:pk>/export/", template_views.template_export, name="export"),
    path("<uuid:pk>/edit/", template_views.template_edit, name="edit"),
    path("<uuid:pk>/set-default/", template_views.template_set_default, name="set_default"),
    path("<uuid:pk>/items/add/", template_views.template_item_create, name="item_add"),
    path("items/<uuid:item_pk>/edit/", template_views.template_item_edit, name="item_edit"),
    path("items/<uuid:item_pk>/delete/", template_views.template_item_delete, name="item_delete"),
    path("items/<uuid:item_pk>/move/", template_views.template_item_move, name="item_move"),
]
