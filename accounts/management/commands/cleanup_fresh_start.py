"""Fresh start for the shared Supabase project (Carl, 2026-10-27, Phase 4): delete every user except one kept System
Admin, every project and everything recorded under them, all sessions, every file in the documents bucket and every
Supabase Auth user. The System Admin's reference lists (KEEP) stay. No backup is taken (Carl's decision).

Dry run (default, changes nothing):
    python manage.py cleanup_fresh_start --keep-email <admin e-mail>
Execute (the total must match the dry run's, or nothing is deleted):
    python manage.py cleanup_fresh_start --execute --keep-email <admin e-mail> --expect <total rows>
"""

import requests
from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import ProtectedError

from document_management.storage import _headers, delete_objects, list_objects

# Kept untouched. Every model must be in KEEP or CLEAR, so a table added later can't be skipped or wiped by accident.
KEEP = [
    "accounts.Role", "accounts.Permission", "accounts.RolePermission",
    "research_projects.CollegeUnit", "research_projects.RdeThrust", "research_projects.FundingType",
    "research_projects.CooperatingAgency", "research_projects.EndorserChoice", "budget_lib.LibItem",
    # Admin-maintained lookups, not in Carl's list but empty on 2026-10-27; kept as reference data.
    "outputs.SenseRankedPublisher", "decision_support.DecisionCriterion", "monitoring.EvaluationCriterion",
    # Django and allauth configuration.
    "auth.Permission", "auth.Group", "contenttypes.ContentType", "sites.Site", "socialaccount.SocialApp",
]

# Emptied completely, except accounts.User, which keeps the --keep-email account.
CLEAR = [
    "accounts.User", "accounts.AuditLog", "accounts.TemporaryReplacement", "accounts.IdempotencyKey",
    "research_projects.Program", "research_projects.Project", "research_projects.ProjectTeamMember",
    "research_projects.TargetBeneficiary", "research_projects.ProjectEndorser", "research_projects.ProjectStatusHistory",
    "research_projects.Study", "research_projects.WorkPlanMilestone",
    "personnel.StaffProfile", "personnel.ProjectAssignment", "personnel.Task", "personnel.TaskDeliverable",
    "personnel.TaskUpdate", "personnel.PersonnelChange", "personnel.PropertyClearance",
    "budget_lib.LineItemBudget", "budget_lib.BudgetReview", "budget_lib.LineItem", "budget_lib.LineItemEdit",
    "financial_monitoring.Disbursement", "financial_monitoring.BudgetRealignment",
    "financial_monitoring.ProcurementRequest", "financial_monitoring.ProcurementStatusEvent",
    "compliance.EthicsReviewReference", "compliance.SimilarityCheckRecord", "compliance.AIUseDeclaration",
    "compliance.ConflictOfInterestDisclosure", "compliance.MisconductCaseReference", "compliance.ComplianceRequirement",
    "document_management.Document", "document_management.DocumentShare",
    "outputs.PublicationRecord", "outputs.IPRecord", "outputs.CreativeWorkRecord", "outputs.ExpectedOutput",
    "outputs.ProjectOutcome",
    "monitoring.MonthlyProgressReport", "monitoring.MidtermReport", "monitoring.TerminalReport",
    "monitoring.ProjectEvaluation", "monitoring.RenewalApplication", "monitoring.ExtensionRequest",
    "monitoring.EvaluationScore", "monitoring.QuarterlyProgressReport", "monitoring.QuarterlyReportEvent",
    "dashboard.PlanningTarget", "forecasting.ForecastRun", "forecasting.MonthlyForecast",
    "decision_support.AHPMatrixRun", "decision_support.AHPPairwiseComparison",
    "decision_support.FundingRecommendationRun", "decision_support.ProjectScore", "decision_support.DecisionRecord",
    "risk_indicators.ProjectRisk", "risk_indicators.RiskUpdate", "reports.GeneratedReportLog",
    "budget_sync.BudgetOfficeImport", "budget_sync.BudgetOfficeRecord",
    "sessions.Session", "admin.LogEntry", "authtoken.Token",
    "account.EmailAddress", "account.EmailConfirmation", "socialaccount.SocialAccount", "socialaccount.SocialToken",
]


def auth_users():
    """Every Supabase Auth user (Google sign-ins) as (id, email)."""
    users, page = [], 1
    while True:
        resp = requests.get(
            f"{settings.SUPABASE_URL}/auth/v1/admin/users", headers=_headers(), params={"page": page, "per_page": 1000},
        )
        resp.raise_for_status()
        batch = resp.json()["users"]
        users += [(u["id"], u.get("email") or "") for u in batch]
        if len(batch) < 1000:
            return users
        page += 1


