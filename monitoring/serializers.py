from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from budget_lib.models import LineItem
from financial_monitoring.models import Disbursement

from research_projects.workflow import WorkAfterReviewMixin
from . import quarterly
from .models import (
    EvaluationCriterion, EvaluationScore, ExtensionRequest, MidtermReport, MonthlyProgressReport, ProjectEvaluation,
    QuarterlyProgressReport, RenewalApplication, TerminalReport,
)

# Seed source for the permission table (accounts/permission_seed.py); gates use permission codes.
REPORT_ROLES = ["system_admin", "riuh", "project_leader", "study_leader", "project_staff"]
TERMINAL_CERTIFY_ROLES = ["system_admin", "riuh"]
EVALUATION_PANEL_ROLES = ["system_admin", "vprei", "drd", "crc_chair"]
RENEWAL_DECISION_ROLES = ["system_admin", "riuh", "drd", "vprei"]
EXTENSION_REQUEST_ROLES = ["system_admin", "program_leader", "project_leader"]
EXTENSION_ENDORSE_ROLES = ["system_admin", "drd", "crc_chair"]  # DRD, or the campus coordinator
EXTENSION_APPROVE_ROLES = ["system_admin", "university_admin"]  # University President
# R&D Quarterly Progress Reports (2026-10-14; Structure Module 9 + Clarification 1a/1b/1c). No system_admin: the
# Project Leader prepares, RIUH / CRC Chair review and endorse, DRD / VPREI review and give final approval.
QUARTERLY_PREPARE_ROLES = ["project_leader"]
QUARTERLY_REVIEW_ROLES = ["riuh", "crc_chair", "drd", "vprei"]
QUARTERLY_APPROVE_ROLES = ["drd", "vprei"]
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


class MonthlyProgressReportSerializer(WorkAfterReviewMixin, serializers.ModelSerializer):
    class Meta:
        model = MonthlyProgressReport
        fields = ["id", "project", "period", "narrative", "document", "submitted_by", "submitted_at"]
        read_only_fields = ["submitted_by"]


class MidtermReportSerializer(WorkAfterReviewMixin, serializers.ModelSerializer):
    class Meta:
        model = MidtermReport
        fields = [
            "id", "project", "project_year", "narrative", "expenditure_summary", "objective_accomplishments",
            "document", "submitted_by", "submitted_at",
        ]
        read_only_fields = ["submitted_by"]

    def validate_objective_accomplishments(self, rows):
        """SF-017 rows: a non-blank objective and Q1-Q4 % from 0 to 100 (blank = not yet reported)."""
        if not isinstance(rows, list):
            raise serializers.ValidationError("Must be a list of objectives.")
        cleaned = []
        for i, row in enumerate(rows, start=1):
            if not isinstance(row, dict) or not str(row.get("objective") or "").strip():
                raise serializers.ValidationError(f"Objective {i}: the objective text is required.")
            item = {"objective": str(row["objective"]).strip()}
            for q in ("q1", "q2", "q3", "q4"):
                value = row.get(q)
                if value in (None, ""):
                    item[q] = None
                    continue
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    raise serializers.ValidationError(f"Objective {i}: {q.upper()} must be a number.")
                if not 0 <= value <= 100:
                    raise serializers.ValidationError(f"Objective {i}: {q.upper()} must be from 0 to 100.")
                item[q] = value
            cleaned.append(item)
        return cleaned


class TerminalReportSerializer(WorkAfterReviewMixin, serializers.ModelSerializer):
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


class RenewalApplicationSerializer(WorkAfterReviewMixin, serializers.ModelSerializer):
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


class ExtensionRequestSerializer(WorkAfterReviewMixin, serializers.ModelSerializer):
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


class QuarterlyAccomplishmentSerializer(serializers.Serializer):
    objective = serializers.CharField(required=False, allow_blank=True, default="")
    activity = serializers.CharField(required=False, allow_blank=True, default="")
    target = serializers.CharField(required=False, allow_blank=True, default="")
    actual = serializers.CharField(required=False, allow_blank=True, default="")
    cumulative = serializers.CharField(required=False, allow_blank=True, default="")
    target_date = serializers.CharField(required=False, allow_blank=True, default="")
    actual_date = serializers.CharField(required=False, allow_blank=True, default="")
    completion_pct = serializers.IntegerField(required=False, min_value=0, max_value=100, default=0)
    variance = serializers.CharField(required=False, allow_blank=True, default="")
    remarks = serializers.CharField(required=False, allow_blank=True, default="")


