from django.core.management.base import BaseCommand
from accounts.models import Role

ROLES = [
    ("system_admin", "System Admin"),
    ("vprei", "VP for REI"),
    ("university_admin", "University Administration"),
    ("drd", "DRD"),
    ("crc_chair", "CRC Chairperson"),
    ("riuh", "RIUH"),
    ("finance_budget", "Finance/Accounting/Budget"),
    ("procurement_officer_lib", "Procurement Officer - LIB"),
    ("program_leader", "Program Leader"),
    ("project_leader", "Project Leader"),
    ("study_leader", "Study Leader"),
    ("project_staff", "Project Staff"),
]


class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        for code, name in ROLES:
            Role.objects.update_or_create(code=code, defaults={"name": name})
        self.stdout.write(self.style.SUCCESS(f"Seeded {len(ROLES)} roles."))