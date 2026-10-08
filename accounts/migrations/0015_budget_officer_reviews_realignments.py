"""Client 2026-10-08: the Finance/Budget Officer approves budget realignments (both the major and the BOR tier);
system_admin keeps both for testing. university_admin no longer reviews major realignments."""

from django.db import migrations

CODES = ["financial.review_major_realignment", "financial.review_bor_realignment"]


def forwards(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    RolePermission = apps.get_model("accounts", "RolePermission")
    officer = Role.objects.filter(code="finance_budget").first()
    if officer:
        for perm in Permission.objects.filter(code__in=CODES):
            RolePermission.objects.get_or_create(role=officer, permission=perm)
    RolePermission.objects.filter(permission__code="financial.review_major_realignment", role__code="university_admin").delete()


def backwards(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    RolePermission = apps.get_model("accounts", "RolePermission")
    RolePermission.objects.filter(permission__code__in=CODES, role__code="finance_budget").delete()
    admin = Role.objects.filter(code="university_admin").first()
    perm = Permission.objects.filter(code="financial.review_major_realignment").first()
    if admin and perm:
        RolePermission.objects.get_or_create(role=admin, permission=perm)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0014_project_leader_registers_own_projects")]

    operations = [migrations.RunPython(forwards, backwards)]
