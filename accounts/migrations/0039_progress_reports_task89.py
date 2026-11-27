"""Client Task 89-A (2026-11-27): Project Progress Reports page for System Admin, Project Leader, RIUH and CRC/CRD.
New progress_reports.view gates monitoring/progress-reports/. Other report pages and roles are unchanged."""

from django.db import migrations

ROLES = ["system_admin", "project_leader", "riuh", "crc_chair"]


def forwards(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    RolePermission = apps.get_model("accounts", "RolePermission")
    perm, _ = Permission.objects.get_or_create(
        code="progress_reports.view",
        defaults={"module": "monitoring", "name": "Open Project Progress Reports (report status and forms per project)"},
    )
    for role in Role.objects.filter(code__in=ROLES):
        RolePermission.objects.get_or_create(role=role, permission=perm)


def backwards(apps, schema_editor):
    apps.get_model("accounts", "Permission").objects.filter(code="progress_reports.view").delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0038_transactions_task88")]

    operations = [migrations.RunPython(forwards, backwards)]
