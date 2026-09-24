from datetime import date

from django.db.models import Avg, Count, Q, Sum

from budget_lib.models import LineItem, LineItemBudget
from compliance.models import (
    AIUseDeclaration,
    ConflictOfInterestDisclosure,
    EthicsReviewReference,
    MisconductCaseReference,
    SimilarityCheckRecord,
)
from decision_support.models import FundingRecommendationRun
from financial_monitoring.models import Disbursement
from forecasting.models import ForecastRun
from monitoring.models import MidtermReport, MonthlyProgressReport, TerminalReport
from outputs.models import CreativeWorkRecord, IPRecord, PublicationRecord
from outputs.serializers import compute_ip_incentive_eligible, compute_publication_incentive
from personnel.models import Task
from research_projects.models import Project

from .models import PlanningTarget


def _scoped_projects(campus=None, funding_type=None):
    qs = Project.objects.all()
    if campus:
        qs = qs.filter(campus=campus)
    if funding_type:
        qs = qs.filter(funding_type=funding_type)
    return qs


def compute_project_dashboard(campus=None, funding_type=None):
    projects = _scoped_projects(campus, funding_type)
    return {
        "total_projects": projects.count(),
        "by_status": dict(projects.values_list("status").annotate(count=Count("id"))),
        "by_funding_type": dict(projects.values_list("funding_type").annotate(count=Count("id"))),
        "by_campus": dict(projects.exclude(campus="").values_list("campus").annotate(count=Count("id"))),
    }


def compute_budget_dashboard(campus=None):
    projects = _scoped_projects(campus)
    current_budgets = LineItemBudget.objects.filter(project__in=projects, is_current=True)
    approved = LineItem.objects.filter(budget__in=current_budgets).aggregate(total=Sum("amount"))["total"] or 0
    actual = (
        Disbursement.objects.filter(line_item__budget__in=current_budgets).aggregate(total=Sum("amount"))["total"] or 0
    )
    utilization_pct = round(float(actual) / float(approved) * 100, 2) if approved else None
    return {
        "project_count": projects.count(),
        "total_approved": approved,
        "total_actual": actual,
        "utilization_pct": utilization_pct,
    }


def compute_compliance_dashboard():
    return {
        "ethics_reviews_by_status": dict(
            EthicsReviewReference.objects.values_list("status").annotate(count=Count("id"))
        ),
        "similarity_checks": {
            "total": SimilarityCheckRecord.objects.count(),
            "within_threshold": SimilarityCheckRecord.objects.filter(is_within_threshold=True).count(),
            "over_threshold": SimilarityCheckRecord.objects.filter(is_within_threshold=False).count(),
        },
        "ai_use_declarations": AIUseDeclaration.objects.count(),
        "coi_disclosures_by_status": dict(
            ConflictOfInterestDisclosure.objects.values_list("status").annotate(count=Count("id"))
        ),
        "misconduct_cases_by_status": dict(
            MisconductCaseReference.objects.values_list("status").annotate(count=Count("id"))
        ),
    }


def compute_output_dashboard(year=None):
    pubs = PublicationRecord.objects.all()
    ip_records = IPRecord.objects.all()
    creative_works = CreativeWorkRecord.objects.all()
    if year:
        pubs = pubs.filter(published_on__year=year)
        ip_records = ip_records.filter(created_at__year=year)
        creative_works = creative_works.filter(date_created__year=year)

    total_estimated_incentive = sum(
        (compute_publication_incentive(p) or 0 for p in pubs), start=0
    )
    ip_incentive_eligible_count = sum(1 for ip in ip_records if compute_ip_incentive_eligible(ip))

    return {
        "publications_by_type": dict(pubs.values_list("publication_type").annotate(count=Count("id"))),
        "ip_records_by_status": dict(ip_records.values_list("status").annotate(count=Count("id"))),
        "creative_works_count": creative_works.count(),
        "total_estimated_publication_incentive": total_estimated_incentive,
        "ip_incentive_eligible_count": ip_incentive_eligible_count,
    }


def compute_rei_thrust_alignment():
    projects = Project.objects.all()
    return {
        "by_thrust": dict(
            projects.exclude(rei_thrust="").values_list("rei_thrust").annotate(count=Count("id"))
        ),
        "unaligned_count": projects.filter(rei_thrust="").count(),
    }


def compute_metric_actual(metric, campus, year):
    if metric == "completed_projects":
        qs = Project.objects.filter(status="completed", target_end_date__year=year)
        if campus:
            qs = qs.filter(campus=campus)
        return qs.count()
    if metric == "publications":
        qs = PublicationRecord.objects.filter(published_on__year=year)
        if campus:
            qs = qs.filter(project__campus=campus)
        return qs.count()
    if metric == "ip_disclosures":
        qs = IPRecord.objects.filter(created_at__year=year)
        if campus:
            qs = qs.filter(project__campus=campus)
        return qs.count()
    if metric == "budget_utilization_pct":
        return compute_budget_dashboard(campus)["utilization_pct"]
    return None


def compute_planning_target_comparison(year=None):
    targets = PlanningTarget.objects.all()
    if year:
        targets = targets.filter(target_year=year)

    results = []
    for target in targets:
        actual = compute_metric_actual(target.metric, target.campus, target.target_year)
        pct_of_target = (
            round(float(actual) / float(target.target_value) * 100, 2)
            if actual is not None and target.target_value
            else None
        )
        results.append(
            {
                "id": target.pk,
                "metric": target.metric,
                "campus": target.campus,
                "target_year": target.target_year,
                "target_value": target.target_value,
                "actual_value": actual,
                "pct_of_target": pct_of_target,
            }
        )
    return results


