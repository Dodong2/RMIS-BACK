from .models import AuditLog

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


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
                    )
                except Exception:
                    pass  # audit logging must never break the actual request

        return response
