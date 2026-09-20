from django.urls import path

from . import views

app_name = "clients_portal"

urlpatterns = [
    path("", views.portal_dashboard, name="dashboard"),
    path("engagements/<uuid:engagement_id>/", views.portal_engagement_detail, name="engagement_detail"),
    path(
        "engagements/<uuid:engagement_id>/findings/<uuid:pk>/",
        views.portal_finding_detail, name="finding_detail",
    ),
]
