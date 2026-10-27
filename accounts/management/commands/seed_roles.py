from django.core.management.base import BaseCommand
from accounts.models import Role
from accounts.permission_seed import sync_role_permissions

ROLES = [
    ("system_admin", "System Admin"),
    ("vprei", "VP for REI"),
    ("university_admin", "University Administration"),
    ("crc_chair", "CRC/CRD"),  # DRD merged in (client 2026-10-27)
    ("riuh", "RIUH"),
    ("finance_budget", "Finance/Accounting/Budget"),
    ("procurement_officer_lib", "Procurement Officer - LIB"),
    ("project_leader", "Project Leader/Program Leader/Study Leader"),  # one role since 2026-10-27
    ("project_staff", "Project Staff"),
]


class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        for code, name in ROLES:
            Role.objects.update_or_create(code=code, defaults={"name": name})
        sync_role_permissions()
        self.stdout.write(self.style.SUCCESS(f"Seeded {len(ROLES)} roles and their permissions."))