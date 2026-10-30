"""Task 24 (2026-10-30): Finance payment reminders from send_scheduled_reminders (7th/14th/21st, 08:00 Manila)."""
import datetime
from io import StringIO
from zoneinfo import ZoneInfo

import requests
from django.core.management import call_command
from django.utils import timezone

from accounts.models import ReminderLog
from accounts.testing import RMISTestCase
from budget_lib.models import LineItem, LineItemBudget
from financial_monitoring.management.commands.send_scheduled_reminders import payment_run
from financial_monitoring.models import Disbursement, ProcurementRequest
from research_projects.models import Project

MANILA = ZoneInfo("Asia/Manila")


def manila(*args):
    return datetime.datetime(*args, tzinfo=MANILA)


class PaymentRunTests(RMISTestCase):
    def test_exactly_three_runs_a_month_on_the_7th_14th_and_21st(self):
        start, hours = manila(2026, 11, 1), 30 * 24
        keys = {payment_run(start + datetime.timedelta(hours=h)) for h in range(hours)}
        self.assertEqual(keys, {datetime.date(2026, 10, 21), datetime.date(2026, 11, 7), datetime.date(2026, 11, 14),
                                datetime.date(2026, 11, 21)})  # 10-21 = the run still current on Nov 1-6
        self.assertEqual(len([k for k in keys if k.month == 11]), 3)

    def test_runs_start_at_8am_manila_not_utc(self):
        self.assertEqual(payment_run(manila(2026, 11, 7, 7, 59)), datetime.date(2026, 10, 21))
        self.assertEqual(payment_run(manila(2026, 11, 7, 8, 0)), datetime.date(2026, 11, 7))
        # 00:30 UTC on Nov 7 is 08:30 in Manila: already due.
        self.assertEqual(payment_run(datetime.datetime(2026, 11, 7, 0, 30, tzinfo=datetime.UTC)), datetime.date(2026, 11, 7))
        self.assertEqual(payment_run(manila(2027, 1, 3, 12)), datetime.date(2026, 12, 21))


class PaymentReminderTests(RMISTestCase):
    def setUp(self):
        super().setUp()
        self.leader = self.make_user("project_leader", campus="Siniloan")
        self.project = Project.objects.create(title="Smart <Farm>", project_code="NTP-2026-007", funding_type="core_funded",
                                              lead=self.leader, campus="Siniloan")
        budget = LineItemBudget.objects.create(project=self.project, version_number=1, status="certified")
        self.item = LineItem.objects.create(budget=budget, category="mooe", description="Internet Subscription Expenses", amount=100000)
        self.finance = [self.make_user("finance_budget", campus="Siniloan"), self.make_user("finance_budget", campus="siniloan")]
        self.make_user("finance_budget", campus="Sta. Cruz")
        self.make_user("finance_budget", campus="Siniloan", is_active=False)
        self.awaiting = [self.request(30000, "completed"), self.request(12500.50, "completed", quarter=2)]
        paid = self.request(5000, "completed")
        Disbursement.objects.create(line_item=self.item, amount=5000, disbursed_on=datetime.date(2026, 11, 1),
                                    recorded_by=self.finance[0], procurement_request=paid)
        self.request(7000, "cancelled")
        self.request(8000, "ready_for_release")
        self._patch("django.utils.timezone.now", return_value=manila(2026, 11, 7, 8, 5))

    def request(self, amount, status, quarter=None):
        return ProcurementRequest.objects.create(line_item=self.item, description=f"Item {amount}", amount=amount, project_year=1,
                                                 quarter=quarter, status=status, requested_by=self.leader,
                                                 completed_at=timezone.now() if status == "completed" else None)

    def run_command(self, *args):
        out = StringIO()
        call_command("send_scheduled_reminders", *args, stdout=out)
        return out.getvalue()

    def sent(self):
        return [call.kwargs["json"] for call in self.brevo_post.call_args_list]

    def test_one_e_mail_per_campus_finance_with_only_the_outstanding_requests(self):
        output = self.run_command()
        mails = self.sent()
        self.assertEqual(sorted(m["to"][0]["email"] for m in mails), sorted(u.email for u in self.finance))
        html = mails[0]["htmlContent"]
        self.assertEqual(mails[0]["subject"], "Payment Reminder — Smart <Farm>")
        for text in ("NTP-2026-007", "Smart &lt;Farm&gt;", f"PR-{self.awaiting[0].pk:04d}", "Year 1 · Q2", "₱42,500.50",
                     "Outstanding Amount"):
            self.assertIn(text, html)
        for excluded in ("Item 5000", "Item 7000", "Item 8000"):  # paid, cancelled, not completed
            self.assertNotIn(excluded, html)
        self.assertIn("Payment run 2026-11-07: 2 sent, 0 failed, 0 already done.", output)
        self.assertEqual(ReminderLog.objects.filter(kind="payment", run_key="2026-11-07", status="sent").count(), 2)

    def test_a_repeated_run_sends_nothing_new(self):
        self.run_command()
        self.brevo_post.reset_mock()
        self.assertIn("0 sent, 0 failed, 2 already done", self.run_command())
        self.assertEqual(self.sent(), [])

    def test_a_failed_send_is_retried_once_by_the_next_run(self):
        self.brevo_post.side_effect = requests.ConnectionError("Brevo down")
        self.assertIn("0 sent, 2 failed", self.run_command())
        self.assertEqual(ReminderLog.objects.filter(status="failed").count(), 2)
        self.brevo_post.side_effect = None
        self.brevo_post.reset_mock()
        self.assertIn("2 sent, 0 failed", self.run_command())
        self.assertIn("0 sent, 0 failed, 2 already done", self.run_command())
        self.assertEqual(len(self.sent()), 2)

    def test_the_next_scheduled_run_reminds_again(self):
        self.run_command()
        self._patch("django.utils.timezone.now", return_value=manila(2026, 11, 14, 9))
        self.brevo_post.reset_mock()
        self.assertIn("Payment run 2026-11-14: 2 sent", self.run_command())

    def test_nothing_outstanding_sends_nothing(self):
        ProcurementRequest.objects.filter(status="completed").update(status="cancelled")
        self.assertIn("0 sent, 0 failed, 0 already done", self.run_command())
        self.assertEqual(self.sent(), [])

    def test_reminders_change_no_financial_record_and_dry_run_sends_nothing(self):
        before = list(ProcurementRequest.objects.order_by("id").values()), list(Disbursement.objects.values())
        self.assertIn("[dry-run] payment 2026-11-07", self.run_command("--dry-run"))
        self.assertEqual((self.sent(), ReminderLog.objects.count()), ([], 0))
        self.run_command()
        self.assertEqual((list(ProcurementRequest.objects.order_by("id").values()), list(Disbursement.objects.values())), before)
