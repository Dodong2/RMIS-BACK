"""2026-10-22 real-time for tasks: every task write (board, Work Log, review, deliverables, reassignment on a personnel
change) sends "personnel.task.changed" {id, project} to the task assigners' roles, the project lead and the people on
the task. A write can save several rows, so tests check that a signal went out and to whom, not how many."""
import datetime

from accounts.testing import RMISTestCase
from budget_lib.models import LineItemBudget
from realtime.notify import to_role, to_user
from research_projects.models import Program, Project

from .models import PersonnelChange, ProjectAssignment, PropertyClearance, Task

ASSIGNER_ROLES = {"system_admin", "crc_chair", "drd", "riuh"}  # leaders are reached per user


def certify(project):
    """Work on a project starts once its LIB is certified (Carl 2026-10-24, D5)."""
    LineItemBudget.objects.create(project=project, version_number=1, status="certified")


class TaskSignalTests(RMISTestCase):
    def setUp(self):
        super().setUp()
        self.notify = self._patch("personnel.signals.notify")
        self.leader = self.make_user("project_leader")
        self.program_leader = self.make_user("program_leader")
        self.staff = self.make_user("project_staff")
        program = Program.objects.create(title="Prog", lead=self.program_leader)
        self.project = Project.objects.create(title="P", project_code="P-1", funding_type="institutional",
                                              lead=self.leader, program=program)
        certify(self.project)
        self.leader_client = self.client_for(self.leader)

    def assert_signalled(self, task_id, *users):
        self.assertTrue(self.notify.called, "no personnel.task.changed sent")
        for (groups, event_type), data in self.notify.call_args_list:
            self.assertEqual(event_type, "personnel.task.changed")
            self.assertEqual(data, {"id": task_id, "project": self.project.id})
            expected = {*map(to_role, ASSIGNER_ROLES), *(to_user(u.pk) for u in (self.leader, self.program_leader, *users))}
            self.assertEqual(set(groups), expected)
        self.notify.reset_mock()

    def add_task(self):
        response = self.leader_client.post("/api/personnel/tasks/", {
            "project": self.project.pk, "title": "Survey", "assignee": self.staff.pk,
            "start_date": "2026-11-02", "due_date": "2026-11-06"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["id"]

    def test_board_work_log_review_and_delete(self):
        task_id = self.add_task()
        self.assert_signalled(task_id, self.staff)

        staff = self.client_for(self.staff)
        response = staff.post(f"/api/personnel/tasks/{task_id}/updates/", {"note": "Half", "hours": "8"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assert_signalled(task_id, self.staff)

        self.assertEqual(self.leader_client.patch(f"/api/personnel/tasks/{task_id}/", {"status": "for_review"},
                                                  format="json").status_code, 200)
        self.assert_signalled(task_id, self.staff)
        response = self.leader_client.post(f"/api/personnel/tasks/{task_id}/review/", {"action": "return"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_signalled(task_id, self.staff)

        response = self.leader_client.post(f"/api/personnel/tasks/{task_id}/deliverables/", {"text": "Forms"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assert_signalled(task_id, self.staff)

        self.assertEqual(self.leader_client.delete(f"/api/personnel/tasks/{task_id}/").status_code, 204)
        self.assert_signalled(task_id, self.staff)

    def test_refused_write_sends_nothing(self):
        task_id = self.add_task()
        self.notify.reset_mock()
        other_staff = self.client_for(self.make_user("project_staff"))
        self.assertEqual(other_staff.post(f"/api/personnel/tasks/{task_id}/updates/", {"note": "x"}, format="json").status_code, 404)
        self.notify.assert_not_called()

    def test_reassignment_on_a_personnel_change(self):
        incoming = self.make_user("project_staff")
        task = Task.objects.create(project=self.project, title="Survey", assignee=self.staff, assigned_by=self.leader,
                                   due_date=datetime.date(2026, 12, 31))
        old = ProjectAssignment.objects.create(user=self.staff, project=self.project, start_date=datetime.date(2026, 1, 1))
        change = PersonnelChange.objects.create(change_type="staff", assignment=old, project=self.project, outgoing=self.staff,
                                                incoming=incoming, reason="Transfer", status="cleared", initiated_by=self.leader)
        PropertyClearance.objects.create(change=change)
        self.notify.reset_mock()
        admin = self.client_for(self.make_user("system_admin"))
        self.assertEqual(admin.post(f"/api/personnel/changes/{change.id}/complete/").status_code, 200)
        self.assert_signalled(task.id, self.staff, incoming)
