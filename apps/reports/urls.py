from django.urls import path

from . import configure_views, export_views

app_name = "reports"

urlpatterns = [
    path("<uuid:engagement_id>/report/", export_views.export_options, name="options"),
    path("<uuid:engagement_id>/report/export/<str:fmt>/", export_views.export_download, name="download"),
    path("<uuid:engagement_id>/report/configure/", configure_views.report_configure, name="configure"),
    path("<uuid:engagement_id>/report/configure/preview/", configure_views.report_preview, name="preview"),
]
