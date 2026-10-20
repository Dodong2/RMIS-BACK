from datetime import date

from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import TruncMonth

from accounts.permissions import scoped_projects, visible_projects
from budget_lib.models import LineItem, LineItemBudget
from budget_lib.serializers import LineItemBudgetSerializer
from compliance.models import (
    AIUseDeclaration,
    ConflictOfInterestDisclosure,
    EthicsReviewReference,
    MisconductCaseReference,
    SimilarityCheckRecord,
)
from decision_support.models import FundingRecommendationRun
from financial_monitoring.models import Disbursement
from forecasting.models import ForecastRun, MonthlyForecast
from monitoring.models import MidtermReport, MonthlyProgressReport, TerminalReport
from outputs.models import CreativeWorkRecord, IPRecord, PublicationRecord
from outputs.serializers import compute_ip_incentive_eligible, compute_publication_incentive
from personnel.models import Task
from research_projects.models import CollegeUnit, Project

from .models import PlanningTarget


class DashboardBudgetRowSerializer(LineItemBudgetSerializer):
    """One current LIB per project for the Dashboard Budget tab, without line items or reviews."""

    class Meta(LineItemBudgetSerializer.Meta):
        fields = ["id", "project", "version_number", "is_current", "status", "total_amount", "exceeds_dry_cap"]


def _user_projects(user, budget=False):
    """Projects the user may see on the Dashboard, or None for every project (client 2026-10-20). Budget figures
    follow scoped_projects (no budget data for Project Staff), everything else visible_projects. No user = no limit."""
    if user is None:
        return None
    return scoped_projects(user) if budget else visible_projects(user)


def _scoped_projects(campus=None, funding_type=None, college=None, user=None, budget=False):
    qs = Project.objects.all()
    allowed = _user_projects(user, budget)
    if allowed is not None:
        qs = qs.filter(pk__in=allowed.values("pk"))
    if campus:
        qs = qs.filter(campus=campus)
    if college:
        qs = qs.filter(college=college)
    if funding_type:
        qs = qs.filter(funding_type=funding_type)
    return qs


def compute_project_dashboard(campus=None, funding_type=None, college=None, user=None):
    projects = _scoped_projects(campus, funding_type, college, user=user)
    return {
        "total_projects": projects.count(),
        "by_status": dict(projects.values_list("status").annotate(count=Count("id"))),
        "by_funding_type": dict(projects.values_list("funding_type").annotate(count=Count("id"))),
        "by_campus": dict(projects.exclude(campus="").values_list("campus").annotate(count=Count("id"))),
    }


def compute_budget_dashboard(campus=None, college=None, user=None):
    # Client 2026-10-20: Project Staff and Project Leaders see the budget of the projects they are involved in (same
    # list as their Projects count). Dashboard only; the Budget page still follows Clarification Q12.
    involved_only = user is not None and user.role is not None and user.role.code in ("project_staff", "project_leader")
    projects = _scoped_projects(campus, college=college, user=user, budget=not involved_only)
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
        "budgets": DashboardBudgetRowSerializer(
            current_budgets.select_related("project").order_by("project__project_code"), many=True,
        ).data,
    }


def compute_compliance_dashboard(campus=None, college=None, user=None):
    ethics = EthicsReviewReference.objects.all()
    similarity = SimilarityCheckRecord.objects.all()
    ai_declarations = AIUseDeclaration.objects.all()
    coi = ConflictOfInterestDisclosure.objects.all()
    misconduct = MisconductCaseReference.objects.all()
    if campus or college or _user_projects(user) is not None:
        projects = _scoped_projects(campus, college=college, user=user)
        ethics, similarity, ai_declarations, coi, misconduct = (
            qs.filter(project__in=projects) for qs in (ethics, similarity, ai_declarations, coi, misconduct)
        )
    return {
        "ethics_reviews_by_status": dict(ethics.values_list("status").annotate(count=Count("id"))),
        "similarity_checks": {
            "total": similarity.count(),
            "within_threshold": similarity.filter(is_within_threshold=True).count(),
            "over_threshold": similarity.filter(is_within_threshold=False).count(),
        },
        "ai_use_declarations": ai_declarations.count(),
        "coi_disclosures_by_status": dict(coi.values_list("status").annotate(count=Count("id"))),
        "misconduct_cases_by_status": dict(misconduct.values_list("status").annotate(count=Count("id"))),
    }


def compute_output_dashboard(year=None, campus=None, college=None, user=None):
    pubs = PublicationRecord.objects.all()
    ip_records = IPRecord.objects.all()
    creative_works = CreativeWorkRecord.objects.all()
    if campus or college or _user_projects(user) is not None:
        projects = _scoped_projects(campus, college=college, user=user)
        pubs = pubs.filter(project__in=projects)
        ip_records = ip_records.filter(project__in=projects)
        creative_works = creative_works.filter(project__in=projects)
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


