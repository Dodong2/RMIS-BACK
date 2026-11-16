"""Client Task 66 (2026-11-16): Budget Forecast (ARIMA) is for the Project Leader, RIUH, CRC/CRD and
Finance/Accounting/Budget (+ system_admin). RIUH and CRC/CRD get forecasting.run; VP for REI loses it."""

from django.db import migrations

ADDED = ["riuh", "crc_chair"]
REMOVED = ["vprei"]


def set_roles(apps, add, remove):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    RolePermission = apps.get_model("accounts", "RolePermission")
    perm = Permission.objects.filter(code="forecasting.run").first()
    if perm is None:
        return
    for role in Role.objects.filter(code__in=add):
        RolePermission.objects.get_or_create(role=role, permission=perm)
    RolePermission.objects.filter(role__code__in=remove, permission=perm).delete()


def forwards(apps, schema_editor):
    set_roles(apps, ADDED, REMOVED)


def backwards(apps, schema_editor):
    set_roles(apps, REMOVED, ADDED)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0032_personnel_coordination_access")]

    operations = [migrations.RunPython(forwards, backwards)]
