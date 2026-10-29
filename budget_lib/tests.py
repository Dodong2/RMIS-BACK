"""LIB review workflow (client 2026-10-21, replaces the 2026-10-18 endorse/return chain): the Project Leader submits,
the CRC Chair reviews (Start Review -> For Checking -> Ready for Certification), the Budget Officer certifies (Start
Certification -> Certify). Either level can put it On Hold for the Project Leader, who edits and resubmits to the CRC
Chair. Every step is kept in the review history, each submission with a snapshot of its line items."""
from datetime import date
from decimal import Decimal

from accounts.testing import RMISTestCase
from research_projects.models import Project

from .models import LineItem, LineItemBudget


def attach_approval_documents(project, user):
    """The Supporting Documents attachments (Approve Proposal, NTP, and the optional MOA); submitting the project's LIB needs
    the first two (client 2026-10-24, Task 13)."""
    from document_management.models import Document

    for document_type in ("notice_of_approval", "ntp", "moa"):
        Document.objects.create(project=project, document_type=document_type, version_number=1, storage_path=f"x/{document_type}",
                                file_name=f"{document_type}.pdf", file_size=1, uploaded_by=user)


def add_registration_rows(project):
    """The form's minimums that submitting the project also needs: 2 studies, a 6P, a beneficiary (client 2026-10-29)."""
    from outputs.models import ExpectedOutput
    from research_projects.models import Study, TargetBeneficiary

    Study.objects.bulk_create([Study(project=project, title="Study 1"), Study(project=project, title="Study 2")])
    ExpectedOutput.objects.create(project=project, category="publications", description="Journal article", target_count=1)
    TargetBeneficiary.objects.create(project=project, group="Faculty", description="CTE faculty", total=10)


