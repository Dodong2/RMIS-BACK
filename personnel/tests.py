import datetime
import io
from unittest import mock

from django.core.management import call_command
from django.utils import timezone

from accounts.testing import RMISTestCase
from monitoring.models import MidtermReport
from research_projects.models import Project

from .models import Task, TaskUpdate


class StaffNotificationTests(RMISTestCase):
    """Client follow-up 2026-10-02: staff are e-mailed their tasks; monthly/quarterly reminders; % completed."""

    def setUp(self):
        super().setUp()
        self.leader = self.make_user("project_leader", first_name="Aimee", last_name="Chavez")
        self.staff = self.make_user("project_staff", email="staff@lspu.test", first_name="Dan", last_name="Agustin")
        self.project = Project.objects.create(title="Bridging Academia", project_code="BRIDGI-1", funding_type="institutional", lead=self.leader)

    def sent(self):
        """(to, subject, html) of every Brevo call so far."""
        return [(c.kwargs["json"]["to"][0]["email"], c.kwargs["json"]["subject"], c.kwargs["json"]["htmlContent"])
                for c in self.brevo_post.call_args_list]

    def assign(self, **fields):
        payload = {"project": self.project.pk, "title": "Data collection", "assignee": self.staff.pk, "due_date": "2026-10-31", **fields}
        return self.client_for(self.leader).post("/api/personnel/tasks/", payload, format="json")

    def test_assigned_staff_is_emailed_the_task_with_calendar_links(self):
        response = self.assign(description="Survey the barangays")

        self.assertEqual(response.status_code, 201, response.data)
        [(to, subject, html)] = self.sent()
        self.assertEqual(to, "staff@lspu.test")
        self.assertIn("Data collection", subject)
        self.assertIn("Survey the barangays", html)
        self.assertIn(f"/tasks?view=calendar&amp;task={response.data['id']}", html)
        self.assertIn("calendar.google.com", html)
        self.assertIn("20261031%2F20261101", html)

    def test_reassigning_emails_the_new_assignee_and_other_edits_do_not(self):
        task_id = self.assign().data["id"]
        other = self.make_user("project_staff", email="other@lspu.test")
        client = self.client_for(self.leader)

        client.patch(f"/api/personnel/tasks/{task_id}/", {"title": "Data collection, round 2"}, format="json")
        client.patch(f"/api/personnel/tasks/{task_id}/", {"assignee": other.pk}, format="json")

        self.assertEqual([to for to, _, _ in self.sent()], ["staff@lspu.test", "other@lspu.test"])

    def test_mail_failure_does_not_undo_the_assignment(self):
        self.brevo_post.side_effect = ConnectionError("Brevo down")

        self.assertEqual(self.assign().status_code, 201)
        self.assertTrue(Task.objects.exists())

    def test_task_progress_is_the_latest_reported_percent(self):
        task_id = self.assign().data["id"]
        client = self.client_for(self.staff)

        client.post(f"/api/personnel/tasks/{task_id}/updates/", {"note": "Half the barangays", "hours": "6", "progress_pct": 50}, format="json")
        client.post(f"/api/personnel/tasks/{task_id}/updates/", {"note": "Comment only"}, format="json")
        bad = client.post(f"/api/personnel/tasks/{task_id}/updates/", {"note": "x", "progress_pct": 120}, format="json")

        self.assertEqual(bad.status_code, 400)
        self.assertEqual(client.get(f"/api/personnel/tasks/{task_id}/").data["progress_pct"], 50)

    def make_task_with_update(self, when, pct=50, hours=6):
        task = Task.objects.create(project=self.project, title="Data collection", assignee=self.staff, assigned_by=self.leader,
                                   due_date=datetime.date(2026, 12, 31))
        update = TaskUpdate.objects.create(task=task, author=self.staff, note="Half the barangays", hours=hours, progress_pct=pct)
        TaskUpdate.objects.filter(pk=update.pk).update(created_at=when)
        Task.objects.filter(pk=task.pk).update(created_at=when)
        return task

    def test_monthly_reminder_lists_last_months_accomplishments(self):
        self.make_task_with_update(timezone.make_aware(datetime.datetime(2026, 9, 15)))

        with mock.patch("django.utils.timezone.localdate", return_value=datetime.date(2026, 10, 1)):
            call_command("send_report_reminders", "--monthly", stdout=io.StringIO())

        [(to, subject, html)] = self.sent()
        self.assertEqual(to, "staff@lspu.test")
        self.assertIn("September 2026", subject)
        self.assertIn("Data collection", html)
        self.assertIn("50%", html)

    def test_quarterly_reminder_goes_to_leaders_and_riuh(self):
        self.make_user("riuh", email="riuh@lspu.test")
        MidtermReport.objects.create(project=self.project, project_year=1, submitted_by=self.leader, objective_accomplishments=[
            {"objective": "A", "q1": 40, "q2": None, "q3": None, "q4": None},
            {"objective": "B", "q1": 60, "q2": None, "q3": None, "q4": None},
        ])

        with mock.patch("django.utils.timezone.localdate", return_value=datetime.date(2026, 10, 1)):
            call_command("send_report_reminders", "--quarterly", stdout=io.StringIO())

        sent = {to: (subject, html) for to, subject, html in self.sent()}
        self.assertEqual(set(sent), {self.leader.email, "riuh@lspu.test"})
        self.assertIn("Q3 2026", sent[self.leader.email][0])
        self.assertIn("SF-017", sent[self.leader.email][1])
        self.assertIn("Year 1 Q1: 50%", sent["riuh@lspu.test"][1])

    def test_dry_run_sends_nothing(self):
        self.make_task_with_update(timezone.now())
        out = io.StringIO()

        call_command("send_report_reminders", "--quarterly", "--dry-run", stdout=out)

        self.assertEqual(self.sent(), [])
        self.assertIn("Would send 1", out.getvalue())

    def test_accomplishment_report_is_pulled_from_the_tasks(self):
        self.make_task_with_update(timezone.make_aware(datetime.datetime(2026, 9, 15)))

        response = self.client_for(self.staff).get("/api/reports/accomplishment/", {"month": "2026-09", "file_format": "csv"})

        self.assertEqual(response.status_code, 200)
        text = response.content.decode()
        for expected in ("MONTHLY ACCOMPLISHMENT REPORT", "Dan Agustin", "September 2026", "BRIDGI-1", "Data collection",
                         "50%", "Half the barangays", "TOTAL HOURS", "Aimee Chavez"):
            self.assertIn(expected, text)

    def test_accomplishment_report_scope(self):
        self.make_task_with_update(timezone.make_aware(datetime.datetime(2026, 9, 15)))
        other_staff = self.make_user("project_staff")
        other_leader = self.make_user("project_leader")
        params = {"user": self.staff.pk, "month": "2026-09", "file_format": "csv"}

        self.assertEqual(self.client_for(other_staff).get("/api/reports/accomplishment/", params).status_code, 404)
        self.assertNotIn("Data collection", self.client_for(other_leader).get("/api/reports/accomplishment/", params).content.decode())
        self.assertIn("Data collection", self.client_for(self.leader).get("/api/reports/accomplishment/", params).content.decode())
