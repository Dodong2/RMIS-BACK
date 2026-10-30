"""Task 27 (2026-10-30, Carl Q4): a Project Leader may run a Budget Forecast for the projects they lead (the view keeps
the row scope)."""

from django.db import migrations


def forwards(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    RolePermission = apps.get_model("accounts", "RolePermission")
    perm = Permission.objects.filter(code="forecasting.run").first()
    role = Role.objects.filter(code="project_leader").first()
    if perm and role:
        RolePermission.objects.get_or_create(role=role, permission=perm)


def backwards(apps, schema_editor):
    RolePermission = apps.get_model("accounts", "RolePermission")
    RolePermission.objects.filter(permission__code="forecasting.run", role__code="project_leader").delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0029_reminderlog")]

    operations = [migrations.RunPython(forwards, backwards)]
