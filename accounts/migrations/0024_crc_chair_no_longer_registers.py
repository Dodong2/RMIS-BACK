"""Client 2026-10-24: the CRC Chair reviews submitted projects and no longer registers them, so the CRC Chair loses
projects.register (Register Approved Project, the Excel import, Add Study). projects.edit stays."""

from django.db import migrations


def forwards(apps, schema_editor):
    RolePermission = apps.get_model("accounts", "RolePermission")
    RolePermission.objects.filter(permission__code="projects.register", role__code="crc_chair").delete()


def backwards(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    RolePermission = apps.get_model("accounts", "RolePermission")
    perm = Permission.objects.filter(code="projects.register").first()
    role = Role.objects.filter(code="crc_chair").first()
    if perm and role:
        RolePermission.objects.get_or_create(role=role, permission=perm)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0023_only_project_leaders_encode_libs")]

    operations = [migrations.RunPython(forwards, backwards)]
