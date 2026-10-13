"""Client 2026-10-13: Analytics is "from Project Leader up", so Project Leader also gets dashboard.view_portfolio."""

from django.db import migrations

CODE = "dashboard.view_portfolio"
ROLE = "project_leader"


def forwards(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    RolePermission = apps.get_model("accounts", "RolePermission")
    perm = Permission.objects.filter(code=CODE).first()
    role = Role.objects.filter(code=ROLE).first()
    if perm and role:
        RolePermission.objects.get_or_create(role=role, permission=perm)


def backwards(apps, schema_editor):
    apps.get_model("accounts", "RolePermission").objects.filter(permission__code=CODE, role__code=ROLE).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0019_dashboard_view_portfolio")]

    operations = [migrations.RunPython(forwards, backwards)]
