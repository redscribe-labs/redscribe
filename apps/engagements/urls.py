from django.urls import path

from . import views

app_name = "engagements"

urlpatterns = [
    path("", views.engagement_list, name="list"),
    path("new/", views.engagement_create, name="create"),
    path("<uuid:engagement_id>/", views.engagement_detail, name="detail"),
    path("<uuid:engagement_id>/edit/", views.engagement_edit, name="edit"),
    path(
        "<uuid:engagement_id>/transition/<str:to_status>/",
        views.engagement_transition, name="transition",
    ),
    path("<uuid:engagement_id>/archive/", views.engagement_archive, name="archive"),
    path("<uuid:engagement_id>/unarchive/", views.engagement_unarchive, name="unarchive"),
    path(
        "<uuid:engagement_id>/release-to-client/",
        views.engagement_release_to_client, name="release_to_client",
    ),
    path(
        "<uuid:engagement_id>/revoke-client-release/",
        views.engagement_revoke_client_release, name="revoke_client_release",
    ),
    path("<uuid:engagement_id>/delete/", views.engagement_permanent_delete, name="permanent_delete"),
    path("<uuid:engagement_id>/members/add/", views.member_add, name="member_add"),
    path(
        "<uuid:engagement_id>/members/<uuid:membership_id>/remove/",
        views.member_remove,
        name="member_remove",
    ),
    path("<uuid:engagement_id>/scope-changes/new/", views.scope_change_create, name="scope_change_create"),
    path(
        "<uuid:engagement_id>/scope-changes/<uuid:pk>/approve/",
        views.scope_change_approve,
        name="scope_change_approve",
    ),
    path(
        "<uuid:engagement_id>/scope-changes/<uuid:pk>/reject/",
        views.scope_change_reject,
        name="scope_change_reject",
    ),
]
