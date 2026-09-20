from django.urls import path

from . import role_management_views as views

app_name = "role_management"

urlpatterns = [
    path("", views.role_list, name="list"),
    path("create/", views.role_create, name="create"),
    path("<uuid:pk>/", views.role_detail, name="detail"),
    path("<uuid:pk>/edit/", views.role_edit, name="edit"),
    path("<uuid:pk>/delete/", views.role_delete, name="delete"),
]