def compute_portfolio_dashboard(campus=None, college=None):
    """Analytics > Portfolio (client request 2026-10-13): project counts by research priority area, SDG and college.
    Counts only, over every project, so roles whose project list is scoped (Program Leader) still see the whole
    university portfolio."""
    projects = _scoped_projects(campus, college=college)
    priority_labels = dict(Project.PRIORITY_AREA_CHOICES)
    by_priority_area = {
        priority_labels.get(code, "Unspecified"): count
        for code, count in projects.values_list("research_priority_area").annotate(count=Count("id"))
    }
    by_sdg = {}
    for sdgs in projects.values_list("sdgs", flat=True):
        for sdg in sdgs or []:
            by_sdg[sdg] = by_sdg.get(sdg, 0) + 1
    colleges = {}
    for row in projects.exclude(college="").values("campus", "college", "status").annotate(count=Count("id")):
        code, _, title = row["college"].partition(CollegeUnit.SEPARATOR)
        entry = colleges.setdefault(
            (row["campus"], row["college"]),
            {"college": row["college"], "code": code, "title": title or code, "campus": row["campus"], "total": 0, "by_status": {}},
        )
        entry["total"] += row["count"]
        entry["by_status"][row["status"]] = row["count"]
    return {
        "total_projects": projects.count(),
        "by_priority_area": by_priority_area,
        "by_sdg": by_sdg,
        "by_college": sorted(colleges.values(), key=lambda c: (c["campus"], c["code"])),
    }


RANKING_WEIGHTS = {"progress": 0.4, "utilization": 0.3, "completion": 0.2, "outputs": 0.1}


def _performance_score(rows):
    """Prototype formula (client 2026-10-14, provisional until the client confirms): 0.4 average physical progress
    + 0.3 budget utilization + 0.2 completion rate + 0.1 min(100, outputs x 10). A project with no milestones counts
    as 0% progress; utilization is the group's total disbursed over its total approved budget."""
    count = len(rows)
    avg_progress = round(sum(r["physical_pct"] or 0 for r in rows) / count)
    approved = sum(r["approved"] for r in rows)
    actual = sum(r["actual"] for r in rows)
    utilization = round(actual / approved * 100) if approved else 0
    completed = sum(1 for r in rows if r["status"] == "completed")
    completion = round(completed / count * 100)
    outputs = sum(r["outputs"] for r in rows)
    score = round(
        RANKING_WEIGHTS["progress"] * avg_progress + RANKING_WEIGHTS["utilization"] * utilization
        + RANKING_WEIGHTS["completion"] * completion + RANKING_WEIGHTS["outputs"] * min(100, outputs * 10)
    )
    return {
        "projects": count, "avg_progress": avg_progress, "utilization": utilization, "completed": completed,
        "outputs": outputs, "score": score,
    }


def _ranking(rows, key, describe):
    groups = {}
    for row in rows:
        k = key(row)
        if k:
            groups.setdefault(k, []).append(row)
    ranked = [describe(group[0]) | _performance_score(group) for group in groups.values()]
    return sorted(ranked, key=lambda r: -r["score"])


def _latest_12_months(disbursements):
    """Totals for the 12 months ending at the latest disbursement month (the prototype's "Latest 12 Months")."""
    latest = disbursements.order_by("-disbursed_on").values_list("disbursed_on", flat=True).first()
    if latest is None:
        return []
    months = []
    year, month = latest.year, latest.month
    for _ in range(12):
        months.append((year, month))
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    months.reverse()
    totals = {
        (row["month"].year, row["month"].month): row
        for row in disbursements.filter(disbursed_on__gte=date(*months[0], 1))
        .annotate(month=TruncMonth("disbursed_on")).values("month")
        .annotate(total=Sum("amount"), count=Count("id"))
    }
    return [
        {
            "month": f"{y}-{m:02d}",
            "total": float(totals[(y, m)]["total"]) if (y, m) in totals else 0.0,
            "count": totals[(y, m)]["count"] if (y, m) in totals else 0,
        }
        for y, m in months
    ]


