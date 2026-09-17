from django.urls import path

from . import review_views

app_name = "queue"

urlpatterns = [
    path("", review_views.my_queue, name="my_queue"),
]
