"""Real-time (2026-10-13 follow-up): procurement status changes reach the leader's open Procurement page and bell, not
only the Procurement Officer's own screen. One signal per successful write; the browser refetches through DRF."""
from accounts.testing import RMISTestCase
from budget_lib.models import LineItem, LineItemBudget
from financial_monitoring.models import ProcurementRequest
from financial_monitoring.tests import with_year_one
from realtime.consumers import campus_role_group
from realtime.notify import to_role, to_user
from research_projects.models import Project

PR_URL = "/api/financial/procurement-requests/"


class ProcurementSignalTests(RMISTestCase):
    def setUp(self):
        super().setUp()
        self.notify = self._patch("financial_monitoring.views.notify")
        self.leader = self.make_user("project_leader")
        self.project = Project.objects.create(title="P", project_code="P-1", funding_type="core_funded", lead=self.leader)
        budget = LineItemBudget.objects.create(project=self.project, version_number=1, status="certified")
        self.item = with_year_one(LineItem.objects.create(budget=budget, category="mooe", description="Supplies", amount=10000))
        self.officer = self.client_for(self.make_user("procurement_officer_lib"))

    def assert_signal(self, event_type, procurement_id, status):
        self.assertEqual(self.notify.call_count, 1)
        (groups, sent_type), data = self.notify.call_args
        self.notify.reset_mock()
        self.assertEqual(sent_type, event_type)
        self.assertEqual(data, {"id": procurement_id, "project": self.project.id, "status": status})
        # Task 21: campus roles through their campus group (this project has no campus: the campus-less accounts)
        self.assertLessEqual({to_user(self.leader.pk), campus_role_group("procurement_officer_lib", ""), to_role("system_admin")}, set(groups))
        self.assertNotIn(to_role("procurement_officer_lib"), groups)
        self.assertNotIn(to_role("project_leader"), groups)  # other leaders' projects aren't theirs

    def test_request_receive_return_resubmit_and_complete(self):
        leader = self.client_for(self.leader)
        response = leader.post(PR_URL, {"line_item": self.item.id, "description": "Reagents", "amount": "1000",
                                        "project_year": 1, "quarter": 4})
        self.assertEqual(response.status_code, 201, response.data)
        pk = response.data["id"]
        self.assert_signal("procurement.created", pk, "requested")

        self.assertEqual(self.officer.post(f"{PR_URL}{pk}/receive/").status_code, 200)
        self.assert_signal("procurement.updated", pk, "under_review")

        response = self.officer.post(f"{PR_URL}{pk}/status/", {"status": "returned_for_revision", "remarks": "Add quote"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_signal("procurement.updated", pk, "returned_for_revision")

        response = leader.post(f"{PR_URL}{pk}/resubmit/", {"description": "Reagents + quote"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_signal("procurement.updated", pk, "requested")

        self.officer.post(f"{PR_URL}{pk}/receive/")
        self.notify.reset_mock()
        response = self.officer.post(f"{PR_URL}{pk}/status/", {"status": "completed"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_signal("procurement.updated", pk, "completed")

    def test_rejected_writes_send_nothing(self):
        pr = ProcurementRequest.objects.create(line_item=self.item, description="x", amount=100, project_year=1, quarter=4,
                                               requested_by=self.leader, status="completed")
        responses = [
            self.officer.post(f"{PR_URL}{pr.id}/receive/"),  # 400: not "requested"
            self.officer.post(f"{PR_URL}{pr.id}/status/", {"status": "under_review"}),  # 400: closed
            self.client_for(self.leader).post(f"{PR_URL}{pr.id}/receive/"),  # 403
            self.client_for(self.leader).post(PR_URL, {"line_item": self.item.id, "description": "x", "amount": "999999",
                                                       "project_year": 1, "quarter": 4}),  # 400: over balance
        ]
        self.assertEqual([r.status_code for r in responses], [400, 400, 403, 400])
        self.notify.assert_not_called()


REALIGN_URL = "/api/financial/realignments/"


class RealignmentSignalTests(RMISTestCase):
    """2026-10-22: a filed realignment reaches the Budget Officer's bell, a review reaches the leader's Realignment tab."""

    def setUp(self):
        super().setUp()
        self.notify = self._patch("financial_monitoring.views.notify")
        self.leader = self.make_user("project_leader")
        self.project = Project.objects.create(title="P", project_code="P-1", funding_type="core_funded", lead=self.leader)
        budget = LineItemBudget.objects.create(project=self.project, version_number=1, status="certified")
        self.travel = LineItem.objects.create(budget=budget, category="mooe", description="Travel", amount=10000)
        self.seminar = LineItem.objects.create(budget=budget, category="mooe", description="Seminar", amount=10000)
        self.supplies = LineItem.objects.create(budget=budget, category="mooe", description="Supplies", amount=10000)
        self.leader_client = self.client_for(self.leader)

    def row(self, source, amount=1000):
        return {"from_line_item": source.id, "to_line_item": self.seminar.id, "amount": str(amount), "justification": "x"}

    def assert_signal(self, event_type, realignment_id):
        self.assertEqual(self.notify.call_count, 1)
        (groups, sent_type), data = self.notify.call_args
        self.notify.reset_mock()
        self.assertEqual(sent_type, event_type)
        self.assertEqual(data, {"id": realignment_id, "project": self.project.id})
        self.assertLessEqual({to_user(self.leader.pk), campus_role_group("finance_budget", self.project.campus), to_role("system_admin")}, set(groups))
        self.assertNotIn(to_role("finance_budget"), groups)
        self.assertNotIn(to_role("project_leader"), groups)

    def test_bulk_request_signals_once_and_review_signals(self):
        response = self.leader_client.post(REALIGN_URL, [self.row(self.travel), self.row(self.supplies)], format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assert_signal("financial.realignment.created", response.data[0]["id"])

        reviewer = self.client_for(self.make_user("finance_budget"))
        pk = response.data[1]["id"]
        self.assertEqual(reviewer.post(f"{REALIGN_URL}{pk}/review/", {"decision": "rejected"}).status_code, 200)
        self.assert_signal("financial.realignment.reviewed", pk)

    def test_single_request_signals(self):
        response = self.leader_client.post(REALIGN_URL, self.row(self.travel), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assert_signal("financial.realignment.created", response.data["id"])

    def test_refused_writes_send_nothing(self):
        self.assertEqual(self.leader_client.post(REALIGN_URL, [self.row(self.travel, 999999)], format="json").status_code, 400)
        pk = self.leader_client.post(REALIGN_URL, self.row(self.travel), format="json").data["id"]
        self.notify.reset_mock()
        self.assertEqual(self.leader_client.post(f"{REALIGN_URL}{pk}/review/", {"decision": "approved"}).status_code, 403)
        self.notify.assert_not_called()
