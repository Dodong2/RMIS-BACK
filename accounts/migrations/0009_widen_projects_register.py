"""Module Structure docx, Module 2 primary users: CRC/CRD, DRD, RIUH, Program/Project/Study Leaders may register
projects (manually or by Excel import). Adds the roles missing from 0008's projects.register seed."""

from django.db import migrations

ADDED = ["drd", "riuh", "program_leader", "project_leader", "study_leader"]


def grant(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    RolePermission = apps.get_model("accounts", "RolePermission")
    perm = Permission.objects.get(code="projects.register")
    for role in Role.objects.filter(code__in=ADDED):
        RolePermission.objects.get_or_create(role=role, permission=perm)


def revoke(apps, schema_editor):
    apps.get_model("accounts", "RolePermission").objects.filter(
        permission__code="projects.register", role__code__in=ADDED
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0008_seed_permissions")]

    operations = [migrations.RunPython(grant, revoke)]
