"""Client decision 2026-09-29 (Option A, per Clarification Answers Q4 + summary table): only CRC Chair, DRD and RIUH
register programs/projects/studies; leaders only edit their own records. Reverts 0009's leader grants on
projects.register and adds projects.edit (the register roles + the three leader roles)."""

from django.db import migrations

LEADERS = ["program_leader", "project_leader", "study_leader"]
EDIT_ROLES = ["system_admin", "crc_chair", "drd", "riuh"] + LEADERS


def forward(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    RolePermission = apps.get_model("accounts", "RolePermission")
    RolePermission.objects.filter(permission__code="projects.register", role__code__in=LEADERS).delete()
    Permission.objects.filter(code="projects.register").update(
        name="Register programs, projects, studies (incl. Excel import)"
    )
    edit, _ = Permission.objects.get_or_create(
        code="projects.edit",
        defaults={"module": "research_projects", "name": "Edit programs, projects, studies (leaders: own records only)"},
    )
    for role in Role.objects.filter(code__in=EDIT_ROLES):
        RolePermission.objects.get_or_create(role=role, permission=edit)


def backward(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    RolePermission = apps.get_model("accounts", "RolePermission")
    Permission.objects.filter(code="projects.edit").delete()
    register = Permission.objects.get(code="projects.register")
    for role in Role.objects.filter(code__in=LEADERS):
        RolePermission.objects.get_or_create(role=role, permission=register)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0012_auditlog_error_detail")]

    operations = [migrations.RunPython(forward, backward)]
