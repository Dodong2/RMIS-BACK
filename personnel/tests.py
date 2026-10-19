import datetime
import io
from unittest import mock

from django.core.management import call_command
from django.utils import timezone

from accounts.testing import RMISTestCase
from monitoring.models import MidtermReport
from research_projects.models import Project

from .models import Task, TaskUpdate, working_days


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
        payload = {"project": self.project.pk, "title": "Data collection", "assignee": self.staff.pk,
                   "start_date": "2026-10-26", "due_date": "2026-10-31", **fields}
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


class MilestoneTaskTests(RMISTestCase):
    """Client meeting 2026-10-01 (#14): milestone = parent, tasks = its activities, done only when all tasks are."""

    def setUp(self):
        super().setUp()
        from research_projects.models import WorkPlanMilestone

        self.leader = self.make_user("project_leader")
        self.staff = self.make_user("project_staff")
        self.project = Project.objects.create(title="P", project_code="P-1", funding_type="institutional", lead=self.leader)
        self.milestone = WorkPlanMilestone.objects.create(project=self.project, title="Data gathering", target_date=datetime.date(2026, 6, 30))
        self.client = self.client_for(self.leader)

    def add_task(self, title, **fields):
        response = self.client.post("/api/personnel/tasks/", {
            "project": self.project.pk, "title": title, "assignee": self.staff.pk, "milestone": self.milestone.pk,
            "start_date": "2026-06-01", "due_date": "2026-06-05", **fields,
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["id"]

    def milestone_data(self):
        return self.client.get(f"/api/milestones/{self.milestone.pk}/").data

    def test_progress_and_done_gate(self):
        first, second = self.add_task("Survey"), self.add_task("Interviews")
        Task.objects.filter(pk=first).update(status="done")

        data = self.milestone_data()
        blocked = self.client.patch(f"/api/milestones/{self.milestone.pk}/", {"status": "done"}, format="json")
        Task.objects.filter(pk=second).update(status="done")
        allowed = self.client.patch(f"/api/milestones/{self.milestone.pk}/", {"status": "done"}, format="json")

        self.assertEqual((data["tasks_total"], data["tasks_done"], data["progress_pct"]), (2, 1, 50))
        self.assertEqual(blocked.status_code, 400)
        self.assertIn("not done", str(blocked.data))
        self.assertEqual(allowed.status_code, 200)

    def test_milestone_without_tasks_works_as_before(self):
        response = self.client.patch(f"/api/milestones/{self.milestone.pk}/", {"status": "done"}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["progress_pct"], 100)

    def test_milestone_must_be_in_the_same_project(self):
        other = Project.objects.create(title="O", project_code="O-1", funding_type="institutional", lead=self.leader)

        response = self.client.post("/api/personnel/tasks/", {
            "project": other.pk, "title": "x", "assignee": self.staff.pk, "milestone": self.milestone.pk,
            "start_date": "2026-06-01", "due_date": "2026-06-05",
        }, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("milestone", response.data)

    def test_task_due_date_stays_within_the_activity_dates(self):
        self.milestone.start_date = datetime.date(2026, 3, 1)
        self.milestone.save()
        post = lambda start, due: self.client.post("/api/personnel/tasks/", {
            "project": self.project.pk, "title": "x", "assignee": self.staff.pk, "milestone": self.milestone.pk,
            "start_date": start, "due_date": due,
        }, format="json")

        self.assertEqual(post("2026-02-27", "2026-03-03").status_code, 400)
        self.assertEqual(post("2026-06-29", "2026-07-01").status_code, 400)
        self.assertIn("planned dates", str(post("2026-06-29", "2026-07-01").data))
        self.assertIn("planned dates", str(post("2026-02-27", "2026-03-03").data))
        self.assertEqual(post("2026-03-02", "2026-03-06").status_code, 201)
        self.assertEqual(post("2026-06-29", "2026-06-30").status_code, 201)

    def test_old_task_outside_the_dates_can_still_be_edited(self):
        task = Task.objects.get(pk=self.add_task("Survey"))
        Task.objects.filter(pk=task.pk).update(due_date=datetime.date(2026, 12, 1))

        response = self.client.patch(f"/api/personnel/tasks/{task.pk}/", {"title": "Survey v2"}, format="json")

        self.assertEqual(response.status_code, 200, response.data)

    def test_tasks_filter_by_milestone(self):
        self.add_task("Survey")
        self.client.post("/api/personnel/tasks/", {"project": self.project.pk, "title": "Loose", "assignee": self.staff.pk,
                                                   "start_date": "2026-06-01", "due_date": "2026-06-05"}, format="json")

        titles = [t["title"] for t in self.client.get("/api/personnel/tasks/", {"milestone": self.milestone.pk}).data]

        self.assertEqual(titles, ["Survey"])


class PersonnelTransitionsHappenOnceTests(RMISTestCase):
    """2026-10-12 concurrency audit: a repeated click changes nothing (row lock + state check)."""

    def setUp(self):
        super().setUp()
        from research_projects.models import Project
        self.leader, self.staff, self.incoming = self.make_user("project_leader"), self.make_user("project_staff"), self.make_user("project_staff")
        self.project = Project.objects.create(title="P", project_code="P-1", funding_type="core_funded", lead=self.leader)
        self.admin = self.client_for(self.make_user("system_admin"))

    def test_completing_a_staff_change_twice_creates_one_new_assignment(self):
        from personnel.models import PersonnelChange, ProjectAssignment, PropertyClearance
        old = ProjectAssignment.objects.create(user=self.staff, project=self.project, start_date=datetime.date(2026, 1, 1))
        change = PersonnelChange.objects.create(change_type="staff", assignment=old, project=self.project, outgoing=self.staff,
                                                incoming=self.incoming, reason="Transfer", status="cleared", initiated_by=self.leader)
        PropertyClearance.objects.create(change=change)
        url = f"/api/personnel/changes/{change.id}/complete/"
        self.assertEqual(self.admin.post(url).status_code, 200)
        self.assertEqual(self.admin.post(url).status_code, 400)
        self.assertEqual(ProjectAssignment.objects.filter(user=self.incoming).count(), 1)

    def test_task_review_is_decided_once(self):
        task = Task.objects.create(project=self.project, title="Survey", assignee=self.staff, assigned_by=self.leader,
                                   due_date=datetime.date(2026, 12, 31), status="for_review")
        url = f"/api/personnel/tasks/{task.id}/review/"
        self.assertEqual(self.admin.post(url, {"action": "approve"}).status_code, 200)
        self.assertEqual(self.admin.post(url, {"action": "return"}).status_code, 400)
        task.refresh_from_db()
        self.assertEqual(task.status, "done")


class TaskScheduleTests(RMISTestCase):
    """Client 2026-10-19: a task has a Start and End (due) date; planned hours = working days (Mon-Fri, inclusive) x 8."""

    def setUp(self):
        super().setUp()
        self.leader = self.make_user("project_leader")
        self.staff = self.make_user("project_staff")
        self.project = Project.objects.create(title="P", project_code="P-1", funding_type="institutional", lead=self.leader)
        self.client = self.client_for(self.leader)

    def create(self, start, due, **fields):
        return self.client.post("/api/personnel/tasks/", {
            "project": self.project.pk, "title": "Survey", "assignee": self.staff.pk, "start_date": start, "due_date": due, **fields,
        }, format="json")

    def test_working_days_skip_weekends_and_count_both_ends(self):
        day = datetime.date.fromisoformat
        self.assertEqual(working_days(day("2026-10-19"), day("2026-10-23")), 5)  # Mon-Fri
        self.assertEqual(working_days(day("2026-10-23"), day("2026-10-26")), 2)  # Fri-Mon
        self.assertEqual(working_days(day("2026-10-19"), day("2026-10-19")), 1)  # same day
        self.assertEqual(working_days(day("2026-10-24"), day("2026-10-25")), 0)  # Sat-Sun
        self.assertEqual(working_days(day("2026-10-19"), day("2026-10-30")), 10)  # two weeks

    def test_planned_hours_come_from_the_dates_not_the_client(self):
        response = self.create("2026-10-19", "2026-10-23", estimated_hours="3")

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["estimated_hours"], "40.00")

    def test_start_and_end_dates_are_required_for_a_new_task(self):
        response = self.client.post("/api/personnel/tasks/", {
            "project": self.project.pk, "title": "Survey", "assignee": self.staff.pk, "due_date": "2026-10-23",
        }, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("start_date", response.data)

    def test_end_before_start_or_no_working_day_is_rejected(self):
        backwards = self.create("2026-10-23", "2026-10-19")
        weekend = self.create("2026-10-24", "2026-10-25")

        self.assertEqual(backwards.status_code, 400)
        self.assertIn("due_date", backwards.data)
        self.assertEqual(weekend.status_code, 400)
        self.assertIn("working day", str(weekend.data))

    def test_changing_the_dates_recomputes_planned_hours(self):
        task_id = self.create("2026-10-19", "2026-10-23").data["id"]

        response = self.client.patch(f"/api/personnel/tasks/{task_id}/", {"due_date": "2026-10-20"}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["estimated_hours"], "16.00")

    def test_old_task_without_a_start_date_can_still_be_edited(self):
        task = Task.objects.create(project=self.project, title="Old", assignee=self.staff, assigned_by=self.leader,
                                   due_date=datetime.date(2026, 10, 23), estimated_hours=12)

        response = self.client.patch(f"/api/personnel/tasks/{task.pk}/", {"title": "Old v2"}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["estimated_hours"], "12.00")
