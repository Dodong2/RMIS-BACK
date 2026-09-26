"""The registration form's leader pickers call users/by-role/, so every projects.register role (0009) needs
accounts.view_users_by_role too, or manual entry has no Project/Study Leader to choose."""

from django.db import migrations

ADDED = ["drd", "riuh", "program_leader", "project_leader", "study_leader"]


def grant(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    RolePermission = apps.get_model("accounts", "RolePermission")
    perm = Permission.objects.get(code="accounts.view_users_by_role")
    for role in Role.objects.filter(code__in=ADDED):
        RolePermission.objects.get_or_create(role=role, permission=perm)


def revoke(apps, schema_editor):
    apps.get_model("accounts", "RolePermission").objects.filter(
        permission__code="accounts.view_users_by_role", role__code__in=ADDED
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0009_widen_projects_register")]

    operations = [migrations.RunPython(grant, revoke)]
