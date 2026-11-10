"""Client Task 54 (2026-11-10, Carl): Personnel Coordination and Personnel Changes are read by system_admin, vprei,
university_admin, crc_chair and riuh only (new personnel.view_coordination); Leader Load adds vprei and
university_admin; Procurement no longer acknowledges property clearance (PAR). Writes stay system_admin/riuh."""

from django.db import migrations

VIEW_COORDINATION = ["system_admin", "vprei", "university_admin", "crc_chair", "riuh"]
LEADER_LOAD_ADDED = ["vprei", "university_admin"]


def grant(apps, code, role_codes):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    RolePermission = apps.get_model("accounts", "RolePermission")
    perm = Permission.objects.filter(code=code).first()
    if perm:
        for role in Role.objects.filter(code__in=role_codes):
            RolePermission.objects.get_or_create(role=role, permission=perm)


def forwards(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    RolePermission = apps.get_model("accounts", "RolePermission")
    Permission.objects.get_or_create(
        code="personnel.view_coordination",
        defaults={"module": "personnel", "name": "View Personnel Coordination and Personnel Changes"},
    )
    grant(apps, "personnel.view_coordination", VIEW_COORDINATION)
    grant(apps, "personnel.view_leader_load", LEADER_LOAD_ADDED)
    RolePermission.objects.filter(role__code="procurement_officer_lib", permission__code="personnel.clearance").delete()


def backwards(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    RolePermission = apps.get_model("accounts", "RolePermission")
    Permission.objects.filter(code="personnel.view_coordination").delete()
    RolePermission.objects.filter(role__code__in=LEADER_LOAD_ADDED, permission__code="personnel.view_leader_load").delete()
    grant(apps, "personnel.clearance", ["procurement_officer_lib"])


class Migration(migrations.Migration):
    dependencies = [("accounts", "0031_crc_view_only")]

    operations = [migrations.RunPython(forwards, backwards)]
