from accounts.testing import RMISTestCase
from research_projects.models import Program, Project, RdeThrust
from research_projects.rde_agenda import seed_rde_agenda
from research_projects.tests import project_payload


class RdeAgendaTestCase(RMISTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        seed_rde_agenda(RdeThrust)


class RdeAgendaSeedTests(RdeAgendaTestCase):
    """LSPU 2024-2028 RDE Agenda (LSPU-RDE-AGENDA-2024-2028.pdf pp. 27-28): 8 thrusts, 61 priority areas."""

    def test_the_agenda_is_seeded_as_thrusts_and_priority_areas(self):
        thrusts = RdeThrust.objects.filter(parent=None)
        computing = thrusts.get(code="1")

        self.assertEqual(thrusts.count(), 8)
        self.assertEqual(RdeThrust.objects.exclude(parent=None).count(), 61)
        self.assertEqual(computing.title, "Computing and Emerging Technologies")
        self.assertEqual(computing.priorities.count(), 9)
        self.assertFalse(RdeThrust.objects.filter(code="1.10").exists())
        self.assertEqual(
            RdeThrust.objects.get(code="2.6").title,
            "Water Treatment and Sanitation (Including Natural Water Filtration Systems)",
        )


class RdeAgendaAdminTests(RdeAgendaTestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.client_for(self.make_user("system_admin"))
        self.computing = RdeThrust.objects.get(code="1")

    def post(self, **data):
        return self.admin.post("/api/rde-thrusts/", data, format="json")

    def test_a_priority_area_is_added_under_its_thrust(self):
        created = self.post(code="1.10", title="Quantum Computing", parent=self.computing.pk)

        self.assertEqual(created.status_code, 201)
        self.assertEqual((created.data["name"], created.data["parent"]), ("1.10 - Quantum Computing", self.computing.pk))

    def test_a_priority_area_code_must_follow_its_thrust(self):
        self.assertEqual(self.post(code="2.10", title="X", parent=self.computing.pk).status_code, 400)
        self.assertEqual(self.post(code="1.x", title="X", parent=self.computing.pk).status_code, 400)

    def test_a_thrust_code_is_a_number(self):
        self.assertEqual(self.post(code="9", title="Space Science").status_code, 201)
        self.assertEqual(self.post(code="9.1", title="Rockets").status_code, 400)

    def test_only_two_levels(self):
        priority = RdeThrust.objects.get(code="1.1")

        self.assertEqual(self.post(code="1.1.1", title="X", parent=priority.pk).status_code, 400)

    def test_a_thrust_with_priority_areas_cannot_be_deleted(self):
        response = self.admin.delete(f"/api/rde-thrusts/{self.computing.pk}/")

        self.assertEqual(response.status_code, 400)
        self.assertTrue(RdeThrust.objects.filter(pk=self.computing.pk).exists())

    def test_other_roles_cannot_edit_the_agenda(self):
        riuh = self.client_for(self.make_user("riuh"))

        self.assertEqual(riuh.get("/api/rde-thrusts/").status_code, 200)
        self.assertEqual(riuh.post("/api/rde-thrusts/", {"code": "9", "title": "X"}, format="json").status_code, 403)
        self.assertEqual(riuh.patch(f"/api/rde-thrusts/{self.computing.pk}/", {"title": "X"}, format="json").status_code, 403)


class ProjectRdeAlignmentTests(RdeAgendaTestCase):
    def setUp(self):
        super().setUp()
        self.leader = self.make_user("project_leader")
        self.client = self.client_for(self.make_user("system_admin"))
        self.thrust = RdeThrust.objects.get(code="1").name
        self.priority = RdeThrust.objects.get(code="1.3").name

    def register(self, **overrides):
        return self.client.post("/api/projects/", project_payload(self.leader, **overrides), format="json")

    def test_project_stores_the_thrust_and_its_priority_area(self):
        response = self.register(rde_thrust=self.thrust, rde_priority=self.priority)

        self.assertEqual(response.status_code, 201, response.data)
        project = Project.objects.get()
        self.assertEqual(
            (project.rde_thrust, project.rde_priority),
            ("1 - Computing and Emerging Technologies", "1.3 - Artificial Intelligence and Machine Learning"),
        )

    def test_priority_area_must_belong_to_the_thrust(self):
        response = self.register(rde_thrust=RdeThrust.objects.get(code="2").name, rde_priority=self.priority)

        self.assertEqual(response.status_code, 400)
        self.assertIn("rde_priority", response.data)

    def test_thrust_and_priority_area_go_together(self):
        self.assertEqual(self.register(rde_thrust=self.thrust).status_code, 400)
        self.assertEqual(self.register(rde_priority=self.priority).status_code, 400)

    def test_unknown_thrust_is_rejected(self):
        self.assertEqual(self.register(rde_thrust="Space", rde_priority="1.1 - Space").status_code, 400)

    def test_old_values_stay_when_the_project_is_edited(self):
        project = Project.objects.create(
            title="Old", project_code="OLD-1", funding_type="core_funded", lead=self.leader,
            rde_thrust="REI-01 - Agriculture", sdgs=[4], sectors=["education"],
        )

        response = self.client.patch(f"/api/projects/{project.pk}/", {"title": "Renamed"}, format="json")

        self.assertEqual(response.status_code, 200, response.data)

    def test_program_stores_a_priority_area_too(self):
        program_leader = self.make_user("program_leader")

        response = self.client.post("/api/programs/", {
            "code": "P-1", "title": "Program", "funding_type": "core_funded", "lead": program_leader.pk,
            "rde_thrust": self.thrust, "rde_priority": self.priority,
        }, format="json")

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Program.objects.get().rde_priority, self.priority)
