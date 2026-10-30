"""Task 25 (2026-10-30): Project Staff task reminders from send_scheduled_reminders, Monday, Tuesday and Wednesday (08:00 Manila;
Task 26, Carl 2026-10-30) from the start date until Done."""
import datetime
from io import StringIO
from zoneinfo import ZoneInfo

import requests
from django.core.management import call_command

from accounts.models import ReminderLog
from accounts.testing import RMISTestCase
from financial_monitoring.management.commands.send_scheduled_reminders import task_reminder_day
from research_projects.models import Project

from .models import Task
from .tests import certify

MANILA = ZoneInfo("Asia/Manila")


def manila(*args):
    return datetime.datetime(*args, tzinfo=MANILA)


class TaskReminderDayTests(RMISTestCase):
    # November 2, 2026 is a Monday.
    def test_monday_tuesday_wednesday_at_8am_manila(self):
        task = Task(start_date=datetime.date(2026, 11, 2))
        self.assertIsNone(task_reminder_day(task, manila(2026, 11, 1, 12)))
        self.assertIsNone(task_reminder_day(task, manila(2026, 11, 2, 7, 59)))
        for day in (2, 3, 4):
            self.assertEqual(task_reminder_day(task, manila(2026, 11, day, 8)), datetime.date(2026, 11, day))
        self.assertEqual(task_reminder_day(task, manila(2026, 11, 9, 7, 59)), datetime.date(2026, 11, 4))
        self.assertEqual(task_reminder_day(task, manila(2026, 11, 9, 8)), datetime.date(2026, 11, 9))
        # 23:30 UTC on Nov 2 is 07:30 Nov 3 in Manila: Tuesday's reminder isn't due yet; 00:30 UTC is 08:30, it is.
        self.assertEqual(task_reminder_day(task, datetime.datetime(2026, 11, 2, 23, 30, tzinfo=datetime.UTC)), datetime.date(2026, 11, 2))
        self.assertEqual(task_reminder_day(task, datetime.datetime(2026, 11, 3, 0, 30, tzinfo=datetime.UTC)), datetime.date(2026, 11, 3))
        self.assertIsNone(task_reminder_day(Task(start_date=None), manila(2026, 11, 3, 9)))

    def test_a_missed_wednesday_is_caught_up_on_a_weekday_never_on_a_weekend(self):
        task = Task(start_date=datetime.date(2026, 11, 2))
        for day in (5, 6):
            self.assertEqual(task_reminder_day(task, manila(2026, 11, day, 9)), datetime.date(2026, 11, 4))
        for day in (7, 8):
            self.assertIsNone(task_reminder_day(task, manila(2026, 11, day, 9)))

    def test_a_task_starting_on_thursday_waits_for_monday(self):
        task = Task(start_date=datetime.date(2026, 11, 5))
        self.assertIsNone(task_reminder_day(task, manila(2026, 11, 5, 9)))
        self.assertIsNone(task_reminder_day(task, manila(2026, 11, 6, 9)))
        self.assertEqual(task_reminder_day(task, manila(2026, 11, 9, 8)), datetime.date(2026, 11, 9))

    def test_exactly_three_reminder_days_a_week(self):
        task = Task(start_date=datetime.date(2026, 11, 2))
        days = {task_reminder_day(task, manila(2026, 11, 2, 8) + datetime.timedelta(hours=h)) for h in range(14 * 24)} - {None}
        self.assertEqual(days, {datetime.date(2026, 11, d) for d in (2, 3, 4, 9, 10, 11)})


