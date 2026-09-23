from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from budget_lib.models import LineItem
from financial_monitoring.models import Disbursement

from .models import MidtermReport, MonthlyProgressReport, ProjectEvaluation, RenewalApplication, TerminalReport

REPORT_ROLES = ["system_admin", "riuh", "project_leader", "study_leader", "project_staff"]
TERMINAL_CERTIFY_ROLES = ["system_admin", "riuh"]
EVALUATION_PANEL_ROLES = ["system_admin", "vprei", "drd", "crc_chair"]
RENEWAL_DECISION_ROLES = ["system_admin", "riuh", "drd", "vprei"]


def months_between(earlier, later):
    return (later.year - earlier.year) * 12 + (later.month - earlier.month)


def compute_escalation_status(project):
    """Live status, not a stored/scheduled flag (no Celery/cron in this project yet) —
    checked on read rather than proactively pushed."""
    last_report = MonthlyProgressReport.objects.filter(project=project).order_by("-period").first()
    baseline = last_report.period if last_report else project.start_date
    if baseline is None:
        return {"status": "unknown", "months_since_last_report": None}

    gap = months_between(baseline, timezone.localdate())
    if gap >= 6:
        status = "terminate_recommended"
    elif gap >= 3:
        status = "notify_dean_riuh"
    else:
        status = "on_track"
    return {"status": status, "months_since_last_report": gap}


def compute_budget_used_pct(project):
    current_budget = project.budgets.filter(is_current=True).first()
    if current_budget is None:
        return None
    total = LineItem.objects.filter(budget=current_budget).aggregate(total=Sum("amount"))["total"]
    if not total:
        return None
    spent = Disbursement.objects.filter(line_item__budget=current_budget).aggregate(total=Sum("amount"))["total"] or 0
    return round(float(spent) / float(total) * 100, 2)


def compute_deliverables_pct(project):
    milestones = project.milestones.all()
    total = milestones.count()
    if total == 0:
        return None
    done = milestones.filter(status="done").count()
    return round(done / total * 100, 2)


def compute_renewal_eligible(project, has_justification):
    budget_pct = compute_budget_used_pct(project)
    deliverables_pct = compute_deliverables_pct(project)
    if budget_pct is not None and budget_pct >= 70:
        return True
    if has_justification and deliverables_pct is not None and deliverables_pct >= 70:
        return True
    return False


class MonthlyProgressReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = MonthlyProgressReport
        fields = ["id", "project", "period", "narrative", "document", "submitted_by", "submitted_at"]
        read_only_fields = ["submitted_by"]


class MidtermReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = MidtermReport
        fields = [
            "id", "project", "project_year", "narrative", "expenditure_summary",
            "document", "submitted_by", "submitted_at",
        ]
        read_only_fields = ["submitted_by"]


class TerminalReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = TerminalReport
        fields = [
            "id", "project", "narrative", "document", "submitted_by", "submitted_at",
            "is_certified", "certified_by", "certified_at",
        ]
        read_only_fields = ["submitted_by", "is_certified", "certified_by", "certified_at"]


class ProjectEvaluationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectEvaluation
        fields = [
            "id", "project", "project_year", "scheduled_date", "panel_members",
            "outcome", "remarks", "evaluated_by", "evaluated_at", "created_at",
        ]
        read_only_fields = ["evaluated_by", "evaluated_at"]


class RenewalApplicationSerializer(serializers.ModelSerializer):
    renewal_eligible = serializers.SerializerMethodField()
    budget_used_pct = serializers.SerializerMethodField()
    deliverables_pct = serializers.SerializerMethodField()

    class Meta:
        model = RenewalApplication
        fields = [
            "id", "project", "application_year", "underspend_justification", "status",
            "decided_by", "decided_at", "submitted_by", "submitted_at",
            "renewal_eligible", "budget_used_pct", "deliverables_pct",
        ]
        read_only_fields = ["status", "decided_by", "decided_at", "submitted_by"]

    def get_renewal_eligible(self, obj):
        return compute_renewal_eligible(obj.project, bool(obj.underspend_justification))

    def get_budget_used_pct(self, obj):
        return compute_budget_used_pct(obj.project)

    def get_deliverables_pct(self, obj):
        return compute_deliverables_pct(obj.project)


class ProjectMonitoringStatusSerializer(serializers.Serializer):
    """Read-only snapshot for a single project — the live status a Dean/RIUH/panel
    would check, since nothing here is pushed proactively (no Celery/cron yet)."""

    project = serializers.IntegerField(source="id")
    escalation_status = serializers.SerializerMethodField()
    months_since_last_report = serializers.SerializerMethodField()
    budget_used_pct = serializers.SerializerMethodField()
    deliverables_pct = serializers.SerializerMethodField()
    midterm_submitted_years = serializers.SerializerMethodField()
    terminal_submitted = serializers.SerializerMethodField()

    def get_escalation_status(self, obj):
        return compute_escalation_status(obj)["status"]

    def get_months_since_last_report(self, obj):
        return compute_escalation_status(obj)["months_since_last_report"]

    def get_budget_used_pct(self, obj):
        return compute_budget_used_pct(obj)

    def get_deliverables_pct(self, obj):
        return compute_deliverables_pct(obj)

    def get_midterm_submitted_years(self, obj):
        return list(obj.midterm_reports.values_list("project_year", flat=True))

    def get_terminal_submitted(self, obj):
        return TerminalReport.objects.filter(project=obj).exists()