def appendix_e_export(project_id):
    """Structured data matching Appendix E (Midterm Progress Report). Returns
    JSON shaped like the form's fields — actual PDF/DOCX rendering belongs to
    Module 14 (Reports and Data Export)."""
    reports = MidtermReport.objects.filter(project_id=project_id).order_by("project_year")
    return [
        {
            "project_year": r.project_year,
            "narrative": r.narrative,
            "expenditure_summary": r.expenditure_summary,
            "submitted_by": r.submitted_by_id,
            "submitted_at": r.submitted_at,
        }
        for r in reports
    ]


def appendix_f_export(project_id):
    """Structured data matching Appendix F (Terminal Report)."""
    report = TerminalReport.objects.filter(project_id=project_id).first()
    if not report:
        return None
    return {
        "narrative": report.narrative,
        "submitted_by": report.submitted_by_id,
        "submitted_at": report.submitted_at,
        "is_certified": report.is_certified,
        "certified_by": report.certified_by_id,
        "certified_at": report.certified_at,
    }


def appendix_g_export(campus=None, year=None):
    """Structured data matching Appendix G (R&D Accomplishment Report) —
    the summary RIUH compiles per the Manual's 'Reporting of R&D
    Accomplishments' section. Aggregated from what RMIS already tracks;
    does not model plantilla positions/academic rank (Planning Office's own
    methodology, outside RMIS's scope)."""
    projects = _scoped_projects(campus)
    pubs = PublicationRecord.objects.filter(project__in=projects)
    ip_records = IPRecord.objects.filter(project__in=projects)
    creative_works = CreativeWorkRecord.objects.filter(project__in=projects)
    monthly_reports = MonthlyProgressReport.objects.filter(project__in=projects)
    if year:
        pubs = pubs.filter(published_on__year=year)
        ip_records = ip_records.filter(created_at__year=year)
        creative_works = creative_works.filter(date_created__year=year)
        monthly_reports = monthly_reports.filter(period__year=year)

    return {
        "campus": campus or "institution-wide",
        "year": year,
        "completed_projects": projects.filter(status="completed").count(),
        "publications": pubs.count(),
        "ip_records": ip_records.count(),
        "creative_works": creative_works.count(),
        "monthly_reports_submitted": monthly_reports.count(),
    }


def compute_forecasting_dashboard(campus=None, funding_type=None):
    """Forecasting Analytics Dashboard (Objective 5c): latest successful ARIMA run per project."""
    projects = _scoped_projects(campus, funding_type)
    runs = []
    for project in projects:
        run = ForecastRun.objects.filter(project=project, status="success").order_by("-run_at").first()
        if run:
            runs.append(run)
    accuracy = ForecastRun.objects.filter(pk__in=[r.pk for r in runs]).aggregate(
        avg_mae=Avg("mae"), avg_rmse=Avg("rmse"), avg_mape=Avg("mape"),
    )
    return {
        "projects_in_scope": projects.count(),
        "projects_forecasted": len(runs),
        "overrun_risk_count": sum(1 for r in runs if r.is_overrun_risk),
        "accuracy": accuracy,
        "projects": [
            {
                "project": r.project_id, "project_code": r.project.project_code, "run": r.id, "run_at": r.run_at,
                "approved_budget_total": r.approved_budget_total, "actual_to_date": r.actual_to_date,
                "projected_total_at_horizon": r.projected_total_at_horizon, "is_overrun_risk": r.is_overrun_risk,
                "mae": r.mae, "rmse": r.rmse, "mape": r.mape,
            }
            for r in sorted(runs, key=lambda r: (not r.is_overrun_risk, r.project.project_code))
        ],
    }


def compute_funding_allocation_dashboard(run_id=None):
    """Funding Allocation Decision Dashboard (Objective 5d): a WSM run's ranking next to the decisions taken."""
    runs = FundingRecommendationRun.objects.order_by("-created_at")
    run = runs.filter(pk=run_id).first() if run_id else runs.first()
    if run is None:
        return None
    decisions = {d.project_id: d for d in run.decisions.all()}
    ranking = []
    for score in run.scores.select_related("project").order_by("rank"):
        decision = decisions.get(score.project_id)
        ranking.append({
            "rank": score.rank, "project": score.project_id, "project_code": score.project.project_code,
            "title": score.project.title, "composite_score": score.composite_score,
            "decision": decision.decision if decision else None,
            "indicative_amount": decision.indicative_amount if decision else None,
        })
    return {
        "run": run.id, "label": run.label, "created_at": run.created_at, "ahp_run": run.ahp_run_id,
        "ranking": ranking,
        "decision_summary": {
            choice: sum(1 for d in decisions.values() if d.decision == choice) for choice in ("fund", "defer", "decline")
        } | {"undecided": len(ranking) - len(decisions)},
        "total_indicative_amount": sum((d.indicative_amount or 0) for d in decisions.values() if d.decision == "fund"),
    }


def compute_task_dashboard(project_id=None):
    """Open/overdue/done task counts per project (feeds the Compliance & Activity Dashboard, Objective 5a)."""
    tasks = Task.objects.all()
    if project_id:
        tasks = tasks.filter(project_id=project_id)
    rows = (
        tasks.values("project", "project__project_code")
        .annotate(
            open=Count("id", filter=~Q(status="done")),
            overdue=Count("id", filter=Q(due_date__lt=date.today()) & ~Q(status="done")),
            done=Count("id", filter=Q(status="done")),
        )
        .order_by("-overdue", "project__project_code")
    )
    return [
        {"project": r["project"], "project_code": r["project__project_code"], "open": r["open"], "overdue": r["overdue"], "done": r["done"]}
        for r in rows
    ]
