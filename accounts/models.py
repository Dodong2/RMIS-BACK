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
    # Suspend = temporary login block, role/assignments kept (e.g. leave, sabbatical).
    # Deactivate = permanent end of the account (retired, resigned) — no hard delete.
    # Login itself is still gated by is_active, which these keep in sync (client clarification Q3).
    ACCOUNT_STATUS_CHOICES = (
        ("active", "Active"),
        ("suspended", "Suspended"),
        ("deactivated", "Deactivated"),
    )
    account_status = models.CharField(max_length=20, choices=ACCOUNT_STATUS_CHOICES, default="active")
    office = models.CharField(max_length=150, blank=True, help_text="Office/department (college, unit, campus office)")
    position = models.CharField(max_length=150, blank=True, help_text="Plantilla/academic position, e.g. Associate Professor II")

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


class Permission(models.Model):
    """One gated action, e.g. "budget.certify" (client clarification Q2: role -> permission lives in the
    database, seeded at deployment, viewable — not hardcoded in if-statements)."""

    code = models.CharField(max_length=80, unique=True)
    module = models.CharField(max_length=50)
    name = models.CharField(max_length=200)

    def __str__(self):
        return self.code


class RolePermission(models.Model):
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="role_permissions")
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE, related_name="role_permissions")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["role", "permission"], name="unique_role_permission")]

    def __str__(self):
        return f"{self.role.code} -> {self.permission.code}"


class TemporaryReplacement(models.Model):
    """Acting replacement for a suspended user (client clarification Q3: suspend keeps assignments and can assign a
    temporary replacement). While current, the replacement also sees and manages the programs/projects/studies the
    suspended user leads, via accounts.permissions.scoped_projects. The replacement's own role is unchanged (one role
    per user), so write permissions still come from that role. Ended, never deleted, so the history stays."""

    suspended_user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="replacements")
    replacement = models.ForeignKey(User, on_delete=models.PROTECT, related_name="acting_for")
    designation = models.CharField(max_length=150, blank=True, help_text="e.g. Study Leader (Acting)")
    coverage = models.TextField(blank=True, help_text="What the replacement covers")
    start_date = models.DateField()
    end_date = models.DateField()
    basis = models.CharField(max_length=200, blank=True, help_text="Office order / memo number")
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="replacements_created")
    created_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True, help_text="Set when ended early or the user is reactivated")

    def __str__(self):
        return f"{self.replacement} acting for {self.suspended_user} ({self.start_date} to {self.end_date})"
