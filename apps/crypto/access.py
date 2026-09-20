from functools import wraps

from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string

from apps.engagements.access import check_engagement_access
from apps.engagements.models import Engagement

from .services import get_data_key


def _unauthenticated_response(request) -> HttpResponse:
    return HttpResponse(render_to_string("401.html", request=request), status=401)


def _attach_engagement_and_key(request, engagement_id):
    if not request.user.is_authenticated:
        return _unauthenticated_response(request)

    engagement = get_object_or_404(Engagement, pk=engagement_id)

    decision = check_engagement_access(request.user, engagement)
    if not decision.granted:
        raise PermissionDenied(decision.reason)

    request.engagement = engagement
    request.project_key = get_data_key(engagement)
    return None


def engagement_access_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, engagement_id=None, **kwargs):
        early_response = _attach_engagement_and_key(request, engagement_id)
        if early_response is not None:
            return early_response
        return view_func(request, *args, engagement_id=engagement_id, **kwargs)

    return wrapper


class EngagementAccessMixin:
    def dispatch(self, request, *args, **kwargs):
        early_response = _attach_engagement_and_key(request, kwargs.get("engagement_id"))
        if early_response is not None:
            return early_response
        return super().dispatch(request, *args, **kwargs)
