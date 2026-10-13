"""Client 2026-10-14: R&D Quarterly Progress Reports. Roles from Structure Module 9 + Clarification 1a/1b/1c, agreed
with Carl: Project Leader prepares, RIUH / CRC Chair review and endorse, DRD / VPREI give final approval. No
system_admin on purpose (same as financial.request_realignment, 2026-10-11)."""

from django.db import migrations

PERMISSIONS = {
    "monitoring.quarterly_prepare": ("Prepare and submit R&D quarterly progress reports", ["project_leader"]),
    "monitoring.quarterly_review": (
        "Review, return and endorse R&D quarterly progress reports", ["riuh", "crc_chair", "drd", "vprei"],
    ),
    "monitoring.quarterly_approve": ("Give final approval to R&D quarterly progress reports", ["drd", "vprei"]),
}


def forwards(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    RolePermission = apps.get_model("accounts", "RolePermission")
    for code, (name, roles) in PERMISSIONS.items():
        perm, _ = Permission.objects.update_or_create(code=code, defaults={"module": "monitoring", "name": name})
        for role in Role.objects.filter(code__in=roles):
            RolePermission.objects.get_or_create(role=role, permission=perm)


def backwards(apps, schema_editor):
    apps.get_model("accounts", "Permission").objects.filter(code__in=PERMISSIONS).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0020_project_leader_view_portfolio")]

    operations = [migrations.RunPython(forwards, backwards)]
