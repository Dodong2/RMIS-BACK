"""Client 2026-10-18: the Project Leader adds Project Staff left out at registration, from the project's Team tab.
The row is the same ProjectTeamMember as Step 2, so it also shows on the SF-018."""
from accounts.testing import RMISTestCase

from .importer import proposal_preview
from .models import Project, ProjectTeamMember


class AddTeamMemberTests(RMISTestCase):
    def setUp(self):
        super().setUp()
        self.leader = self.make_user("project_leader", first_name="Lea", last_name="Der")
        self.staff = self.make_user("project_staff", first_name="Sta", last_name="Ff")
        self.project = Project.objects.create(title="P", project_code="P-1", funding_type="core_funded", lead=self.leader)
        self.url = f"/api/projects/{self.project.id}/team/add-member/"

    def add(self, actor, **data):
        return self.client_for(actor).post(self.url, data, format="json")

    def test_leader_adds_a_staff_account_as_project_staff(self):
        response = self.add(self.leader, user=self.staff.id, name="Sta Ff", gender="female")
        self.assertEqual(response.status_code, 201, response.data)
        row = ProjectTeamMember.objects.get(project=self.project)
        self.assertEqual((row.member_role, row.user, row.name, row.gender), ("member", self.staff, "Sta Ff", "female"))

    def test_role_is_always_project_staff(self):
        response = self.add(self.leader, name="EIU Coordinators", member_role="co_leader")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(ProjectTeamMember.objects.get().member_role, "member")

    def test_typed_name_without_account_is_allowed(self):
        self.assertEqual(self.add(self.leader, name="EIU Coordinators").status_code, 201)

    def test_name_is_required(self):
        self.assertEqual(self.add(self.leader, name="  ").status_code, 400)
        self.assertFalse(ProjectTeamMember.objects.exists())

    def test_only_the_projects_own_leader_adds(self):
        for user in (self.make_user("project_leader"), self.make_user("system_admin"), self.make_user("crc_chair"), self.staff):
            self.assertIn(self.add(user, name="Someone").status_code, (403, 404), user.role.code)
        self.assertFalse(ProjectTeamMember.objects.exists())

    def test_any_project_status(self):
        """Client 2026-10-18 (later): the button doesn't depend on the project being active."""
        Project.objects.filter(pk=self.project.pk).update(status="completed")
        self.assertEqual(self.add(self.leader, name="Someone").status_code, 201)

    def test_account_must_be_project_staff(self):
        other_leader = self.make_user("project_leader")
        self.assertEqual(self.add(self.leader, user=other_leader.id, name="X").status_code, 400)

    def test_duplicates_are_refused(self):
        self.project.team_members.create(member_role="member", name="Sta Ff", user=self.staff)
        self.project.team_members.create(member_role="co_leader", name="Maria Cruz")
        self.assertEqual(self.add(self.leader, user=self.staff.id, name="Other spelling").status_code, 400)
        self.assertEqual(self.add(self.leader, name="  maria cruz ").status_code, 400)
        self.assertEqual(self.add(self.leader, name="Lea Der").status_code, 400)
        self.assertEqual(self.project.team_members.count(), 2)

    def test_added_member_shows_on_the_sf018(self):
        self.add(self.leader, user=self.staff.id, name="Sta Ff")
        self.assertIn("Sta Ff", [m["name"] for m in proposal_preview(self.project)["team"]])
