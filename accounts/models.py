from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.Model):
    """One row per actor type from the client's role list."""
    code = models.SlugField(unique=True)          # e.g. "system_admin", "project_leader"
    name = models.CharField(max_length=120)        # e.g. "System Administrator"
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class User(AbstractUser):
    email = models.EmailField(unique=True)
    role = models.ForeignKey(Role, null=True, blank=True, on_delete=models.SET_NULL, related_name="users")

    # scope: which college/program/project this role applies to — flexible for now,
    # normalize into real FKs once Projects/Colleges models exist (Phase 1 continuation)
    scope = models.JSONField(default=dict, blank=True)

    # set when the user came in via Google OAuth, so Django knows not to expect a usable password
    supabase_uid = models.CharField(max_length=64, blank=True, null=True, unique=True)

    is_pending_role = models.BooleanField(default=False)  # True right after Google sign-up, until admin assigns a role

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    def __str__(self):
        return self.email