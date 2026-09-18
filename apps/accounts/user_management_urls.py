from django.urls import path

from . import user_management_views as views

app_name = "user_management"

urlpatterns = [
    path("", views.user_list, name="list"),
    path("create/", views.user_create, name="create"),
    path("<uuid:user_uuid>/", views.user_detail, name="detail"),
    path("<uuid:user_uuid>/edit/", views.user_edit, name="edit"),
    path("<uuid:user_uuid>/deactivate/", views.user_deactivate, name="deactivate"),
    path("<uuid:user_uuid>/reactivate/", views.user_reactivate, name="reactivate"),
    path("<uuid:user_uuid>/send-password-reset/", views.user_send_password_reset, name="send_password_reset"),
    path("<uuid:user_uuid>/clear-mfa/", views.user_clear_mfa, name="clear_mfa"),
    path("<uuid:user_uuid>/convert-to-local/", views.user_convert_to_local, name="convert_to_local"),
]
