from django.contrib.auth.models import AbstractUser
from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import RegexValidator
from django.db import models

# Registration fields (client 2026-10-27). Staff ID is 6 digits until the client gives the real format; change only
# these two lines then.
STAFF_ID_PATTERN = r"^\d{6}$"
STAFF_ID_MESSAGE = "Staff ID must be 6 digits."
MOBILE_PATTERN = r"^(09|\+639)\d{9}$"
MOBILE_MESSAGE = "Enter a mobile number like 09171234567 or +639171234567."
PROFILE_EDIT_LIMIT = 3


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
        ("rejected", "Rejected"),
    )
    account_status = models.CharField(max_length=20, choices=ACCOUNT_STATUS_CHOICES, default="active")
    office = models.CharField(max_length=150, blank=True, help_text="Office/department (college, unit, campus office)")
    position = models.CharField(max_length=150, blank=True, help_text="Plantilla/academic position, e.g. Associate Professor II")

    GENDER_CHOICES = (("male", "Male"), ("female", "Female"))
    # The four LSPU campuses, spelled like the project registration's campus cards (Project.campus).
    CAMPUS_CHOICES = (
        ("San Pablo City", "San Pablo City"),
        ("Siniloan", "Siniloan"),
        ("Los Baños", "Los Baños"),
        ("Sta. Cruz", "Sta. Cruz"),
    )
    # Required on registration (client 2026-10-27), blank only for accounts made before it.
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, blank=True)
    campus = models.CharField(max_length=100, choices=CAMPUS_CHOICES, blank=True)
    college_unit = models.CharField(max_length=100, blank=True, help_text="A CollegeUnit name, kept as text")
    mobile_number = models.CharField(max_length=13, blank=True, validators=[RegexValidator(MOBILE_PATTERN, MOBILE_MESSAGE)])
    staff_id = models.CharField(
        max_length=20, unique=True, null=True, blank=True, validators=[RegexValidator(STAFF_ID_PATTERN, STAFF_ID_MESSAGE)],
        error_messages={"unique": "This Staff ID is already registered."},
    )
    email_verified_at = models.DateTimeField(null=True, blank=True)
    # Successful self-service edits on the Profile page (client 2026-10-28), at most PROFILE_EDIT_LIMIT. The System
    # Admin's edits in User & Access don't count and don't reset it.
    profile_edit_count = models.PositiveSmallIntegerField(default=0)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    def __str__(self):
        return self.email

    @property
    def display_name(self):
        """Name shown across the system (client request 2026-10-07). Older accounts registered before names were
        required fall back to the e-mail until an admin fills the name in."""
        return self.get_full_name() or self.email


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
    # For 4xx/5xx only: the start of the response body (e.g. the 400's validation message), so a failed
    # action during client testing can be explained from the audit screen without server logs.
    error_detail = models.TextField(blank=True, default="")
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


class IdempotencyKey(models.Model):
    """
    One client intent behind an Idempotency-Key header (config/concurrency.py). The unique (user, key) INSERT is the
    claim; `response_*` is stored in the same transaction as the work, so "succeeded" never outlives a rollback.
    """

    STATE_CHOICES = (("in_progress", "In progress"), ("succeeded", "Succeeded"))

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="idempotency_keys")
    key = models.CharField(max_length=64)
    endpoint = models.CharField(max_length=255, help_text="METHOD /path the key was first used on")
    request_hash = models.CharField(max_length=64)
    state = models.CharField(max_length=20, choices=STATE_CHOICES, default="in_progress")
    response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    response_body = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "key"], name="unique_idempotency_key_per_user")]

    def __str__(self):
        return f"{self.key} ({self.state})"


class ReminderLog(models.Model):
    """Task 24 (2026-10-30): one scheduled reminder e-mail (send_scheduled_reminders), at most one per kind, run,
    recipient and record, so a repeated or overlapping run can't send it twice. A failed send stays "failed" and is
    retried by the next run. This is also the execution and delivery log."""

    KIND_CHOICES = (("payment", "Payment reminder"), ("task", "Task reminder"))
    STATUS_CHOICES = (("sent", "Sent"), ("failed", "Failed"))

    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    run_key = models.CharField(max_length=20, help_text="The scheduled run, e.g. 2026-11-07")
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name="reminder_logs")
    object_ref = models.CharField(max_length=50, help_text="What the reminder is about, e.g. project:12 or task:5")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["kind", "run_key", "recipient", "object_ref"], name="unique_reminder_per_run"),
        ]

    def __str__(self):
        return f"{self.kind} {self.run_key} -> {self.recipient_id} ({self.object_ref}): {self.status}"
