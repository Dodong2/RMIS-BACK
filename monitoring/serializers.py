from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from budget_lib.models import LineItem
from financial_monitoring.models import Disbursement

from .models import (
    EvaluationCriterion, EvaluationScore, ExtensionRequest, MidtermReport, MonthlyProgressReport, ProjectEvaluation, RenewalApplication, TerminalReport,
)

REPORT_ROLES = ["system_admin", "riuh", "project_leader", "study_leader", "project_staff"]
TERMINAL_CERTIFY_ROLES = ["system_admin", "riuh"]
EVALUATION_PANEL_ROLES = ["system_admin", "vprei", "drd", "crc_chair"]
RENEWAL_DECISION_ROLES = ["system_admin", "riuh", "drd", "vprei"]
EXTENSION_REQUEST_ROLES = ["system_admin", "program_leader", "project_leader"]
EXTENSION_ENDORSE_ROLES = ["system_admin", "drd", "crc_chair"]  # DRD, or the campus coordinator
EXTENSION_APPROVE_ROLES = ["system_admin", "university_admin"]  # University President
EXTENSION_MIN_LEAD_DAYS = 30  # "approved one (1) month before the expected date of project termination"


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
    weighted_score = serializers.SerializerMethodField()

    class Meta:
        model = ProjectEvaluation
        fields = [
            "id", "project", "project_year", "scheduled_date", "panel_members",
            "outcome", "remarks", "evaluated_by", "evaluated_at", "created_at", "weighted_score",
        ]
        read_only_fields = ["evaluated_by", "evaluated_at"]

    def get_weighted_score(self, obj):
        """sum(score x weight) / 100 over scored criteria; None until every active criterion is scored."""
        scores = list(obj.scores.select_related("criterion"))
        active = EvaluationCriterion.objects.filter(is_active=True).count()
        if not scores or len(scores) < active:
            return None
        return round(sum(float(s.score) * s.criterion.weight for s in scores) / 100, 2)


class EvaluationCriterionSerializer(serializers.ModelSerializer):
    class Meta:
        model = EvaluationCriterion
        fields = ["id", "name", "description", "weight", "is_active"]


class EvaluationScoreSerializer(serializers.ModelSerializer):
    class Meta:
        model = EvaluationScore
        fields = ["id", "evaluation", "criterion", "score", "remarks"]
        read_only_fields = ["evaluation"]

    def validate_score(self, value):
        if not 0 <= value <= 100:
            raise serializers.ValidationError("Score must be between 0 and 100.")
        return value

    def validate_criterion(self, criterion):
        if not criterion.is_active:
            raise serializers.ValidationError("This criterion is inactive.")
        total = sum(EvaluationCriterion.objects.filter(is_active=True).values_list("weight", flat=True))
        if total != 100:
            raise serializers.ValidationError(f"Active criteria weights total {total}%, not 100% — fix the rubric first.")
        return criterion


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
    indicators = serializers.SerializerMethodField()

    def get_indicators(self, obj):
        from .indicators import compute_indicators  # indicators imports this module's compute helpers
        return compute_indicators(obj)

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


def extension_deadline_passed(project, today=None):
    """True once it's too late to approve an extension (< 1 month before target_end_date)."""
    today = today or timezone.localdate()
    return (project.target_end_date - today).days < EXTENSION_MIN_LEAD_DAYS


class ExtensionRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExtensionRequest
        fields = [
            "id", "project", "current_end_date", "requested_end_date", "justification", "status",
            "submitted_by", "submitted_at", "endorsed_by", "endorsed_at", "decided_by", "decided_at", "remarks",
        ]
        read_only_fields = ["status", "submitted_by", "endorsed_by", "endorsed_at", "decided_by", "decided_at"]

    def validate(self, attrs):
        project = attrs["project"]
        if not project.target_end_date:
            raise serializers.ValidationError({"project": "Project has no target end date to extend."})
        if attrs["requested_end_date"] <= project.target_end_date:
            raise serializers.ValidationError({"requested_end_date": "Must be later than the current target end date."})
        if extension_deadline_passed(project):
            raise serializers.ValidationError("Too late: an extension must be approved at least one month before termination.")
        if project.extension_requests.filter(status__in=("pending", "endorsed")).exists():
            raise serializers.ValidationError("This project already has an extension request in progress.")
        return attrs
