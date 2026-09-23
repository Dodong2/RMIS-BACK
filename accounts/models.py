from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.Model):
    code = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class User(AbstractUser):
    REGISTRATION_METHOD_CHOICES = (
        ("email", "Email"),
        ("google", "Google"),
    )

    email = models.EmailField(unique=True)
    role = models.ForeignKey(Role, null=True, blank=True, on_delete=models.SET_NULL, related_name="users")
    requested_role = models.ForeignKey(Role, null=True, blank=True, on_delete=models.SET_NULL, related_name="requested_by")
    scope = models.JSONField(default=dict, blank=True)
    supabase_uid = models.CharField(max_length=64, blank=True, null=True, unique=True)
    is_pending_role = models.BooleanField(default=True)
    registration_method = models.CharField(max_length=10, choices=REGISTRATION_METHOD_CHOICES, default="email")

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    def __str__(self):
        return self.email


class AuditLog(models.Model):
    """Request-level audit trail — who called which mutating API endpoint,
    when, and what it returned. Populated by AuditLogMiddleware for every
    authenticated POST/PUT/PATCH/DELETE to /api/, not a per-model change diff
    — matches how the MIT proposal frames it ('the business logic layer...
    enforces authentication, role-based access control, request validation,
    and audit logging before any request reaches the data layer'), i.e. a
    cross-cutting request concern rather than granular field-level history."""

    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_logs")
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=500)
    status_code = models.PositiveSmallIntegerField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.method} {self.path} ({self.status_code}) by {self.actor_id} at {self.created_at:%Y-%m-%d %H:%M}"