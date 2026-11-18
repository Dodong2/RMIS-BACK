"""Client Task 84 (2026-11-18): R&D Quarterly Progress Reports follow PL Submit > RIUH Endorse > CRC/CRD Approve.
monitoring.quarterly_review = riuh only (was riuh, crc_chair, vprei); monitoring.quarterly_approve = crc_chair only
(was vprei). VP for REI keeps read access through visible_projects."""

from django.db import migrations

BEFORE = {"monitoring.quarterly_review": ["riuh", "crc_chair", "vprei"], "monitoring.quarterly_approve": ["vprei"]}
AFTER = {"monitoring.quarterly_review": ["riuh"], "monitoring.quarterly_approve": ["crc_chair"]}


def apply(grants):
    def run(apps, schema_editor):
        Permission = apps.get_model("accounts", "Permission")
        Role = apps.get_model("accounts", "Role")
        RolePermission = apps.get_model("accounts", "RolePermission")
        for code, roles in grants.items():
            perm = Permission.objects.filter(code=code).first()
            if perm is None:
                continue
            RolePermission.objects.filter(permission=perm).exclude(role__code__in=roles).delete()
            for role in Role.objects.filter(code__in=roles):
                RolePermission.objects.get_or_create(role=role, permission=perm)
    return run


class Migration(migrations.Migration):
    dependencies = [("accounts", "0036_procurement_analytics_task82")]

    operations = [migrations.RunPython(apply(AFTER), apply(BEFORE))]
