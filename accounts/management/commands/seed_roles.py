from django.core.management.base import BaseCommand
from accounts.models import Role

ROLES = [
    ("system_admin", "System Administrator"),
    ("vprei", "VP for REI"),
    ("drd", "Director for Research and Development"),
    ("crc", "Campus Research Coordinator"),
    ("riuh", "Research Implementing Unit Head"),
    ("dean", "Dean / Associate Dean"),
    ("budget_officer", "Budget Officer"),
    ("program_leader", "Program Leader"),
    ("project_leader", "Project Leader"),
    ("study_leader", "Study Leader"),
    ("project_staff", "Project Staff"),
    ("pdrcu", "Project Development & Resource Coordination Unit"),
    ("pmeu", "Project Monitoring and Evaluation Unit"),
    ("riau", "Research Integrity and Assurance Unit"),
    ("rfmu", "Research Facility Management Unit"),
    ("cwmu", "Creative Works Management Unit"),
    ("finance", "Finance/Accounting Office"),
    ("university_admin", "University Administration"),
]

class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        for code, name in ROLES:
            Role.objects.get_or_create(code=code, defaults={"name": name})
        self.stdout.write(self.style.SUCCESS(f"Seeded {len(ROLES)} roles."))