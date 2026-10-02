import datetime

from accounts.testing import RMISTestCase
from research_projects.models import Project


class RegistrationRowsTests(RMISTestCase):
    """The manual registration wizard saves Section V (6Ps) and XI (work plan) like the Excel import does."""

    def setUp(self):
        super().setUp()
        self.leader = self.make_user("project_leader")
        self.project = Project.objects.create(title="P", project_code="P-1", funding_type="institutional", lead=self.leader)

    def add_output(self, user):
        return self.client_for(user).post("/api/outputs/expected-outputs/", {
            "project": self.project.pk, "category": "people_services", "description": "x" * 400, "target_count": 2000,
        }, format="json")

    def add_milestone(self, user):
        return self.client_for(user).post("/api/milestones/", {
            "project": self.project.pk, "title": "Logistic preparations", "target_date": datetime.date(2026, 3, 31),
        }, format="json")

    def test_crc_chair_registering_a_project_can_add_its_6ps_and_work_plan(self):
        crc = self.make_user("crc_chair")

        self.assertEqual(self.add_output(crc).status_code, 201)
        self.assertEqual(self.add_milestone(crc).status_code, 201)

    def test_particulars_take_the_forms_full_text(self):
        response = self.add_output(self.leader)

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(len(response.data["description"]), 400)

    def test_leaders_add_6ps_only_to_their_own_projects(self):
        other = self.make_user("project_leader")

        self.assertEqual(self.add_output(other).status_code, 400)

    def test_roles_without_either_permission_are_still_blocked(self):
        staff = self.make_user("project_staff")

        self.assertEqual(self.add_output(staff).status_code, 403)
        self.assertEqual(self.add_milestone(staff).status_code, 403)
