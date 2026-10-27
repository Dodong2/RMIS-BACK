import datetime
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError

from accounts.management.commands.cleanup_fresh_start import CLEAR, Command
from accounts.models import AuditLog, Permission, Role, RolePermission, User
from accounts.testing import RMISTestCase
from budget_lib.models import BudgetReview, LibItem, LineItemBudget
from personnel.models import Task
from research_projects.models import CollegeUnit, CooperatingAgency, EndorserChoice, Project

COMMAND = "accounts.management.commands.cleanup_fresh_start"
ADMIN = "admin@lspu.test"


class CleanupFreshStartTests(RMISTestCase):
    """Phase 4 cleanup (2026-10-27): only the kept System Admin and the reference lists survive."""

    def setUp(self):
        super().setUp()
        self.list_objects = self._patch(f"{COMMAND}.list_objects", return_value=["P-1/a.pdf", "_staged/b.pdf"])
        self.delete_objects = self._patch(f"{COMMAND}.delete_objects")
        self.auth_users = self._patch(f"{COMMAND}.auth_users", return_value=[("u1", "Leader@lspu.test"), ("u2", ADMIN)])
        self.delete_auth_user = self._patch(f"{COMMAND}.delete_auth_user")

        self.admin = self.make_user("system_admin", email=ADMIN, is_superuser=True, is_staff=True)
        self.other_admin = self.make_user("system_admin")
        leader = self.make_user("project_leader", email="leader@lspu.test")
        staff = self.make_user("project_staff")
        CollegeUnit.objects.create(code="CA", title="College of Agriculture")
        CooperatingAgency.objects.create(name="DOST-PCAARRD")
        EndorserChoice.objects.create(name="Dr. Dean", designation="Dean")
        # PROTECT chains the delete has to work through: project -> leader, task -> staff, review -> admin.
        project = Project.objects.create(
            title="P", project_code="P-1", funding_type="core_funded", lead=leader,
            start_date=datetime.date(2026, 1, 1), target_end_date=datetime.date(2027, 12, 31),
        )
        budget = LineItemBudget.objects.create(project=project, version_number=1)
        BudgetReview.objects.create(budget=budget, action="submitted", acted_by=self.admin)
        Task.objects.create(project=project, title="T", assignee=staff, assigned_by=leader)
        AuditLog.objects.create(actor=leader, method="POST", path="/api/x/", status_code=201)
        self.kept_before = Command().keep_counts()

    def run_cleanup(self, *args):
        out = StringIO()
        call_command("cleanup_fresh_start", "--keep-email", ADMIN, *args, stdout=out)
        return out.getvalue()

    def total(self):
        return sum(Command().clear_counts(self.admin).values())

    def test_dry_run_deletes_nothing(self):
        users = User.objects.count()

        output = self.run_cleanup()

        self.assertIn(f"Total rows to delete: {self.total()}", output)
        self.assertIn("Files in bucket research-documents: 2", output)
        self.assertIn("Supabase Auth users to delete: 1", output)
        self.assertEqual(User.objects.count(), users)
        self.assertEqual(Project.objects.count(), 1)
        self.delete_objects.assert_not_called()
        self.delete_auth_user.assert_not_called()

    def test_execute_keeps_only_the_admin_and_reference_lists(self):
        self.run_cleanup("--execute", "--expect", str(self.total()))

        self.assertEqual(list(User.objects.values_list("email", flat=True)), [ADMIN])
        admin = User.objects.get()
        self.assertEqual((admin.pk, admin.role.code, admin.is_superuser, admin.is_active),
                         (self.admin.pk, "system_admin", True, True))
        self.assertEqual(Command().keep_counts(), self.kept_before)
        self.assertEqual((Role.objects.count(), CollegeUnit.objects.count(), CooperatingAgency.objects.count(),
                          EndorserChoice.objects.count()), (12, 1, 1, 1))
        self.assertTrue(LibItem.objects.exists())
        self.assertTrue(Permission.objects.exists() and RolePermission.objects.exists())
        self.assertEqual(self.total(), 0)
        self.delete_objects.assert_called_once_with(["P-1/a.pdf", "_staged/b.pdf"])
        self.delete_auth_user.assert_called_once_with("u1")  # never the kept admin's e-mail, whatever its case

    def test_wrong_expect_deletes_nothing(self):
        total = self.total()

        with self.assertRaisesMessage(CommandError, "doesn't match"):
            self.run_cleanup("--execute", "--expect", str(total - 1))

        self.assertEqual(self.total(), total)
        self.delete_objects.assert_not_called()
        self.delete_auth_user.assert_not_called()

    def test_keep_email_must_be_a_system_admin(self):
        with self.assertRaisesMessage(CommandError, "existing System Admin"):
            call_command("cleanup_fresh_start", "--keep-email", "leader@lspu.test", "--execute", "--expect", "1",
                         stdout=StringIO())
        with self.assertRaisesMessage(CommandError, "existing System Admin"):
            call_command("cleanup_fresh_start", "--keep-email", "nobody@lspu.test", stdout=StringIO())

        self.assertEqual(Project.objects.count(), 1)

    def test_every_table_is_kept_or_cleared(self):
        Command().check_every_model_classified()  # raises if a model is in neither list
        self.assertEqual(len(CLEAR), len(set(CLEAR)))
