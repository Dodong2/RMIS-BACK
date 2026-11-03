"""Client Task 41 (2026-11-03, Carl): CRC/CRD views Project Management, the Work Plan and Personnel & Tasks for auditing
but takes no action there: no project edits, work-plan activities, tasks, personnel records or clearances. The
Project Leader -> CRC/CRD -> Finance/Accounting/Budget review (budget.endorse) is unchanged."""

from django.db import migrations

REMOVED = (
    "projects.edit", "projects.manage_milestones", "personnel.assign_tasks", "personnel.manage", "personnel.clearance",
)


def forwards(apps, schema_editor):
    RolePermission = apps.get_model("accounts", "RolePermission")
    RolePermission.objects.filter(role__code="crc_chair", permission__code__in=REMOVED).delete()


def backwards(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    RolePermission = apps.get_model("accounts", "RolePermission")
    role = Role.objects.filter(code="crc_chair").first()
    if role:
        for perm in Permission.objects.filter(code__in=REMOVED):
            RolePermission.objects.get_or_create(role=role, permission=perm)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0030_project_leader_runs_forecast")]

    operations = [migrations.RunPython(forwards, backwards)]
