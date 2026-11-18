"""Client Task 85-B (2026-11-18): RIUH's Personnel & Tasks follow its project scope (campus + College Unit, 85-A)."""
import datetime

from accounts.testing import RMISTestCase
from personnel.models import Task
from research_projects.models import Project

URL = "/api/personnel/tasks/"
CAS = "CAS - College of Arts and Sciences"


class RIUHTaskScopeTests(RMISTestCase):
    def setUp(self):
        super().setUp()
        leader = self.make_user("project_leader")
        self.staff = self.make_user("project_staff")
        self.tasks = {}
        for key, campus, college in (("own", "Siniloan", CAS), ("other_college", "Siniloan", "CCS - College of Computer Studies"),
                                     ("other_campus", "Los Baños", CAS)):
            project = Project.objects.create(title=key, project_code=key, campus=campus, college=college,
                                             funding_type="externally_funded", lead=leader)
            self.tasks[key] = Task.objects.create(project=project, title=key, assignee=self.staff, assigned_by=leader,
                                                  due_date=datetime.date(2026, 12, 1))
        self.riuh = self.client_for(self.make_user("riuh", campus="Siniloan", college_unit=CAS))

    def test_list_shows_only_tasks_of_projects_in_scope(self):
        titles = [t["title"] for t in self.riuh.get(URL).data]
        self.assertEqual(titles, ["own"])

    def test_detail_outside_scope_is_404(self):
        self.assertEqual(self.riuh.get(f"{URL}{self.tasks['own'].pk}/").status_code, 200)
        self.assertEqual(self.riuh.get(f"{URL}{self.tasks['other_college'].pk}/").status_code, 404)
        self.assertEqual(self.riuh.get(f"{URL}{self.tasks['other_campus'].pk}/").status_code, 404)
        self.assertEqual(self.riuh.get(f"{URL}{self.tasks['own'].pk}/updates/").status_code, 200)
        self.assertEqual(self.riuh.get(f"{URL}{self.tasks['other_campus'].pk}/updates/").status_code, 404)

    def test_riuh_without_campus_or_college_is_not_limited(self):
        unscoped = self.client_for(self.make_user("riuh"))
        self.assertEqual(len(unscoped.get(URL).data), 3)
        self.assertEqual(unscoped.get(f"{URL}{self.tasks['other_campus'].pk}/updates/").status_code, 200)

    def test_other_roles_unchanged(self):
        self.assertEqual(len(self.client_for(self.make_user("system_admin")).get(URL).data), 3)
        self.assertEqual(len(self.client_for(self.staff).get(URL).data), 3)
