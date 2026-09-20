from django.urls import path

from . import catalogue_views as views

app_name = "catalogue"

urlpatterns = [
    path("", views.template_list, name="list"),
    path("new/", views.template_create, name="create"),
    path("export/", views.template_export, name="export"),
    path("import/", views.template_import, name="import"),
    path("<uuid:pk>/", views.template_detail, name="detail"),
    path("<uuid:pk>/edit/", views.template_edit, name="edit"),
    path("<uuid:pk>/delete/", views.template_delete, name="delete"),
    path("<uuid:pk>/submit-qa/", views.template_submit_qa, name="submit_qa"),
    path("<uuid:pk>/approve/", views.template_approve, name="approve"),
    path("<uuid:pk>/unapprove/", views.template_unapprove, name="unapprove"),
]
