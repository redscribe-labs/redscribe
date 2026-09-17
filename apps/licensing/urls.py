from django.urls import path

from . import views

app_name = "licensing"

urlpatterns = [
    path("", views.license_edit, name="edit"),
]
