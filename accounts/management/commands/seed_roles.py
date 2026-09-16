from django.core.management.base import BaseCommand
from accounts.models import Role

ROLES = [
    ("system_admin", "System Admin", "system_admin"),
    ("vprei", "VP for REI", "institution_oversight"),
    ("university_admin", "University Administration", "institution_oversight"),
    ("drd", "DRD", "institution_oversight"),
    ("crc_chair", "CRC Chairperson", "campus_coordination"),
    ("riuh", "RIUH", "college_oversight"),
    ("finance_budget", "Finance/Accounting/Budget", "finance"),
    ("procurement_officer_lib", "Procurement Officer - LIB", "procurement"),
    ("program_leader", "Program Leader", "project_management"),
    ("project_leader", "Project Leader", "project_management"),
    ("study_leader", "Study Leader", "study_management"),
    ("project_staff", "Project Staff", "execution"),
]


class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        for code, name, tier in ROLES:
            Role.objects.update_or_create(code=code, defaults={"name": name, "tier": tier})
        self.stdout.write(self.style.SUCCESS(f"Seeded {len(ROLES)} roles."))