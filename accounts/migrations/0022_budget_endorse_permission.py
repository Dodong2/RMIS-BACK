"""Client 2026-10-18: a LIB is endorsed by the CRC Chair before the Budget Officer certifies it."""

from django.db import migrations

CODE = "budget.endorse"
ROLES = ["system_admin", "crc_chair"]


def forwards(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    RolePermission = apps.get_model("accounts", "RolePermission")
    perm, _ = Permission.objects.update_or_create(
        code=CODE, defaults={"module": "budget_lib", "name": "Endorse or return a LIB before certification (CRC Chair)"},
    )
    for role in Role.objects.filter(code__in=ROLES):
        RolePermission.objects.get_or_create(role=role, permission=perm)


def backwards(apps, schema_editor):
    apps.get_model("accounts", "Permission").objects.filter(code=CODE).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0021_quarterly_report_permissions")]

    operations = [migrations.RunPython(forwards, backwards)]
