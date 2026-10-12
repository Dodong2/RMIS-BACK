"""Module 2 registration under real concurrent requests (threads, separate DB connections). See ConcurrencyTestCase."""
from accounts.testing import ConcurrencyTestCase
from research_projects.models import Project
from research_projects.tests import project_payload


class LeaderCapConcurrencyTests(ConcurrencyTestCase):
    def test_two_simultaneous_registrations_cannot_exceed_the_institutional_leader_cap(self):
        """Manual: a leader may lead only one active institutional project at a time."""
        leader = self.make_user("project_leader")
        registrar_a, registrar_b = self.make_user("system_admin"), self.make_user("crc_chair")
        self.widen("research_projects.serializers.validate_lead_concurrency")

        def register(registrar, code):
            client = self.client_for(registrar)
            return lambda: client.post("/api/projects/", project_payload(
                leader, project_code=code, funding_type="institutional", status="active"), format="json")

        first, second = self.run_concurrently(register(registrar_a, "INST-1"), register(registrar_b, "INST-2"))
        self.assertEqual(sorted([first.status_code, second.status_code]), [201, 400])
        self.assertEqual(Project.objects.filter(lead=leader, funding_type="institutional").count(), 1)
