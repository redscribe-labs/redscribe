from django.urls import path

from . import branding_views

app_name = "branding"

urlpatterns = [
    path("", branding_views.branding_edit, name="edit"),
    path("logo/", branding_views.logo, name="logo"),
]
