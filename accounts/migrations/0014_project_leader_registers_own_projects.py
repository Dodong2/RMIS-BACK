"""Client meeting 2026-10-01: the Project Leader registers their own approved project again (manual entry and Excel
import), alongside CRC Chair, DRD and RIUH. Partly reverses 0013 for project_leader only; program and study leaders
stay edit-only. The serializer limits a Project Leader to projects they lead."""

from django.db import migrations


def forward(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Permission = apps.get_model("accounts", "Permission")
    RolePermission = apps.get_model("accounts", "RolePermission")
    register = Permission.objects.filter(code="projects.register").first()
    role = Role.objects.filter(code="project_leader").first()
    if register and role:
        RolePermission.objects.get_or_create(role=role, permission=register)


def backward(apps, schema_editor):
    RolePermission = apps.get_model("accounts", "RolePermission")
    RolePermission.objects.filter(permission__code="projects.register", role__code="project_leader").delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0013_split_projects_register_edit")]

    operations = [migrations.RunPython(forward, backward)]
