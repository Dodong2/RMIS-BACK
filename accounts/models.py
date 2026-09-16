from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.Model):
    code = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
    tier = models.SlugField()
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class User(AbstractUser):
    email = models.EmailField(unique=True)
    role = models.ForeignKey(Role, null=True, blank=True, on_delete=models.SET_NULL, related_name="users")
    scope = models.JSONField(default=dict, blank=True)
    supabase_uid = models.CharField(max_length=64, blank=True, null=True, unique=True)
    is_pending_role = models.BooleanField(default=False)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    def __str__(self):
        return self.email