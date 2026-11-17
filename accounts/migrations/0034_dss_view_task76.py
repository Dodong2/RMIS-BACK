"""Client Task 76 (2026-11-18): only System Admin, VP for REI, University Administration and CRC/CRD may open the
Decision Support System (new dss.view, also used by dashboard/funding-allocation/). dss.manage/dss.decide unchanged."""

from django.db import migrations

DSS_VIEW = ["system_admin", "vprei", "university_admin", "crc_chair"]


def forwards(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    RolePermission = apps.get_model("accounts", "RolePermission")
    perm, _ = Permission.objects.get_or_create(
        code="dss.view",
        defaults={"module": "decision_support", "name": "Open the Decision Support System and read its data"},
    )
    for role in Role.objects.filter(code__in=DSS_VIEW):
        RolePermission.objects.get_or_create(role=role, permission=perm)


def backwards(apps, schema_editor):
    apps.get_model("accounts", "Permission").objects.filter(code="dss.view").delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0033_forecast_roles_task66")]

    operations = [migrations.RunPython(forwards, backwards)]
