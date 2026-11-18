"""Client Task 79 (2026-11-18): only System Admin, VP for REI and University Administration have Compliance.
New compliance.view gates every Compliance endpoint (and dashboard/compliance/); compliance.encode and
compliance.manage go to the same three roles (RIUH and Project Leader lose them)."""

from django.db import migrations

COMPLIANCE = ["system_admin", "vprei", "university_admin"]
OLD = {"compliance.manage": ["system_admin", "riuh"], "compliance.encode": ["system_admin", "riuh", "project_leader"]}


def _set_roles(apps, code, role_codes):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    RolePermission = apps.get_model("accounts", "RolePermission")
    perm = Permission.objects.filter(code=code).first()
    if perm is None:
        return
    RolePermission.objects.filter(permission=perm).exclude(role__code__in=role_codes).delete()
    for role in Role.objects.filter(code__in=role_codes):
        RolePermission.objects.get_or_create(role=role, permission=perm)


def forwards(apps, schema_editor):
    apps.get_model("accounts", "Permission").objects.get_or_create(
        code="compliance.view",
        defaults={"module": "compliance", "name": "Open Compliance Tracking and read its records"},
    )
    for code in ("compliance.view", "compliance.manage", "compliance.encode"):
        _set_roles(apps, code, COMPLIANCE)


def backwards(apps, schema_editor):
    apps.get_model("accounts", "Permission").objects.filter(code="compliance.view").delete()
    for code, roles in OLD.items():
        _set_roles(apps, code, roles)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0034_dss_view_task76")]

    operations = [migrations.RunPython(forwards, backwards)]
