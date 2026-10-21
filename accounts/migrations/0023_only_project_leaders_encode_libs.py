"""Client 2026-10-21 (LIB workflow Q9): only the Project Leader encodes a LIB; the Procurement Officer and Program
Leaders lose budget.manage."""

from django.db import migrations

ROLES = ["procurement_officer_lib", "program_leader"]


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
    dependencies = [("accounts", "0022_budget_endorse_permission")]

    operations = [migrations.RunPython(forwards, backwards)]
