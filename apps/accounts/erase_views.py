from django.contrib import messages
from django.shortcuts import redirect, render

from .erasure import ErasureError, erase_user, erasure_blocker, verify_erase_confirmation


def run_erase_flow(request, target, *, detail_url, erase_url, breadcrumbs, action, route):
    """The confirm page and POST handling shared by staff and client-user erasure.

    Callers do their own permission check and fetch `target`; this renders the
    confirmation page, checks the typed username, then erases.
    """
    blocker = erasure_blocker(target, request.user)
    if blocker:
        messages.error(request, blocker)
        return redirect(detail_url)

    if request.method != "POST":
        return render(
            request, "accounts/user_management/erase_confirm.html",
            {"target": target, "cancel_url": detail_url, "breadcrumbs": breadcrumbs},
        )

    def refuse(message):
        messages.error(request, f"{message} — nothing was erased.")
        return redirect(erase_url)

    problem = verify_erase_confirmation(request, target)
    if problem:
        return refuse(problem)

    try:
        erase_user(target, actor=request.user, action=action, route=route)
    except ErasureError as exc:
        return refuse(str(exc).rstrip("."))

    messages.success(request, "Account erased. Its personal data is gone.")
    return redirect(detail_url)
