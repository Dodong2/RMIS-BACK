from datetime import timedelta

from django.utils import timezone

from financial_monitoring.models import PROCUREMENT_DELAY_DAYS, ProcurementRequest
from forecasting.models import ForecastRun
from monitoring.serializers import compute_budget_used_pct, compute_deliverables_pct, compute_escalation_status
from personnel.models import PersonnelChange
from research_projects.models import Project

BUDGET_UNDERUTILIZATION_THRESHOLD = 70
DELIVERABLES_THRESHOLD = 70
PERSONNEL_CHANGE_WINDOW_MONTHS = 12
PERSONNEL_CHANGE_THRESHOLD = 2
# The client places the 70%/70% checks "malapit sa renewal" — no day count given, engineering default.
RENEWAL_WINDOW_DAYS = 90

# 5x5 Likelihood x Impact bands (client clarification Q7, 2026-09-24), with the action each level triggers.
RISK_BANDS = (
    (4, "low", "Monitor only"),
    (9, "medium", "Reminder to the Project Leader"),
    (16, "high", "Notice to RIUH and CRC Chairperson"),
    (25, "critical", "Escalation to VP / DRD"),
)


def risk_band(score):
    """Map a 0-25 score to (level, action). 0 = nothing flagged = low."""
    for upper, level, action in RISK_BANDS:
        if score <= upper:
            return level, action
    return RISK_BANDS[-1][1], RISK_BANDS[-1][2]


def _scored(flagged, likelihood, impact, **details):
    score = likelihood * impact if flagged else 0
    return {"flagged": flagged, "likelihood": likelihood if flagged else 0,
            "impact": impact if flagged else 0, "score": score, **details}


def _near_renewal(project):
    """Within RENEWAL_WINDOW_DAYS of the target end date (or already past it)."""
    if not project.target_end_date:
        return False
    return (project.target_end_date - timezone.localdate()).days <= RENEWAL_WINDOW_DAYS


def _non_submission_warning(project):
    # Client Q7 mapping: 2 months = 3x3 (Medium), 3 months = 4x4 (High, Manual notice to Dean/RIUH),
    # 6+ months = 5x5 (Critical, Manual termination).
    escalation = compute_escalation_status(project)
    months = escalation["months_since_last_report"]
    if months is not None and months >= 6:
        likelihood, impact = 5, 5
    elif months is not None and months >= 3:
        likelihood, impact = 4, 4
    else:
        likelihood, impact = 3, 3
    return _scored(months is not None and months >= 2, likelihood, impact,
                   status=escalation["status"], months_since_last_report=months)


def _budget_underutilization(project):
    # Client Q7: < 70% utilization near renewal = 4x4 (High).
    pct = compute_budget_used_pct(project)
    near = _near_renewal(project)
    return _scored(pct is not None and pct < BUDGET_UNDERUTILIZATION_THRESHOLD and near, 4, 4,
                   budget_used_pct=pct, near_renewal=near)


def _deliverable_shortfall(project):
    # Client Q7: deliverables < 70% of the work plan = 4x4 (High); checked near renewal like the budget rule.
    pct = compute_deliverables_pct(project)
    near = _near_renewal(project)
    return _scored(pct is not None and pct < DELIVERABLES_THRESHOLD and near, 4, 4,
                   deliverables_pct=pct, near_renewal=near)


def _deliverable_slippage(project):
    # Not in the client's score table: 3x3 (Medium) is an engineering default.
    today = timezone.localdate()
    overdue = project.milestones.filter(target_date__lt=today).exclude(status="done")
    count = overdue.count()
    return _scored(count > 0, 3, 3, overdue_count=count)


def _personnel_change_frequency(project):
    # Not in the client's score table: 3x2 (Medium) is an engineering default.
    since = timezone.localdate() - timedelta(days=PERSONNEL_CHANGE_WINDOW_MONTHS * 30)
    count = PersonnelChange.objects.filter(project=project, created_at__date__gte=since).count()
    return _scored(count >= PERSONNEL_CHANGE_THRESHOLD, 3, 2,
                   changes_in_window=count, window_months=PERSONNEL_CHANGE_WINDOW_MONTHS)


def _procurement_delay(project):
    # Consultation findings: delayed procurement -> escalation. 3x3 (Medium) is an engineering default.
    cutoff = timezone.now() - timedelta(days=PROCUREMENT_DELAY_DAYS)
    delayed = ProcurementRequest.objects.filter(
        line_item__budget__project=project, status__in=("requested", "processing"), requested_at__lt=cutoff,
    ).count()
    return _scored(delayed > 0, 3, 3, delayed_requests=delayed, delay_days=PROCUREMENT_DELAY_DAYS)


def _forecast_overrun(project):
    # Client Q7: forecast above the adjusted budget = 3x4 (High).
    latest = ForecastRun.objects.filter(project=project, status="success").order_by("-run_at").first()
    if latest is None:
        return _scored(False, 3, 4, has_forecast=False, is_overrun_risk=None)
    return _scored(bool(latest.is_overrun_risk), 3, 4, has_forecast=True, is_overrun_risk=latest.is_overrun_risk)


def compute_project_risk(project):
    """Live-computed, not stored (no Celery/cron in this project — same
    convention as Module 9's compute_escalation_status). Each trigger is scored
    Likelihood x Impact on the client's 5x5 scale; the project's level is its
    highest-scoring trigger or open register risk (worst risk wins, not a sum)."""
    flags = {
        "non_submission_warning": _non_submission_warning(project),
        "budget_underutilization": _budget_underutilization(project),
        "deliverable_shortfall": _deliverable_shortfall(project),
        "deliverable_slippage": _deliverable_slippage(project),
        "personnel_change_frequency": _personnel_change_frequency(project),
        "procurement_delay": _procurement_delay(project),
        "forecast_overrun": _forecast_overrun(project),
    }
    flagged_count = sum(1 for f in flags.values() if f["flagged"])
    register_scores = [r.likelihood * r.impact for r in project.risks.exclude(status="closed")]
    risk_score = max([f["score"] for f in flags.values()] + register_scores)
    risk_level, recommended_action = risk_band(risk_score)
    return {
        "project": project.id,
        "project_code": project.project_code,
        "risk_score": risk_score,
        "risk_level": risk_level,
        "recommended_action": recommended_action,
        "flagged_count": flagged_count,
        "open_register_risks": len(register_scores),
        "flags": flags,
    }


def compute_risk_dashboard(campus=None, funding_type=None):
    """Scoped to active projects only — a completed/archived project isn't
    an early-warning concern anymore."""
    projects = Project.objects.filter(status="active")
    if campus:
        projects = projects.filter(campus=campus)
    if funding_type:
        projects = projects.filter(funding_type=funding_type)

    results = [compute_project_risk(p) for p in projects]
    by_level = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    for r in results:
        by_level[r["risk_level"]] += 1
    flagged_projects = [r for r in results if r["risk_score"] > 0]
    flagged_projects.sort(key=lambda r: (r["risk_score"], r["flagged_count"]), reverse=True)

    return {
        "total_projects": len(results),
        "by_risk_level": by_level,
        "flagged_projects": flagged_projects,
    }