def delete_auth_user(uid):
    requests.delete(f"{settings.SUPABASE_URL}/auth/v1/admin/users/{uid}", headers=_headers()).raise_for_status()


class Command(BaseCommand):
    help = "Delete all users except one System Admin, all project data, sessions, files and Supabase Auth users."

    def add_arguments(self, parser):
        parser.add_argument("--execute", action="store_true", help="Actually delete. Without it, only a dry run.")
        parser.add_argument("--keep-email", required=True, help="The System Admin account to keep.")
        parser.add_argument("--expect", type=int, help="Total rows from the dry run; must match to execute.")

    def handle(self, *args, execute, keep_email, expect, **options):
        self.check_every_model_classified()
        User = apps.get_model("accounts", "User")
        keep = User.objects.filter(email__iexact=keep_email.strip()).first()
        if keep is None or keep.role is None or keep.role.code != "system_admin":
            raise CommandError("--keep-email must name an existing System Admin account.")

        counts = self.clear_counts(keep)
        total = sum(counts.values())
        for label, n in counts.items():
            if n:
                self.stdout.write(f"  delete {label}: {n}")
        self.stdout.write(f"Total rows to delete: {total}")
        files = list_objects()
        self.stdout.write(f"Files in bucket {settings.SUPABASE_STORAGE_BUCKET}: {len(files)}")
        supabase_users = [(uid, email) for uid, email in auth_users() if email.lower() != keep.email.lower()]
        self.stdout.write(f"Supabase Auth users to delete: {len(supabase_users)}")
        kept = self.keep_counts()
        self.stdout.write("Kept: " + ", ".join(f"{label} {n}" for label, n in kept.items() if n))
        self.stdout.write(f"Kept account: id {keep.pk} ({keep.role.code})")

        if not execute:
            self.stdout.write(self.style.WARNING("Dry run: nothing was deleted. Re-run with the same --keep-email plus "
                                                 f"--execute --expect {total} to delete."))
            return
        if expect != total:
            raise CommandError(f"--expect {expect} doesn't match the {total} rows found now. Nothing was deleted.")

        with transaction.atomic():
            self.delete_rows(keep)
            if self.keep_counts() != kept or not User.objects.filter(pk=keep.pk, role=keep.role, is_active=True).exists():
                raise CommandError("Kept data changed. Rolled back, nothing was deleted.")
            left = {label: n for label, n in self.clear_counts(keep).items() if n}
            if left:
                raise CommandError(f"Rows left after delete: {left}. Rolled back, nothing was deleted.")
        self.stdout.write(self.style.SUCCESS(f"Deleted {total} rows."))

        # Outside the transaction: these can't be rolled back, so they run only after the database commit.
        # A failure here leaves the database clean; re-run the command to finish (it then finds 0 rows).
        delete_objects(files)
        self.stdout.write(self.style.SUCCESS(f"Deleted {len(files)} files."))
        for uid, _email in supabase_users:
            delete_auth_user(uid)
        self.stdout.write(self.style.SUCCESS(f"Deleted {len(supabase_users)} Supabase Auth users."))

    def check_every_model_classified(self):
        listed = set(KEEP) | set(CLEAR)
        missing = [f"{m._meta.app_label}.{m.__name__}" for m in apps.get_models() if not m._meta.proxy]
        missing = [label for label in missing if label not in listed]
        if missing:
            raise CommandError(f"Not in KEEP or CLEAR: {missing}. Classify them first.")

    def clear_queryset(self, label, keep):
        qs = apps.get_model(label).objects.all()
        return qs.exclude(pk=keep.pk) if label == "accounts.User" else qs

    def clear_counts(self, keep):
        return {label: self.clear_queryset(label, keep).count() for label in CLEAR}

    def keep_counts(self):
        return {label: apps.get_model(label).objects.count() for label in KEEP}

    def delete_rows(self, keep):
        """Deletes in passes: a PROTECT foreign key blocks a table until the rows pointing at it are gone.
        Django raises ProtectedError before it writes anything, so a blocked pass is simply retried."""
        pending = list(CLEAR)
        while pending:
            blocked = []
            for label in pending:
                try:
                    self.clear_queryset(label, keep).delete()
                except ProtectedError:
                    blocked.append(label)
            if len(blocked) == len(pending):
                raise CommandError(f"Can't delete, still protected: {blocked}. Rolled back, nothing was deleted.")
            pending = blocked
