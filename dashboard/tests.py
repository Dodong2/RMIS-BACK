from accounts.testing import RMISTestCase
from research_projects.models import Project


class PortfolioDashboardTests(RMISTestCase):
    def test_program_leader_sees_counts_for_every_project(self):
        other = self.make_user("project_leader")
        program_leader = self.make_user("program_leader")
        Project.objects.create(
            title="A", project_code="A-1", funding_type="core_funded", lead=other, research_priority_area="ict",
            sdgs=[4, 9], campus="San Pablo City", college="CCS - College of Computer Studies",
        )
        Project.objects.create(
            title="B", project_code="B-1", funding_type="core_funded", lead=other, status="completed",
            sdgs=[9], campus="San Pablo City", college="CCS - College of Computer Studies",
        )

        response = self.client_for(program_leader).get("/api/dashboard/portfolio/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total_projects"], 2)
        self.assertEqual(response.data["by_priority_area"], {"Information and Communication Tech.": 1, "Unspecified": 1})
        self.assertEqual(response.data["by_sdg"], {4: 1, 9: 2})
        self.assertEqual(response.data["by_college"], [{
            "college": "CCS - College of Computer Studies", "code": "CCS", "title": "College of Computer Studies",
            "campus": "San Pablo City", "total": 2, "by_status": {"active": 1, "completed": 1},
        }])

    def test_campus_filter(self):
        leader = self.make_user("project_leader")
        Project.objects.create(title="A", project_code="A-1", funding_type="core_funded", lead=leader, campus="Siniloan")

        response = self.client_for(self.make_user("system_admin")).get("/api/dashboard/portfolio/", {"campus": "Sta. Cruz"})

        self.assertEqual(response.data["total_projects"], 0)