class QuarterlyIssueSerializer(serializers.Serializer):
    issue = serializers.CharField(required=False, allow_blank=True, default="")
    corrective_action = serializers.CharField(required=False, allow_blank=True, default="")
    recommendation = serializers.CharField(required=False, allow_blank=True, default="")
    responsible = serializers.CharField(required=False, allow_blank=True, default="")
    target_resolution_date = serializers.CharField(required=False, allow_blank=True, default="")


class QuarterlyProgressReportSerializer(WorkAfterReviewMixin, serializers.ModelSerializer):
    accomplishments = QuarterlyAccomplishmentSerializer(many=True, required=False)
    issues = QuarterlyIssueSerializer(many=True, required=False)
    period = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()
    project_info = serializers.SerializerMethodField()
    evidence_files = serializers.SerializerMethodField()
    events = serializers.SerializerMethodField()
    review_history = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()

    class Meta:
        model = QuarterlyProgressReport
        fields = [
            "id", "project", "year", "quarter", "period", "status", "version", "is_overdue", "project_info",
            "accomplishments", "issues", "financial_snapshot", "evidence", "evidence_files", "recommendations",
            "created_by", "created_at", "updated_at", "submitted_at", "approved_by", "approved_by_name", "approved_at",
            "events", "review_history",
        ]
        read_only_fields = [
            "status", "version", "financial_snapshot", "created_by", "created_at", "updated_at", "submitted_at",
            "approved_by", "approved_at",
        ]

    def get_period(self, obj):
        return f"Q{obj.quarter} {obj.year}"

    def get_is_overdue(self, obj):
        return quarterly.is_overdue(obj)

    def get_project_info(self, obj):
        p = obj.project
        return {
            "code": p.project_code, "title": p.title, "leader": p.lead.display_name, "leader_id": p.lead_id,
            "campus": p.campus, "college": p.college, "funding_agency": quarterly.funding_agency(p),
            "start_date": p.start_date, "end_date": p.target_end_date, "objectives": quarterly.objective_list(p),
        }

    def get_evidence_files(self, obj):
        return [{"id": d.id, "file_name": d.file_name} for d in obj.evidence.all()]

    def _events(self, obj):
        return [
            {"action": e.action, "from_status": e.from_status, "to_status": e.to_status, "remarks": e.remarks,
             "actor": e.actor.display_name, "at": e.at}
            for e in obj.events.select_related("actor")
        ]

    def get_events(self, obj):
        return self._events(obj)

    def get_review_history(self, obj):
        return [e for e in self._events(obj)
                if e["action"] == "status_transition" and e["remarks"] and e["to_status"] != "submitted"]

    def get_approved_by_name(self, obj):
        return obj.approved_by.display_name if obj.approved_by else ""

    def validate_quarter(self, value):
        if not 1 <= value <= 4:
            raise serializers.ValidationError("Quarter must be 1 to 4.")
        return value

    def validate(self, attrs):
        if self.instance is None:
            project, year, quarter = attrs["project"], attrs["year"], attrs["quarter"]
            if quarterly.quarter_range(year, quarter)[0] > quarterly.today():
                raise serializers.ValidationError("That quarter has not started yet.")
            user = self.context["request"].user
            from accounts.permissions import acting_for
            if project.lead_id not in (user.pk, *acting_for(user)):
                raise serializers.ValidationError({"project": "You can only create reports for projects you lead."})
            if QuarterlyProgressReport.objects.filter(project=project, year=year, quarter=quarter).exists():
                raise serializers.ValidationError(f"This project already has a Q{quarter} {year} report.")
        else:
            for field in ("project", "year", "quarter"):
                if field in attrs and attrs[field] != getattr(self.instance, field):
                    raise serializers.ValidationError({field: "Can't be changed after the report is created."})
        project = attrs.get("project") or self.instance.project
        for doc in attrs.get("evidence", []):
            if doc.project_id != project.pk:
                raise serializers.ValidationError({"evidence": f"'{doc.file_name}' belongs to another project."})
        return attrs
