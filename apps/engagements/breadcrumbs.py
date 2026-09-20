from django.urls import reverse


def engagement_crumbs(engagement):
    return [
        {"label": "Engagements", "url": reverse("engagements:list")},
        {"label": engagement.client_name, "url": reverse("engagements:detail", args=[engagement.pk])},
    ]
