"""Client Task 90-A (2026-11-27): Project Leader proposes a Work Plan milestone change after registration, RIUH confirms
(applied) or returns it, the campus CRC/CRD is e-mailed on confirm. The milestone is locked while a change is pending."""
import datetime
from unittest import mock

from accounts.testing import RMISTestCase
from budget_lib.models import LineItemBudget

from .models import MilestoneChangeRequest, Project, WorkPlanMilestone

URL = "/api/milestone-changes/"


class MilestoneChangeTests(RMISTestCase):
    def setUp(self):
        super().setUp()
        self.notify = self._patch("research_projects.milestone_changes.notify")
        self.email = self._patch("research_projects.milestone_changes.send_brevo_email")
        self.leader = self.make_user("project_leader", first_name="Ana", last_name="Cruz", campus="Siniloan")
        self.other_leader = self.make_user("project_leader", campus="Siniloan")
        self.riuh = self.make_user("riuh", campus="Siniloan", college_unit="CAS", first_name="Rita", last_name="Uy")
        self.riuh_ccs = self.make_user("riuh", campus="Siniloan", college_unit="CCS")
        self.crc = self.make_user("crc_chair", campus="Siniloan")
        self.lb_crc = self.make_user("crc_chair", campus="Los Baños")
        self.admin = self.make_user("system_admin")
        self.project = Project.objects.create(title="Study A", project_code="S-1", funding_type="core_funded",
                                              lead=self.leader, campus="Siniloan", college="CAS")
        self.budget = LineItemBudget.objects.create(project=self.project, version_number=1, status="certified")
        self.milestone = WorkPlanMilestone.objects.create(project=self.project, title="Survey", objective="Obj 1",
                                                          start_date=datetime.date(2027, 1, 1), target_date=datetime.date(2027, 3, 31))

    def propose(self, user=None, **changes):
        changes = changes or {"target_date": "2027-05-31", "title": "Survey (extended)"}
        return self.client_for(user or self.leader).post(URL, {"milestone": self.milestone.id, "reason": "Rain delay",
                                                               "changes": changes}, format="json")

    def act(self, user, change_id, action, **body):
        return self.client_for(user).post(f"{URL}{change_id}/{action}/", body, format="json")

    def test_leader_proposes_and_only_changed_fields_are_kept(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.propose(objective="Obj 1", target_date="2027-05-31")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual((response.data["previous"], response.data["proposed"], response.data["status"]),
                         ({"target_date": "2027-03-31"}, {"target_date": "2027-05-31"}, "pending"))
        self.assertEqual((response.data["submitted_by_name"], response.data["project_leader"]), ("Ana Cruz", "Ana Cruz"))
        self.milestone.refresh_from_db()
        self.assertEqual(self.milestone.target_date, datetime.date(2027, 3, 31))  # not applied yet
        self.assertEqual(self.notify.call_args.args[1], "milestone_change.submitted")
        self.assertEqual([c.args[0] for c in self.email.call_args_list], [self.riuh.email])  # CAS RIUH only

    def test_who_may_propose(self):
        self.assertEqual(self.propose(self.other_leader).status_code, 400)  # not their project
        for role in ("riuh", "crc_chair", "finance_budget", "project_staff", "vprei"):
            self.assertEqual(self.propose(self.make_user(role, campus="Siniloan")).status_code, 403, role)
        self.assertEqual(self.propose(self.admin).status_code, 201)

    def test_rules(self):
        self.assertEqual(self.propose(title="Survey").status_code, 400)  # nothing changed
        self.assertEqual(self.propose(start_date="2027-06-01").status_code, 400)  # after target date
        empty = self.client_for(self.leader).post(URL, {"milestone": self.milestone.id, "reason": " ", "changes": {"title": "X"}}, format="json")
        self.assertEqual(empty.status_code, 400)
        LineItemBudget.objects.filter(pk=self.budget.pk).update(status="draft")
        self.assertIn("edit the Work Plan directly", str(self.propose().data))

    def test_pending_change_locks_the_milestone(self):
        self.assertEqual(self.propose().status_code, 201)
        self.assertEqual(self.propose(title="Other").status_code, 400)
        LineItemBudget.objects.filter(pk=self.budget.pk).update(status="draft")  # even with registration reopened
        client = self.client_for(self.leader)
        self.assertEqual(client.patch(f"/api/milestones/{self.milestone.id}/", {"title": "Y"}, format="json").status_code, 400)
        self.assertEqual(client.delete(f"/api/milestones/{self.milestone.id}/").status_code, 400)

    def test_riuh_confirms_applies_and_emails_the_campus_crc(self):
        change = self.propose().data["id"]
        self.email.reset_mock()
        with self.captureOnCommitCallbacks(execute=True):
            response = self.act(self.riuh, change, "confirm")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual((response.data["status"], response.data["reviewed_by_name"]), ("confirmed", "Rita Uy"))
        self.milestone.refresh_from_db()
        self.assertEqual((self.milestone.title, self.milestone.target_date), ("Survey (extended)", datetime.date(2027, 5, 31)))
        self.assertEqual([c.args[0] for c in self.email.call_args_list], [self.crc.email])
        self.assertEqual(self.notify.call_args.args[1], "milestone_change.confirmed")
        self.assertEqual(self.act(self.riuh, change, "confirm").status_code, 409)
        self.assertEqual(self.propose(title="Again").status_code, 201)  # unlocked after the decision

    def test_return_needs_remarks_and_keeps_the_milestone(self):
        change = self.propose().data["id"]
        self.assertEqual(self.act(self.riuh, change, "return").status_code, 400)
        response = self.act(self.riuh, change, "return", remarks="Keep March")
        self.assertEqual((response.data["status"], response.data["review_remarks"]), ("returned", "Keep March"))
        self.milestone.refresh_from_db()
        self.assertEqual(self.milestone.target_date, datetime.date(2027, 3, 31))

    def test_who_may_review(self):
        change = self.propose().data["id"]
        for user in (self.crc, self.leader):
            self.assertEqual(self.act(user, change, "confirm").status_code, 403)
        self.assertEqual(self.act(self.riuh_ccs, change, "confirm").status_code, 404)  # other College Unit
        self.assertEqual(self.act(self.riuh, change, "approve").status_code, 404)
        self.assertEqual(MilestoneChangeRequest.objects.get(pk=change).status, "pending")
        self.assertEqual(self.act(self.admin, change, "confirm").status_code, 200)

    def test_list_scope_search_and_paging(self):
        self.propose()
        codes = lambda user, **p: [r["project_code"] for r in self.client_for(user).get(URL, p).data["results"]]
        for user in (self.leader, self.riuh, self.crc, self.admin):
            self.assertEqual(codes(user), ["S-1"])
        for user in (self.other_leader, self.riuh_ccs, self.lb_crc):
            self.assertEqual(codes(user), [])
        self.assertEqual(self.client_for(self.make_user("finance_budget", campus="Siniloan")).get(URL).status_code, 403)
        self.assertEqual(codes(self.admin, q="survey"), ["S-1"])
        self.assertEqual(codes(self.admin, status="confirmed"), [])
        self.assertEqual(self.client_for(self.admin).get(URL, {"page_size": 1}).data["count"], 1)

    def test_realtime_audience_is_the_campus_reviewers_and_the_leader(self):
        from realtime.consumers import campus_role_group
        from realtime.notify import to_role, to_user

        with mock.patch("research_projects.milestone_changes.notify") as notify:
            self.propose()
        groups = notify.call_args.args[0]
        for group in (to_role("system_admin"), campus_role_group("riuh", "Siniloan"), campus_role_group("crc_chair", "Siniloan"), to_user(self.leader.id)):
            self.assertIn(group, groups)
        self.assertNotIn(campus_role_group("finance_budget", "Siniloan"), groups)
        self.assertEqual(MilestoneChangeRequest.objects.count(), 1)
