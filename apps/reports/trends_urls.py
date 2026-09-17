from django.urls import path

from . import trends_views

app_name = "trends"

urlpatterns = [
    path("", trends_views.trends_view, name="view"),
]