def compute_performance_dashboard(campus=None, college=None):
    """Analytics per-project progress rows plus College, Campus and Project Leader performance rankings
    (client 2026-10-14, important.png)."""
    projects = (
        _scoped_projects(campus, college=college)
        .select_related("lead")
        .annotate(
            milestones_total=Count("milestones", distinct=True),
            milestones_done=Count("milestones", filter=Q(milestones__status="done"), distinct=True),
            publication_count=Count("publications", distinct=True),
            ip_count=Count("ip_records", distinct=True),
            creative_count=Count("creative_works", distinct=True),
            team_count=Count("team_members", distinct=True),
        )
        .order_by("project_code")
    )
    current_budgets = LineItemBudget.objects.filter(project__in=projects, is_current=True)
    approved_by_project = dict(
        LineItem.objects.filter(budget__in=current_budgets).values_list("budget__project").annotate(total=Sum("amount"))
    )
    actual_by_project = dict(
        Disbursement.objects.filter(line_item__budget__in=current_budgets)
        .values_list("line_item__budget__project").annotate(total=Sum("amount"))
    )
    priority_labels = dict(Project.PRIORITY_AREA_CHOICES)
    rows = []
    for p in projects:
        approved = float(approved_by_project.get(p.pk) or 0)
        actual = float(actual_by_project.get(p.pk) or 0)
        code, _, title = p.college.partition(CollegeUnit.SEPARATOR)
        rows.append({
            "project": p.pk, "project_code": p.project_code, "title": p.title,
            "priority_area": priority_labels.get(p.research_priority_area, ""), "status": p.status,
            "funding_type": p.funding_type, "team_members": p.team_count,
            "campus": p.campus, "college": p.college, "college_code": code, "college_title": title or code,
            "leader_id": p.lead_id, "leader": p.lead.display_name, "leader_position": p.lead.position,
            "leader_office": p.lead.office,
            "physical_pct": round(p.milestones_done / p.milestones_total * 100, 2) if p.milestones_total else None,
            "financial_pct": round(actual / approved * 100, 2) if approved else None,
            "milestones_done": p.milestones_done, "milestones_total": p.milestones_total,
            "outputs": p.publication_count + p.ip_count + p.creative_count,
            "approved": approved, "actual": actual,
        })
    # Overview "Budget Allocation by Funding Agency" (prototype; Carl 2026-10-14). Projects carry no agency
    # field, so this is the current LIB's line items summed per funding source.
    by_agency = (
        LineItem.objects.filter(budget__in=current_budgets).values_list("funding_source").annotate(total=Sum("amount"))
    )
    agency_totals = {}
    for source, total in by_agency:
        agency = source.strip() or "Unspecified"
        agency_totals[agency] = agency_totals.get(agency, 0.0) + float(total)
    return {
        "weights": RANKING_WEIGHTS,
        "projects": rows,
        "budget_by_funding_agency": [
            {"agency": a, "total": t} for a, t in sorted(agency_totals.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "monthly_disbursements": _latest_12_months(
            Disbursement.objects.filter(line_item__budget__in=current_budgets)
        ),
        "college_ranking": _ranking(
            rows, lambda r: r["college"] and (r["campus"], r["college"]),
            lambda r: {"campus": r["campus"], "college": r["college"], "code": r["college_code"], "title": r["college_title"]},
        ),
        "campus_ranking": _ranking(rows, lambda r: r["campus"], lambda r: {"campus": r["campus"]}),
        "leader_ranking": _ranking(
            rows, lambda r: r["leader_id"],
            lambda r: {
                "leader_id": r["leader_id"], "leader": r["leader"], "position": r["leader_position"],
                "office": r["leader_office"],
            },
        ),
    }


def compute_rde_thrust_alignment(campus=None, college=None, user=None):
    projects = _scoped_projects(campus, college=college, user=user)
    return {
        "by_thrust": dict(
            projects.exclude(rde_thrust="").values_list("rde_thrust").annotate(count=Count("id"))
        ),
        "unaligned_count": projects.filter(rde_thrust="").count(),
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


def compute_forecasting_dashboard(campus=None, funding_type=None, college=None, user=None):
    """Forecasting Analytics Dashboard (Objective 5c): latest successful ARIMA run per project."""
    projects = _scoped_projects(campus, funding_type, college, user=user, budget=True)
    runs = []
    for project in projects:
        run = ForecastRun.objects.filter(project=project, status="success").order_by("-run_at").first()
        if run:
            runs.append(run)
    monthly = {}
    for period, amount in MonthlyForecast.objects.filter(forecast_run__in=runs).values_list("period", "predicted_amount"):
        key = f"{period:%Y-%m}"
        monthly[key] = monthly.get(key, 0) + float(amount)
    accuracy = ForecastRun.objects.filter(pk__in=[r.pk for r in runs]).aggregate(
        avg_mae=Avg("mae"), avg_rmse=Avg("rmse"), avg_mape=Avg("mape"),
    )
    return {
        "projects_in_scope": projects.count(),
        "projects_forecasted": len(runs),
        "overrun_risk_count": sum(1 for r in runs if r.is_overrun_risk),
        "accuracy": accuracy,
        "monthly_forecast": [{"month": m, "predicted": monthly[m]} for m in sorted(monthly)],
        "projects": [
            {
                "project": r.project_id, "project_code": r.project.project_code, "title": r.project.title,
                "run": r.id, "run_at": r.run_at,
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


def compute_task_dashboard(project_id=None, user=None):
    """Open/overdue/done task counts per project (feeds the Compliance & Activity Dashboard, Objective 5a)."""
    tasks = Task.objects.all()
    allowed = _user_projects(user)
    if allowed is not None:
        tasks = tasks.filter(project__in=allowed.values("pk"))
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
