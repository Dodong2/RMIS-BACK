from .models import AuditLog

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
ERROR_DETAIL_MAX_CHARS = 1000


def _error_detail(response):
    """First part of a JSON error body. 5xx bodies are skipped: with DEBUG off they're just a generic HTML page
    (the traceback goes to the container logs instead)."""
    if not 400 <= response.status_code < 500 or response.streaming:
        return ""
    if "json" not in response.get("Content-Type", ""):
        return ""
    return response.content.decode("utf-8", errors="replace")[:ERROR_DETAIL_MAX_CHARS]


class AuditLogMiddleware:
    """Logs every authenticated mutating API call. Must sit AFTER the view
    runs (i.e. read request.user only in the post-get_response half) —
    DRF's JWTAuthentication resolves request.user lazily inside the view via
    permission checks, and its Request.user setter writes the resolved user
    back onto this same underlying request object, so it's only populated
    by the time get_response() returns."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if request.method in MUTATING_METHODS and request.path.startswith("/api/"):
            user = getattr(request, "user", None)
            if user is not None and user.is_authenticated:
                try:
                    AuditLog.objects.create(
                        actor=user,
                        method=request.method,
                        path=request.path[:500],
                        status_code=response.status_code,
                        ip_address=request.META.get("REMOTE_ADDR"),
                        error_detail=_error_detail(response),
                    )
                except Exception:
                    pass  # audit logging must never break the actual request

        return response
