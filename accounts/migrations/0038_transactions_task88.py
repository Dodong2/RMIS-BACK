"""Client Task 88-A (2026-11-27): Transactions page for System Admin, Finance/Accounting/Budget and Procurement
Officer - LIB. New transactions.view (not budget.*: lib_signal reaches every role holding a budget.* permission) gates budget/transactions/ (list, filters, export)."""

from django.db import migrations

ROLES = ["system_admin", "finance_budget", "procurement_officer_lib"]


def forwards(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    RolePermission = apps.get_model("accounts", "RolePermission")
    perm, _ = Permission.objects.get_or_create(
        code="transactions.view",
        defaults={"module": "budget_lib", "name": "Open Transactions (approved and processed budget/procurement actions)"},
    )
    for role in Role.objects.filter(code__in=ROLES):
        RolePermission.objects.get_or_create(role=role, permission=perm)


def backwards(apps, schema_editor):
    apps.get_model("accounts", "Permission").objects.filter(code="transactions.view").delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0037_quarterly_flow_task84")]

    operations = [migrations.RunPython(forwards, backwards)]
