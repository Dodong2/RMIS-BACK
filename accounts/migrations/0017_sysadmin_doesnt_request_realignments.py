"""Client 2026-10-11: system_admin only approves; filing a realignment request is the project leader's job."""

from django.db import migrations


def forwards(apps, schema_editor):
    RolePermission = apps.get_model("accounts", "RolePermission")
    RolePermission.objects.filter(permission__code="financial.request_realignment", role__code="system_admin").delete()


def backwards(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    RolePermission = apps.get_model("accounts", "RolePermission")
    perm = Permission.objects.filter(code="financial.request_realignment").first()
    admin = Role.objects.filter(code="system_admin").first()
    if perm and admin:
        RolePermission.objects.get_or_create(role=admin, permission=perm)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0016_reviewers_dont_encode_budgets")]

    operations = [migrations.RunPython(forwards, backwards)]
