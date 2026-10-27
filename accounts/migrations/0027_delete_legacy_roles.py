"""Client 2026-10-27, contract step after 0026: delete the DRD, Program Leader and Study Leader roles. 0026 already moved
their accounts and grants and no code uses them, so this stops (and changes nothing) if an account still has one."""

from django.db import migrations

LEGACY = {"drd": "DRD", "program_leader": "Program Leader", "study_leader": "Study Leader"}


def forwards(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    User = apps.get_model("accounts", "User")
    from django.db.models import Q

    still_used = User.objects.filter(Q(role__code__in=LEGACY) | Q(requested_role__code__in=LEGACY))
    if still_used.exists():
        raise RuntimeError(f"{still_used.count()} account(s) still have a legacy role; run 0026 first.")
    Role.objects.filter(code__in=LEGACY).delete()


def backwards(apps, schema_editor):
    """Recreates the roles (no accounts); reversing 0026 then gives them their grants back."""
    Role = apps.get_model("accounts", "Role")
    for code, name in LEGACY.items():
        Role.objects.get_or_create(code=code, defaults={"name": name})


class Migration(migrations.Migration):
    dependencies = [("accounts", "0026_merge_roles")]

    operations = [migrations.RunPython(forwards, backwards)]
