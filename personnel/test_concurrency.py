"""Run in autocommit like production (TransactionTestCase): a row lock outside a transaction would be a 500 here,
which RMISTestCase can't show because it wraps every test in one transaction."""
from accounts.testing import ConcurrencyTestCase
from research_projects.models import Project


class LeaderAssignmentInAutocommitTests(ConcurrencyTestCase):
    def test_assigning_a_leader_runs_the_locked_load_check_inside_a_transaction(self):
        old, new = self.make_user("project_leader"), self.make_user("project_leader")
        project = Project.objects.create(title="P", project_code="P-1", funding_type="core_funded", lead=old)
        response = self.client_for(self.make_user("system_admin")).post(
            "/api/personnel/leaders/assign/", {"record_type": "project", "record_id": project.id, "lead": new.id}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        project.refresh_from_db()
        self.assertEqual(project.lead, new)
