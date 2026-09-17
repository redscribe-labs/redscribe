from django.urls import path

from . import views

app_name = "feature_flags"

urlpatterns = [
    path("", views.flags_edit, name="edit"),
]