class LibWorkflowTests(RMISTestCase):
    def setUp(self):
        super().setUp()
        self.leader = self.make_user("project_leader")
        self.crc = self.make_user("crc_chair")
        self.officer = self.make_user("finance_budget")
        self.project = Project.objects.create(
            title="P", project_code="P-1", funding_type="core_funded", lead=self.leader, campus="San Pablo",
            total_cost="1000", start_date=date(2026, 1, 1), target_end_date=date(2026, 12, 31),
        )
        self.budget = LineItemBudget.objects.create(project=self.project, version_number=1)
        self.item = LineItem.objects.create(budget=self.budget, category="mooe", description="Travel", amount=Decimal("1000"))
        attach_approval_documents(self.project, self.leader)
        add_registration_rows(self.project)

    def act(self, user, action, **data):
        return self.client_for(user).post(f"/api/budget/budgets/{self.budget.id}/{action}/", data, format="json")

    def status(self):
        self.budget.refresh_from_db()
        return self.budget.status

    def move_to(self, status):
        LineItemBudget.objects.filter(pk=self.budget.pk).update(status=status)

    def test_full_chain_from_draft_to_certified(self):
        steps = [(self.leader, "submit", "submitted"), (self.crc, "start-review", "crc_processing"),
                 (self.crc, "for-checking", "for_checking"), (self.crc, "ready", "endorsed"),
                 (self.officer, "start-certification", "certifying"), (self.officer, "certify", "certified")]
        for user, action, expected in steps:
            response = self.act(user, action)
            self.assertEqual(response.status_code, 200, (action, response.data))
            self.assertEqual(self.status(), expected, action)
        self.assertEqual((self.budget.endorsed_by, self.budget.certified_by), (self.crc, self.officer))
        self.assertEqual([r["action"] for r in response.data["reviews"]],
                         ["submitted", "review_started", "for_checking", "ready", "certification_started", "certified"])

    def test_steps_cannot_be_skipped(self):
        self.assertEqual(self.act(self.crc, "start-review").status_code, 404)  # not submitted yet: a Draft is hidden from the CRC Chair (D2)
        self.act(self.leader, "submit")
        for action in ("for-checking", "ready"):
            self.assertEqual(self.act(self.crc, action).status_code, 400, action)
        for action in ("start-certification", "certify"):
            self.assertEqual(self.act(self.officer, action).status_code, 404, action)  # Q10: hidden from Budget until Ready
        self.act(self.crc, "start-review")
        self.assertEqual(self.act(self.crc, "ready").status_code, 400)  # always through For Checking (client Q5)
        self.assertEqual(self.status(), "crc_processing")
        self.move_to("endorsed")
        self.assertEqual(self.act(self.officer, "certify").status_code, 400)  # Start Certification first (Q6)
        self.assertEqual(self.status(), "endorsed")

    def test_each_step_belongs_to_its_role(self):
        for user in (self.crc, self.officer, self.make_user("project_leader")):
            self.assertIn(self.act(user, "submit").status_code, (403, 404), user.role.code)
        self.act(self.leader, "submit")
        for user in (self.officer, self.leader, self.make_user("vprei"), self.make_user("riuh")):
            self.assertIn(self.act(user, "start-review").status_code, (403, 404), user.role.code)  # Q10: hidden from Budget
        self.move_to("endorsed")
        for user in (self.crc, self.leader):
            self.assertEqual(self.act(user, "start-certification").status_code, 403, user.role.code)
        self.move_to("certifying")
        self.assertEqual(self.act(self.crc, "certify").status_code, 403)
        self.assertEqual(self.status(), "certifying")

    def test_crc_chair_outside_campus_gets_404(self):
        self.act(self.leader, "submit")
        other = self.make_user("crc_chair", campus="Los Baños")
        self.assertEqual(self.act(other, "start-review").status_code, 404)
        self.assertEqual(self.status(), "submitted")

    def test_submit_refuses_grand_total_not_equal_to_total_cost(self):
        LineItem.objects.filter(pk=self.item.pk).update(amount="900")
        response = self.act(self.leader, "submit")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Total Project/Study Cost", str(response.data))
        self.assertEqual(self.status(), "draft")

    def test_submit_refuses_empty_lib(self):
        self.item.delete()
        self.assertEqual(self.act(self.leader, "submit").status_code, 400)

    def test_the_leader_edits_a_draft_but_not_a_submitted_lib(self):
        url = f"/api/budget/line-items/{self.item.id}/"
        leader = self.client_for(self.leader)
        self.assertEqual(leader.patch(url, {"justification": "Field visits"}, format="json").status_code, 200)
        new_row = {"budget": self.budget.id, "category": "mooe", "description": "Training Expenses", "amount": "10"}
        for status in ("submitted", "crc_processing", "for_checking", "endorsed", "certifying", "certified"):
            self.move_to(status)
            self.assertEqual(leader.patch(url, {"justification": "X"}, format="json").status_code, 400, status)
            self.assertEqual(leader.post("/api/budget/line-items/", new_row, format="json").status_code, 400, status)
            self.assertEqual(leader.delete(url).status_code, 400, status)

    def test_only_the_project_leader_encodes(self):
        # Client Q9 (2026-10-21): the Procurement Officer and Program Leaders no longer encode LIBs (Program Leaders merged
        # into the Project Leader 2026-10-27; vprei stands in for another non-encoding role).
        row = {"budget": self.budget.id, "category": "mooe", "description": "Training Expenses", "amount": "10"}
        url = f"/api/budget/line-items/{self.item.id}/"
        for code in ("procurement_officer_lib", "vprei", "crc_chair", "finance_budget", "system_admin"):
            client = self.client_for(self.make_user(code))
            self.assertEqual(client.post("/api/budget/line-items/", row, format="json").status_code, 403, code)
            self.assertEqual(client.patch(url, {"justification": "X"}, format="json").status_code, 403, code)
            self.assertEqual(client.delete(url).status_code, 403, code)
            self.assertEqual(client.post("/api/budget/budgets/", {"project": self.project.id}, format="json").status_code, 403, code)
        self.assertEqual(self.client_for(self.leader).post("/api/budget/line-items/", row, format="json").status_code, 201)

    def test_the_budget_officer_sees_a_lib_only_once_it_is_ready(self):
        # Client Q10 (2026-10-21): nothing before Ready for Certification reaches the Budget Officer.
        officer = self.client_for(self.officer)
        for status, seen in (("draft", False), ("submitted", False), ("crc_processing", False), ("for_checking", False),
                             ("returned", False), ("endorsed", True), ("certifying", True), ("certified", True)):
            self.move_to(status)
            listed = [b["id"] for b in officer.get("/api/budget/budgets/", {"project": self.project.id}).data]
            self.assertEqual(self.budget.id in listed, seen, status)
            self.assertEqual(officer.get(f"/api/budget/budgets/{self.budget.id}/").status_code, 200 if seen else 404, status)
            items = [i["id"] for i in officer.get("/api/budget/line-items/", {"budget": self.budget.id}).data]
            self.assertEqual(self.item.id in items, seen, status)

    def test_other_roles_still_see_every_status(self):
        self.move_to("for_checking")
        for user in (self.leader, self.crc, self.make_user("system_admin")):
            self.assertEqual(self.client_for(user).get(f"/api/budget/budgets/{self.budget.id}/").status_code, 200, user.role.code)

    def test_hold_needs_remarks(self):
        self.act(self.leader, "submit")
        self.assertEqual(self.act(self.crc, "hold").status_code, 400)
        self.assertEqual(self.status(), "submitted")

    def test_crc_chair_holds_from_its_review_states(self):
        for status in ("submitted", "crc_processing", "for_checking"):
            self.move_to(status)
            response = self.act(self.crc, "hold", remarks="Fix travel")
            self.assertEqual(response.status_code, 200, status)
            self.assertEqual((self.status(), response.data["hold_level"]), ("returned", "crc"), status)
        self.assertEqual(response.data["reviews"][-1]["action"], "held_crc")

    def test_budget_officer_holds_from_ready_and_in_progress(self):
        for status in ("endorsed", "certifying"):
            self.move_to(status)
            response = self.act(self.officer, "hold", remarks="Wrong unit cost")
            self.assertEqual(response.status_code, 200, status)
            self.assertEqual((self.status(), response.data["hold_level"]), ("returned", "budget"), status)

    def test_hold_belongs_to_the_level_holding_the_lib(self):
        self.move_to("submitted")
        self.assertEqual(self.act(self.officer, "hold", remarks="x").status_code, 404)  # Q10: not visible to Budget yet
        self.move_to("endorsed")
        self.assertEqual(self.act(self.crc, "hold", remarks="x").status_code, 403)
        for status, code in (("draft", 404), ("certified", 400), ("returned", 400)):  # a Draft is hidden from the CRC Chair (D2)
            self.move_to(status)
            self.assertEqual(self.act(self.crc, "hold", remarks="x").status_code, code, status)

    def test_the_leader_edits_an_on_hold_lib_and_resubmits_to_the_crc_chair(self):
        self.act(self.leader, "submit")
        self.move_to("endorsed")
        self.act(self.officer, "hold", remarks="Fix travel")
        edit = self.client_for(self.leader).patch(f"/api/budget/line-items/{self.item.id}/", {"justification": "Two trips"}, format="json")
        self.assertEqual(edit.status_code, 200, edit.data)

        response = self.act(self.leader, "resubmit", remarks="Fixed")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.status(), "submitted")  # client Q7: back to Awaiting CRC Chair
        self.assertIsNone(response.data["hold_level"])
        self.assertEqual([(r["action"], r["remarks"]) for r in response.data["reviews"]],
                         [("submitted", ""), ("held_budget", "Fix travel"), ("resubmitted", "Fixed")])

    def test_only_the_project_leader_resubmits(self):
        self.move_to("returned")
        for user in (self.crc, self.officer, self.make_user("project_leader"), self.make_user("system_admin")):
            self.assertIn(self.act(user, "resubmit").status_code, (403, 404), user.role.code)
        self.assertEqual(self.status(), "returned")

    def test_resubmit_refuses_grand_total_not_equal_to_total_cost(self):
        self.move_to("returned")
        LineItem.objects.filter(pk=self.item.pk).update(amount="900")
        self.assertEqual(self.act(self.leader, "resubmit").status_code, 400)
        self.assertEqual(self.status(), "returned")

    def test_each_submission_keeps_a_snapshot_of_the_line_items(self):
        # Client Q11: what was submitted stays on record even after the leader edits an On Hold LIB.
        self.act(self.leader, "submit")
        self.act(self.crc, "hold", remarks="Fix")
        self.client_for(self.leader).patch(f"/api/budget/line-items/{self.item.id}/", {"justification": "Two trips"}, format="json")
        response = self.act(self.leader, "resubmit")

        submitted, held, resubmitted = response.data["reviews"]
        self.assertEqual(submitted["snapshot"][0]["justification"], "")
        self.assertEqual(resubmitted["snapshot"][0]["justification"], "Two trips")
        self.assertEqual((submitted["snapshot"][0]["amount"], held["snapshot"]), ("1000.00", []))

    def test_old_libs_keep_their_status_and_history_labels(self):
        self.move_to("returned")
        from .models import BudgetReview
        BudgetReview.objects.create(budget=self.budget, action="returned", remarks="Old return", acted_by=self.crc)

        data = self.client_for(self.leader).get(f"/api/budget/budgets/{self.budget.id}/").data

        self.assertEqual((data["status"], data["reviews"][0]["action"]), ("returned", "returned"))

    def test_a_line_item_cannot_move_out_of_a_locked_lib(self):
        # Audit 2026-10-21: PATCH {"budget": <a draft LIB>} only checked the new LIB, so an item could leave a
        # certified one.
        LineItemBudget.objects.filter(pk=self.budget.pk).update(status="certified")
        draft = LineItemBudget.objects.create(project=self.project, version_number=2)

        response = self.client_for(self.leader).patch(f"/api/budget/line-items/{self.item.id}/", {"budget": draft.id}, format="json")

        self.assertEqual(response.status_code, 400)
        self.item.refresh_from_db()
        self.assertEqual(self.item.budget_id, self.budget.id)

    def test_a_line_item_stays_in_its_own_lib_even_while_draft(self):
        other = LineItemBudget.objects.create(project=self.project, version_number=2)

        response = self.client_for(self.leader).patch(f"/api/budget/line-items/{self.item.id}/", {"budget": other.id}, format="json")

        self.assertIn("budget", response.data)
        self.item.refresh_from_db()
        self.assertEqual(self.item.budget_id, self.budget.id)


