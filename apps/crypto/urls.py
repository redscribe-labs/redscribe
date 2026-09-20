from django.urls import path

from . import blob_views

app_name = "crypto"

urlpatterns = [
    path("<uuid:engagement_id>/blobs/upload/", blob_views.blob_upload, name="blob_upload"),
    path("<uuid:engagement_id>/blobs/<uuid:blob_id>/", blob_views.blob_serve, name="blob_serve"),
]