class TaskReminderTests(RMISTestCase):
    def setUp(self):
        super().setUp()
        self.leader = self.make_user("project_leader", first_name="Aimee", last_name="Chavez")
        self.staff = self.make_user("project_staff", email="staff@lspu.test", first_name="Dan", last_name="Agustin")
        self.other = self.make_user("project_staff", email="other@lspu.test")
        self.project = Project.objects.create(title="Bridging <Academia>", project_code="BRIDGI-1", funding_type="institutional",
                                              lead=self.leader)
        certify(self.project)
        self.task = self.make_task("Data collection", start=datetime.date(2026, 11, 2), due=datetime.date(2026, 11, 6))
        self.now = self._patch("django.utils.timezone.now", return_value=manila(2026, 11, 4, 8, 10))

    def make_task(self, title, start, due, assignee=None, status="pending"):
        return Task.objects.create(project=self.project, title=title, description="Survey the barangays", start_date=start,
                                   due_date=due, assignee=assignee or self.staff, assigned_by=self.leader, status=status)

    def run_command(self):
        out = StringIO()
        call_command("send_scheduled_reminders", stdout=out)
        return out.getvalue()

    def sent(self):
        return [(c.kwargs["json"]["to"][0]["email"], c.kwargs["json"]["subject"], c.kwargs["json"]["htmlContent"])
                for c in self.brevo_post.call_args_list]

    def test_the_assignee_gets_the_task_reminder(self):
        self.assertIn("Task reminders: 1 sent, 0 failed", self.run_command())
        [(to, subject, html)] = self.sent()
        self.assertEqual((to, subject), ("staff@lspu.test", "Task Reminder — Data collection"))
        for text in ("This is a reminder about your assigned project task.", "Bridging &lt;Academia&gt;", "Survey the barangays",
                     "November 02, 2026", "November 06, 2026", "completed within the scheduled period"):
            self.assertIn(text, html)
        self.assertNotIn("Payment Reminder", subject)
        self.assertTrue(ReminderLog.objects.filter(kind="task", run_key="2026-11-04", object_ref=f"task:{self.task.pk}").exists())

    def test_once_per_reminder_day_and_again_on_the_next_one(self):
        self.run_command()
        self.brevo_post.reset_mock()
        self.assertIn("Task reminders: 0 sent, 0 failed, 1 already done", self.run_command())
        self.now.return_value = manila(2026, 11, 5, 9)  # Thursday: only Wednesday's, already sent
        self.assertIn("Task reminders: 0 sent, 0 failed, 1 already done", self.run_command())
        self.now.return_value = manila(2026, 11, 7, 9)  # Saturday
        self.assertIn("Task reminders: 0 sent, 0 failed, 0 already done", self.run_command())
        self.now.return_value = manila(2026, 11, 9, 8)  # Monday
        self.assertIn("Task reminders: 1 sent", self.run_command())
        self.assertEqual(len(self.sent()), 1)

    def test_overdue_tasks_keep_reminding_and_done_ones_stop(self):
        self.now.return_value = manila(2026, 11, 23, 8)  # a Monday past the Nov 6 end date
        self.assertIn("1 sent", self.run_command())
        Task.objects.filter(pk=self.task.pk).update(status="done")
        self.now.return_value = manila(2026, 11, 24, 8)
        self.assertIn("Task reminders: 0 sent, 0 failed, 0 already done", self.run_command())

    def test_only_project_staff_get_task_reminders(self):
        self.make_task("Leader's own task", start=datetime.date(2026, 11, 2), due=datetime.date(2026, 11, 6), assignee=self.leader)
        self.make_task("Finance's task", start=datetime.date(2026, 11, 2), due=datetime.date(2026, 11, 6),
                       assignee=self.make_user("finance_budget"))
        self.run_command()
        self.assertEqual([to for to, _, _ in self.sent()], ["staff@lspu.test"])

    def test_reassigning_moves_the_reminders_to_the_new_assignee(self):
        Task.objects.filter(pk=self.task.pk).update(assignee=self.other)
        self.run_command()
        self.assertEqual([to for to, _, _ in self.sent()], ["other@lspu.test"])

    def test_not_started_undated_inactive_and_closed_project_tasks_are_skipped(self):
        self.make_task("Later", start=datetime.date(2026, 11, 10), due=datetime.date(2026, 11, 20))
        self.make_task("No dates", start=None, due=None)
        gone = self.make_user("project_staff", email="gone@lspu.test", is_active=False)
        self.make_task("Inactive", start=datetime.date(2026, 11, 2), due=datetime.date(2026, 11, 6), assignee=gone)
        closed = Project.objects.create(title="Closed", project_code="OLD-1", funding_type="institutional", lead=self.leader,
                                        status="completed")
        Task.objects.create(project=closed, title="Old task", start_date=datetime.date(2026, 11, 2), assignee=self.staff,
                            assigned_by=self.leader)
        self.run_command()
        self.assertEqual([subject for _, subject, _ in self.sent()], ["Task Reminder — Data collection"])

    def test_a_failed_reminder_is_retried_without_a_duplicate(self):
        self.brevo_post.side_effect = requests.ConnectionError("Brevo down")
        self.assertIn("Task reminders: 0 sent, 1 failed", self.run_command())
        self.brevo_post.side_effect = None
        self.brevo_post.reset_mock()
        self.assertIn("Task reminders: 1 sent", self.run_command())
        self.assertIn("1 already done", self.run_command())
        self.assertEqual(len(self.sent()), 1)
