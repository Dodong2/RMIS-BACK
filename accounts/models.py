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