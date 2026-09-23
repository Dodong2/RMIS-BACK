from datetime import timedelta

from django.utils import timezone

from forecasting.models import ForecastRun
from monitoring.serializers import compute_budget_used_pct, compute_deliverables_pct, compute_escalation_status
from personnel.models import PersonnelChange
from research_projects.models import Project

BUDGET_UNDERUTILIZATION_THRESHOLD = 70
PERSONNEL_CHANGE_WINDOW_MONTHS = 12
PERSONNEL_CHANGE_THRESHOLD = 2


def _non_submission_warning(project):
    escalation = compute_escalation_status(project)
    return {
        "flagged": escalation["status"] in ("notify_dean_riuh", "terminate_recommended"),
        "status": escalation["status"],
        "months_since_last_report": escalation["months_since_last_report"],
    }


def _budget_underutilization(project):
    pct = compute_budget_used_pct(project)
    return {
        "flagged": pct is not None and pct < BUDGET_UNDERUTILIZATION_THRESHOLD,
        "budget_used_pct": pct,
    }


def _deliverable_slippage(project):
    today = timezone.localdate()
    overdue = project.milestones.filter(target_date__lt=today).exclude(status="done")
    return {
        "flagged": overdue.exists(),
        "overdue_count": overdue.count(),
        "deliverables_pct": compute_deliverables_pct(project),
    }


def _personnel_change_frequency(project):
    since = timezone.localdate() - timedelta(days=PERSONNEL_CHANGE_WINDOW_MONTHS * 30)
    count = PersonnelChange.objects.filter(project=project, created_at__date__gte=since).count()
    return {
        "flagged": count >= PERSONNEL_CHANGE_THRESHOLD,
        "changes_in_window": count,
        "window_months": PERSONNEL_CHANGE_WINDOW_MONTHS,
    }


def _forecast_overrun(project):
    latest = ForecastRun.objects.filter(project=project, status="success").order_by("-run_at").first()
    if latest is None:
        return {"flagged": False, "has_forecast": False, "is_overrun_risk": None}
    return {"flagged": latest.is_overrun_risk, "has_forecast": True, "is_overrun_risk": latest.is_overrun_risk}


def compute_project_risk(project):
    """Live-computed, not stored (no Celery/cron in this project — same
    convention as Module 9's compute_escalation_status). Five flags per the
    docx's key-feature list, each reusing an existing compute function or
    query from the module that actually owns that data."""
    flags = {
        "non_submission_warning": _non_submission_warning(project),
        "budget_underutilization": _budget_underutilization(project),
        "deliverable_slippage": _deliverable_slippage(project),
        "personnel_change_frequency": _personnel_change_frequency(project),
        "forecast_overrun": _forecast_overrun(project),
    }
    flagged_count = sum(1 for f in flags.values() if f["flagged"])
    if flagged_count >= 3:
        risk_level = "high"
    elif flagged_count >= 1:
        risk_level = "medium"
    else:
        risk_level = "low"
    return {
        "project": project.id,
        "project_code": project.project_code,
        "risk_level": risk_level,
        "flagged_count": flagged_count,
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
    by_level = {"low": 0, "medium": 0, "high": 0}
    for r in results:
        by_level[r["risk_level"]] += 1
    flagged_projects = [r for r in results if r["flagged_count"] > 0]
    flagged_projects.sort(key=lambda r: r["flagged_count"], reverse=True)

    return {
        "total_projects": len(results),
        "by_risk_level": by_level,
        "flagged_projects": flagged_projects,
    }
