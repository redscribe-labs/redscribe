from django.urls import path

from . import field_visibility_views

app_name = "field_visibility"

urlpatterns = [
    path("", field_visibility_views.field_visibility_edit, name="edit"),
    path("<uuid:pk>/move-<str:direction>/", field_visibility_views.content_section_move, name="move"),
    path("<uuid:pk>/delete/", field_visibility_views.content_section_delete, name="delete"),
]