class LineItemSpecificationTests(RMISTestCase):
    """Task 12 (2026-10-29): an LIB row can name its specific item (SF-018 Section X, e.g. "PAPER, 80 gsm" under Office
    Supplies Expenses) beside the LIB Item it is picked from."""

    def setUp(self):
        super().setUp()
        self.leader = self.make_user("project_leader")
        self.project = Project.objects.create(
            title="P", project_code="P-1", funding_type="core_funded", lead=self.leader, campus="San Pablo",
            total_cost="1000", start_date=date(2026, 1, 1), target_end_date=date(2026, 12, 31),
        )
        self.budget = LineItemBudget.objects.create(project=self.project, version_number=1)
        self.item = LineItem.objects.create(budget=self.budget, category="mooe", description="Travel", amount=Decimal("1000"))
        attach_approval_documents(self.project, self.leader)
        add_registration_rows(self.project)

    act = LibWorkflowTests.act

    def test_a_row_keeps_its_specific_item_beside_the_lib_item(self):
        row = {"budget": self.budget.id, "category": "mooe", "description": "Office Supplies Expenses",
               "specification": "  PAPER, 80 gsm, A4  ", "amount": "10"}

        response = self.client_for(self.leader).post("/api/budget/line-items/", row, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual((response.data["description"], response.data["specification"]), ("Office Supplies Expenses", "PAPER, 80 gsm, A4"))

    def test_the_specific_item_is_optional_and_older_rows_have_none(self):
        row = {"budget": self.budget.id, "category": "mooe", "description": "Training Expenses", "amount": "10"}

        response = self.client_for(self.leader).post("/api/budget/line-items/", row, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["specification"], "")
        self.assertEqual(LineItem.objects.get(pk=self.item.pk).specification, "")

    def test_the_lib_item_still_comes_from_lib_items(self):
        row = {"budget": self.budget.id, "category": "mooe", "description": "PAPER, 80 gsm", "specification": "PAPER, 80 gsm", "amount": "10"}

        response = self.client_for(self.leader).post("/api/budget/line-items/", row, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("description", response.data)

    def test_a_submission_snapshot_keeps_the_specific_item(self):
        LineItem.objects.filter(pk=self.item.pk).update(specification="Bus fare, Manila")

        submitted = self.act(self.leader, "submit").data["reviews"][0]

        self.assertEqual(submitted["snapshot"][0]["specification"], "Bus fare, Manila")
