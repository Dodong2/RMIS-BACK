"""Client 2026-10-13: Analytics > Portfolio counts every project, so the endpoint is limited to the Analytics roles."""

from django.db import migrations

CODE = "dashboard.view_portfolio"
ROLES = [
    "system_admin", "vprei", "university_admin", "drd", "crc_chair", "riuh", "finance_budget",
    "procurement_officer_lib", "program_leader",
]


def forwards(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    RolePermission = apps.get_model("accounts", "RolePermission")
    perm, _ = Permission.objects.update_or_create(
        code=CODE, defaults={"module": "dashboard", "name": "View Analytics > Portfolio (counts across all projects)"}
    )
    for role in Role.objects.filter(code__in=ROLES):
        RolePermission.objects.get_or_create(role=role, permission=perm)


def backwards(apps, schema_editor):
    apps.get_model("accounts", "Permission").objects.filter(code=CODE).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0018_idempotencykey")]

    operations = [migrations.RunPython(forwards, backwards)]
