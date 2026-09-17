from django.urls import path

from . import management_views as views

app_name = "clients"

urlpatterns = [
    path("", views.client_list, name="list"),
    path("create/", views.client_create, name="create"),
    path("<uuid:client_uuid>/", views.client_detail, name="detail"),
    path("<uuid:client_uuid>/edit/", views.client_edit, name="edit"),
    path("<uuid:client_uuid>/users/create/", views.client_user_create, name="user_create"),
    path("users/<uuid:user_uuid>/", views.client_user_detail, name="user_detail"),
    path("users/<uuid:user_uuid>/edit/", views.client_user_edit, name="user_edit"),
    path("users/<uuid:user_uuid>/deactivate/", views.client_user_deactivate, name="user_deactivate"),
    path("users/<uuid:user_uuid>/reactivate/", views.client_user_reactivate, name="user_reactivate"),
    path(
        "users/<uuid:user_uuid>/send-password-reset/",
        views.client_user_send_password_reset, name="user_send_password_reset",
    ),
    path("users/<uuid:user_uuid>/clear-mfa/", views.client_user_clear_mfa, name="user_clear_mfa"),
]
