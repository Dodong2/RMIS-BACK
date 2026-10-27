"""R&D Quarterly Progress Reports (client 2026-10-14, new_feat.png / R&D.png; prototype QuarterlyReports.tsx).
Roles from Structure Module 9 + Clarification 1a/1b/1c: the Project Leader prepares; RIUH / CRC Chair review and
endorse; DRD / VPREI give final approval."""
import datetime
from unittest import mock

from accounts.testing import RMISTestCase
from budget_lib.models import LineItem, LineItemBudget
from financial_monitoring.models import Disbursement
from monitoring.models import QuarterlyProgressReport
from research_projects.models import Project, WorkPlanMilestone

URL = "/api/monitoring/quarterly-reports/"


class QuarterlyReportTests(RMISTestCase):
    def setUp(self):
        super().setUp()
        self.leader = self.make_user("project_leader", first_name="Jose", last_name="Reyes")
        self.project = Project.objects.create(
            title="Biochar", project_code="LSPU-RD-2024-001", funding_type="externally_funded", lead=self.leader,
            campus="San Pablo City", college="CA - College of Agriculture", start_date=datetime.date(2024, 1, 15),
            target_end_date=datetime.date(2026, 12, 31), objectives="Characterize biochar\nDevelop a technology package",
        )
        budget = LineItemBudget.objects.create(project=self.project, version_number=1, status="certified")
        item = LineItem.objects.create(budget=budget, category="mooe", description="Supplies", amount=1000,
                                       funding_source="DOST-PCAARRD")
        for day, amount in ((datetime.date(2026, 3, 31), 100), (datetime.date(2026, 4, 1), 200),
                            (datetime.date(2026, 6, 30), 50), (datetime.date(2026, 7, 1), 999)):
            Disbursement.objects.create(line_item=item, amount=amount, disbursed_on=day, recorded_by=self.leader)
        WorkPlanMilestone.objects.create(
            project=self.project, title="Season 2 trials", start_date=datetime.date(2026, 4, 1),
            target_date=datetime.date(2026, 6, 30), status="done", objective="Characterize biochar",
            deliverable="Two site-season trials",
        )
        WorkPlanMilestone.objects.create(project=self.project, title="Next year", target_date=datetime.date(2027, 3, 1))
        self.leader_client = self.client_for(self.leader)

    def _create(self, client=None, year=2026, quarter=2):
        return (client or self.leader_client).post(URL, {"project": self.project.id, "year": year, "quarter": quarter},
                                                   format="json")

    def _move(self, report_id, user, to_status, remarks=""):
        return self.client_for(user).post(f"{URL}{report_id}/transition/", {"status": to_status, "remarks": remarks},
                                          format="json")

    def _in_review(self):
        report_id = self._create().data["id"]
        self._move(report_id, self.leader, "submitted")
        self._move(report_id, self.make_user("riuh"), "under_review")
        return report_id

    # --- create + prefill ---------------------------------------------------------------------------------------

    def test_leader_creates_a_draft_prefilled_from_the_work_plan_and_ledger(self):
        response = self._create()

        self.assertEqual(response.status_code, 201, response.data)
        data = response.data
        self.assertEqual((data["status"], data["version"], data["period"]), ("draft", 1, "Q2 2026"))
        self.assertEqual(len(data["accomplishments"]), 1)
        row = data["accomplishments"][0]
        self.assertEqual((row["activity"], row["objective"], row["target"]),
                         ("Season 2 trials", "Characterize biochar", "Two site-season trials"))
        self.assertEqual((row["target_date"], row["completion_pct"]), ("2026-06-30", 100))
        fin = data["financial_snapshot"]
        self.assertEqual((fin["original_budget"], fin["quarter_disbursements"], fin["cumulative_disbursements"]),
                         (1000.0, 250.0, 350.0))
        self.assertEqual((fin["utilization_pct"], fin["transaction_count"], fin["remaining_budget"]), (35, 2, 650.0))
        self.assertEqual(data["project_info"]["funding_agency"], "DOST-PCAARRD")
        self.assertEqual(data["project_info"]["objectives"], ["Characterize biochar", "Develop a technology package"])
        self.assertEqual(data["events"][0]["action"], "created")

    def test_only_the_projects_own_leader_can_create(self):
        self.assertEqual(self._create(self.client_for(self.make_user("project_leader"))).status_code, 400)
        self.assertEqual(self._create(self.client_for(self.make_user("riuh"))).status_code, 403)
        self.assertEqual(self._create(self.client_for(self.make_user("system_admin"))).status_code, 403)

    def test_one_report_per_project_quarter(self):
        self.assertEqual(self._create().status_code, 201)
        response = self._create()
        self.assertEqual(response.status_code, 400)

    def test_rejects_a_future_quarter_and_bad_quarter_numbers(self):
        self.assertEqual(self._create(year=datetime.date.today().year + 1, quarter=4).status_code, 400)
        self.assertEqual(self._create(quarter=5).status_code, 400)

    # --- editing ----------------------------------------------------------------------------------------------

    def test_owner_edits_a_draft_but_not_once_submitted(self):
        report_id = self._create().data["id"]
        patch = {"recommendations": "Proceed", "issues": [{"issue": "CEC rerun", "corrective_action": "Rerun",
                                                           "recommendation": "", "responsible": "QA",
                                                           "target_resolution_date": "2026-07-15"}]}

        response = self.leader_client.patch(f"{URL}{report_id}/", patch, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["issues"][0]["issue"], "CEC rerun")

        self._move(report_id, self.leader, "submitted")
        self.assertEqual(self.leader_client.patch(f"{URL}{report_id}/", {"recommendations": "x"}, format="json").status_code, 400)

    def test_reviewer_cannot_edit_the_content(self):
        report_id = self._create().data["id"]
        response = self.client_for(self.make_user("riuh")).patch(f"{URL}{report_id}/", {"recommendations": "x"},
                                                                  format="json")
        self.assertEqual(response.status_code, 403)

    def test_accomplishment_rows_are_validated(self):
        report_id = self._create().data["id"]
        response = self.leader_client.patch(f"{URL}{report_id}/", {"accomplishments": [{"activity": "A",
                                                                                        "completion_pct": 150}]},
                                            format="json")
        self.assertEqual(response.status_code, 400)

    # --- workflow ---------------------------------------------------------------------------------------------

    def test_full_chain_with_a_revision_bumps_the_version(self):
        riuh, vprei = self.make_user("riuh"), self.make_user("vprei")
        report_id = self._create().data["id"]

        self.assertEqual(self._move(report_id, self.leader, "submitted").status_code, 200)
        self.assertEqual(self._move(report_id, riuh, "under_review").status_code, 200)
        self.assertEqual(self._move(report_id, riuh, "returned_for_revision", "Attach the certified statement").status_code, 200)
        self.assertEqual(self._move(report_id, self.leader, "submitted").status_code, 200)
        self.assertEqual(self._move(report_id, riuh, "under_review").status_code, 200)
        self.assertEqual(self._move(report_id, riuh, "endorsed", "Complete").status_code, 200)
        response = self._move(report_id, vprei, "approved", "Approved.")

        self.assertEqual(response.status_code, 200, response.data)
        report = QuarterlyProgressReport.objects.get(pk=report_id)
        self.assertEqual((report.status, report.version, report.approved_by), ("approved", 2, vprei))
        self.assertEqual([c["remarks"] for c in response.data["review_history"]],
                         ["Attach the certified statement", "Complete", "Approved."])

    def test_cannot_submit_without_accomplishments(self):
        report_id = self._create().data["id"]
        self.leader_client.patch(f"{URL}{report_id}/", {"accomplishments": []}, format="json")
        self.assertEqual(self._move(report_id, self.leader, "submitted").status_code, 400)

    def test_return_needs_remarks(self):
        report_id = self._in_review()
        self.assertEqual(self._move(report_id, self.make_user("riuh"), "returned_for_revision").status_code, 400)

    def test_reviewer_endorses_but_cannot_approve(self):
        report_id = self._in_review()
        self.assertEqual(self._move(report_id, self.make_user("crc_chair"), "approved").status_code, 403)
        self.assertEqual(self._move(report_id, self.make_user("crc_chair"), "endorsed").status_code, 200)

    def test_final_approver_can_approve_straight_from_review(self):
        report_id = self._in_review()
        self.assertEqual(self._move(report_id, self.make_user("vprei"), "approved").status_code, 200)

    def test_leader_and_system_admin_cannot_review(self):
        report_id = self._create().data["id"]
        self._move(report_id, self.leader, "submitted")
        self.assertEqual(self._move(report_id, self.leader, "under_review").status_code, 403)
        self.assertEqual(self._move(report_id, self.make_user("system_admin"), "under_review").status_code, 403)

    def test_invalid_jump_is_rejected(self):
        report_id = self._create().data["id"]
        self.assertEqual(self._move(report_id, self.make_user("vprei"), "approved").status_code, 400)

    def test_reviewer_outside_scope_cannot_review(self):
        report_id = self._create().data["id"]
        self._move(report_id, self.leader, "submitted")
        other_college = self.make_user("riuh", scope={"college": "CAS - College of Arts and Sciences"})
        self.assertEqual(self._move(report_id, other_college, "under_review").status_code, 404)

    def test_financial_snapshot_freezes_on_submit(self):
        report_id = self._create().data["id"]
        self._move(report_id, self.leader, "submitted")
        Disbursement.objects.create(line_item=LineItem.objects.get(), amount=1, disbursed_on=datetime.date(2026, 5, 1),
                                    recorded_by=self.leader)
        data = self.leader_client.get(f"{URL}{report_id}/").data
        self.assertEqual(data["financial_snapshot"]["quarter_disbursements"], 250.0)

    # --- list, scope, overdue ---------------------------------------------------------------------------------

    def test_list_is_scoped(self):
        self._create()
        self.assertEqual(len(self.client_for(self.make_user("vprei")).get(URL).data), 1)
        self.assertEqual(len(self.client_for(self.make_user("project_leader")).get(URL).data), 0)
        other = self.make_user("riuh", scope={"college": "CAS - College of Arts and Sciences"})
        self.assertEqual(len(self.client_for(other).get(URL).data), 0)

    def test_overdue_is_quarter_end_plus_15_days_until_approved(self):
        report_id = self._create().data["id"]
        with mock.patch("monitoring.quarterly.today", return_value=datetime.date(2026, 7, 15)):
            self.assertFalse(self.leader_client.get(URL).data[0]["is_overdue"])
        with mock.patch("monitoring.quarterly.today", return_value=datetime.date(2026, 7, 16)):
            self.assertTrue(self.leader_client.get(URL).data[0]["is_overdue"])
        QuarterlyProgressReport.objects.filter(pk=report_id).update(status="approved")
        with mock.patch("monitoring.quarterly.today", return_value=datetime.date(2026, 7, 16)):
            self.assertFalse(self.leader_client.get(URL).data[0]["is_overdue"])

    # --- export -----------------------------------------------------------------------------------------------

    def test_export_renders_only_approved_reports(self):
        vprei = self.make_user("vprei")
        client = self.client_for(vprei)
        self.assertEqual(client.get(f"{URL}export/", {"file_format": "pdf"}).status_code, 404)

        report_id = self._in_review()
        self._move(report_id, vprei, "approved", "Approved.")
        pdf = client.get(f"{URL}export/", {"file_format": "pdf", "ids": str(report_id)})
        docx = client.get(f"{URL}export/", {"file_format": "docx"})

        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        self.assertEqual(docx.status_code, 200)
        self.assertTrue(docx.content.startswith(b"PK"))
        self.assertEqual(client.get(f"{URL}export/", {"file_format": "csv"}).status_code, 400)
