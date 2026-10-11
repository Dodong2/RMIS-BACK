"""Client 2026-10-11: the Finance/Budget Officer and system_admin only certify LIBs and approve realignments.
They can no longer create a LIB or add/edit its line items (budget.manage); the project leader encodes it."""

from django.db import migrations

ROLES = ["finance_budget", "system_admin"]


def forwards(apps, schema_editor):
    RolePermission = apps.get_model("accounts", "RolePermission")
    RolePermission.objects.filter(permission__code="budget.manage", role__code__in=ROLES).delete()


def backwards(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    RolePermission = apps.get_model("accounts", "RolePermission")
    perm = Permission.objects.filter(code="budget.manage").first()
    if perm:
        for role in Role.objects.filter(code__in=ROLES):
            RolePermission.objects.get_or_create(role=role, permission=perm)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0015_budget_officer_reviews_realignments")]

    operations = [migrations.RunPython(forwards, backwards)]
