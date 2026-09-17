from django.urls import path

from . import item_views, views

app_name = "checklist"

urlpatterns = [
    path("<uuid:engagement_id>/checklist/", views.checklist_list, name="list"),
    path("<uuid:engagement_id>/checklist/export/", views.checklist_export, name="export"),
    path("<uuid:engagement_id>/checklist/<uuid:pk>/", item_views.item_detail, name="item_detail"),
    path("<uuid:engagement_id>/checklist/<uuid:pk>/comment/", item_views.item_comment_create, name="item_comment_create"),
]
