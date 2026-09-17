from .branding import get_branding


def branding(request):
    return {"branding": get_branding()}
