"""Client Task 90-A (2026-11-27): Work Plan milestone changes after registration. Leader proposes (request), RIUH
confirms or returns (review), CRC/CRD is notified and can read them (view)."""

from django.db import migrations

PERMISSIONS = {
    "milestone_changes.view": ("Open Milestone Changes (Work Plan changes after registration)",
                               ["system_admin", "project_leader", "riuh", "crc_chair"]),
    "milestone_changes.request": ("Propose a Work Plan milestone change for RIUH confirmation", ["system_admin", "project_leader"]),
    "milestone_changes.review": ("Confirm or return Work Plan milestone changes", ["system_admin", "riuh"]),
}


def forwards(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    RolePermission = apps.get_model("accounts", "RolePermission")
    for code, (name, roles) in PERMISSIONS.items():
        perm, _ = Permission.objects.get_or_create(code=code, defaults={"module": "research_projects", "name": name})
        for role in Role.objects.filter(code__in=roles):
            RolePermission.objects.get_or_create(role=role, permission=perm)


def backwards(apps, schema_editor):
    apps.get_model("accounts", "Permission").objects.filter(code__in=PERMISSIONS).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0039_progress_reports_task89")]

    operations = [migrations.RunPython(forwards, backwards)]
