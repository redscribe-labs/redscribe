from django.urls import path

from . import views

app_name = "audit"

urlpatterns = [
    path("", views.audit_log_list, name="list"),
    path("purge/", views.purge_view, name="purge"),
    path("purge-all/", views.purge_all_confirm, name="purge_all_confirm"),
    path("purge-all/confirm/", views.purge_all_view, name="purge_all"),
]
