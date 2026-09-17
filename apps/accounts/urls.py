from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("setup/", views.setup_view, name="setup"),
    path("logout/", views.logout_view, name="logout"),
    path("password/change/", views.password_change_view, name="password_change"),
    path("notifications/preferences/", views.notification_preferences_view, name="notification_preferences"),
    path("profile/", views.profile_view, name="profile"),
    path("password/forgot/", views.forgot_password_view, name="password_reset_request"),
    path(
        "password/reset/<uidb64>/<token>/",
        views.password_reset_confirm_view,
        name="password_reset_confirm",
    ),
    path(
        "invite/<uidb64>/<token>/",
        views.account_setup_confirm_view,
        name="account_setup_confirm",
    ),
    path("mfa/enroll/", views.mfa_enroll_view, name="mfa_enroll"),
    path("mfa/verify/", views.mfa_verify_view, name="mfa_verify"),
    path("session/ping/", views.session_ping, name="session_ping"),
    path("", views.dashboard_view, name="dashboard"),
]
