from django.urls import path

from . import comment_views, import_views, retest_views, review_views, views

app_name = "findings"

urlpatterns = [
    path("<uuid:engagement_id>/findings/", views.finding_list, name="list"),
    path("<uuid:engagement_id>/findings/new/", views.finding_create, name="create"),
    path("<uuid:engagement_id>/findings/import/", import_views.finding_import, name="import"),
    path("<uuid:engagement_id>/findings/<uuid:pk>/", views.finding_detail, name="detail"),
    path("<uuid:engagement_id>/findings/<uuid:pk>/edit/", views.finding_edit, name="edit"),
    path("<uuid:engagement_id>/findings/<uuid:pk>/archive/", views.finding_archive, name="archive"),
    path("<uuid:engagement_id>/findings/<uuid:pk>/unarchive/", views.finding_unarchive, name="unarchive"),
    path(
        "<uuid:engagement_id>/findings/<uuid:pk>/assign-reviewer/",
        review_views.assign_reviewer, name="assign_reviewer",
    ),
    path(
        "<uuid:engagement_id>/findings/<uuid:pk>/submit-review/",
        review_views.submit_review, name="submit_review",
    ),
    path(
        "<uuid:engagement_id>/findings/<uuid:pk>/assign-qa/",
        review_views.assign_qa, name="assign_qa",
    ),
    path(
        "<uuid:engagement_id>/findings/<uuid:pk>/submit-qa/",
        review_views.submit_qa, name="submit_qa",
    ),
    path(
        "<uuid:engagement_id>/findings/<uuid:pk>/reopen/",
        review_views.reopen_to_draft, name="reopen_to_draft",
    ),
    path(
        "<uuid:engagement_id>/findings/bulk/assign-reviewer/",
        review_views.bulk_assign_reviewer, name="bulk_assign_reviewer",
    ),
    path(
        "<uuid:engagement_id>/findings/bulk/submit-review/",
        review_views.bulk_submit_review, name="bulk_submit_review",
    ),
    path(
        "<uuid:engagement_id>/findings/bulk/assign-qa/",
        review_views.bulk_assign_qa, name="bulk_assign_qa",
    ),
    path(
        "<uuid:engagement_id>/findings/bulk/submit-qa/",
        review_views.bulk_submit_qa, name="bulk_submit_qa",
    ),
    path(
        "<uuid:engagement_id>/findings/<uuid:pk>/retest/",
        retest_views.retest_record_create, name="retest_create",
    ),
    path(
        "<uuid:engagement_id>/findings/<uuid:pk>/comments/<str:field_name>/",
        comment_views.thread_list,
        name="comment_thread_list",
    ),
    path(
        "<uuid:engagement_id>/findings/<uuid:pk>/comments/<str:field_name>/new/",
        comment_views.thread_create,
        name="comment_thread_create",
    ),
    path(
        "<uuid:engagement_id>/findings/<uuid:pk>/comments/thread/<uuid:thread_id>/reply/",
        comment_views.thread_reply,
        name="comment_thread_reply",
    ),
    path(
        "<uuid:engagement_id>/findings/<uuid:pk>/comments/thread/<uuid:thread_id>/resolve/",
        comment_views.thread_toggle_resolved,
        name="comment_thread_resolve",
    ),
    path(
        "<uuid:engagement_id>/findings/<uuid:pk>/comments/thread/<uuid:thread_id>/delete/",
        comment_views.thread_delete,
        name="comment_thread_delete",
    ),
]
