"""Client Task 82 (2026-11-18): Procurement Analytics for System Admin, Procurement Officer - LIB and University
Administration. New procurement.view_analytics gates dashboard/procurement/ (was financial.update_procurement)."""

from django.db import migrations

ROLES = ["system_admin", "procurement_officer_lib", "university_admin"]


def forwards(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    RolePermission = apps.get_model("accounts", "RolePermission")
    perm, _ = Permission.objects.get_or_create(
        code="procurement.view_analytics",
        defaults={"module": "dashboard", "name": "Open Procurement Analytics (procurement requests and figures)"},
    )
    for role in Role.objects.filter(code__in=ROLES):
        RolePermission.objects.get_or_create(role=role, permission=perm)


def backwards(apps, schema_editor):
    apps.get_model("accounts", "Permission").objects.filter(code="procurement.view_analytics").delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0035_compliance_roles_task79")]

    operations = [migrations.RunPython(forwards, backwards)]
