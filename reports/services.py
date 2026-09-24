from datetime import date

from django.db.models import Count, Q

from accounts.permissions import scoped_projects
from compliance.models import (
    AIUseDeclaration, ConflictOfInterestDisclosure, EthicsReviewReference, MisconductCaseReference, SimilarityCheckRecord,
)
from financial_monitoring.models import ProcurementRequest
from financial_monitoring.serializers import line_item_balance
from outputs.models import CreativeWorkRecord, IPRecord, PublicationRecord
from outputs.serializers import ExpectedOutputSerializer
from personnel.models import ProjectAssignment, Task
from research_projects.models import Project

PROJECT_LIST_FIELDS = [
    "project_code", "title", "funding_type", "status", "campus",
    "rei_thrust", "start_date", "target_end_date", "total_cost",
]


def project_list_report(campus=None, funding_type=None, status=None, rei_thrust=None, year=None):
    """The docx's 'custom filtered report builder', scoped to a fixed set of
    Project fields rather than a fully generic query/column builder — a
    generic report designer is out of scope for this capstone; this covers
    the filters/fields RIUH/DRD would realistically ask for."""
    qs = Project.objects.all().select_related("lead")
    if campus:
        qs = qs.filter(campus=campus)
    if funding_type:
        qs = qs.filter(funding_type=funding_type)
    if status:
        qs = qs.filter(status=status)
    if rei_thrust:
        qs = qs.filter(rei_thrust=rei_thrust)
    if year:
        qs = qs.filter(start_date__year=year)

    rows = []
    for p in qs:
        rows.append(
            {
                "project_code": p.project_code,
                "title": p.title,
                "funding_type": p.funding_type,
                "status": p.status,
                "campus": p.campus,
                "rei_thrust": p.rei_thrust,
                "lead": p.lead.email if p.lead else "",
                "start_date": p.start_date,
                "target_end_date": p.target_end_date,
                "total_cost": p.total_cost,
            }
        )
    return rows


def _projects(campus=None, funding_type=None):
    qs = Project.objects.all().order_by("project_code")
    if campus:
        qs = qs.filter(campus=campus)
    if funding_type:
        qs = qs.filter(funding_type=funding_type)
    return qs


def financial_report(user, campus=None, funding_type=None):
    """Approved/Adjusted/Actual per project (current LIB) plus procurement pipeline counts.
    Honors the same budget row-level scope as the budget endpoints."""
    projects = _projects(campus, funding_type)
    scope = scoped_projects(user)
    if scope is not None:
        projects = projects.filter(pk__in=scope)
    rows = []
    for p in projects:
        budget = p.budgets.filter(is_current=True).first()
        totals = {"approved": 0, "adjusted": 0, "actual": 0, "available": 0}
        if budget:
            for item in budget.line_items.all():
                for key, value in line_item_balance(item).items():
                    totals[key] += value
        procurement = ProcurementRequest.objects.filter(line_item__budget__project=p).aggregate(
            requested=Count("id", filter=Q(status="requested")),
            processing=Count("id", filter=Q(status="processing")),
            released=Count("id", filter=Q(status="released")),
        )
        rows.append({
            "project_code": p.project_code, "title": p.title, "funding_type": p.funding_type, "campus": p.campus,
            "budget_status": budget.status if budget else "none", **totals,
            "utilization_pct": round(float(totals["actual"]) / float(totals["adjusted"]) * 100, 2) if totals["adjusted"] else "",
            "procurement_requested": procurement["requested"], "procurement_processing": procurement["processing"],
            "procurement_released": procurement["released"],
        })
    return rows


def compliance_report(campus=None, funding_type=None):
    rows = []
    for p in _projects(campus, funding_type):
        similarity = SimilarityCheckRecord.objects.filter(project=p)
        reviews = EthicsReviewReference.objects.filter(project=p)
        ai = AIUseDeclaration.objects.filter(project=p)
        coi = ConflictOfInterestDisclosure.objects.filter(project=p)
        rows.append({
            "project_code": p.project_code, "title": p.title, "campus": p.campus,
            "review_references": reviews.count(), "reviews_approved": reviews.filter(status="approved").count(),
            "similarity_checks": similarity.count(), "similarity_over_threshold": similarity.filter(is_within_threshold=False).count(),
            "ai_declarations": ai.count(), "coi_disclosures": coi.count(),
            "records_verified_by_riuh": sum(qs.filter(verified_at__isnull=False).count() for qs in (similarity, reviews, ai, coi)),
            "misconduct_cases": MisconductCaseReference.objects.filter(project=p).count(),
        })
    return rows


def personnel_report(campus=None, funding_type=None):
    """One row per person per project: leaders and assigned staff, with their task load."""
    today = date.today()
    rows = []
    for p in _projects(campus, funding_type).select_related("lead"):
        people = [(p.lead, "Project Leader", p.lead.office)]
        people += [(s.lead, "Study Leader", s.lead.office) for s in p.studies.select_related("lead")]
        assignments = ProjectAssignment.objects.filter(Q(project=p) | Q(study__project=p), end_date__isnull=True).select_related("user")
        people += [(a.user, a.role_label or "Project Staff", a.department) for a in assignments]
        for user, role, department in people:
            tasks = Task.objects.filter(project=p, assignee=user)
            rows.append({
                "project_code": p.project_code, "person": user.email, "role": role, "department": department,
                "tasks_open": tasks.exclude(status="done").count(),
                "tasks_overdue": tasks.filter(due_date__lt=today).exclude(status="done").count(),
                "tasks_done": tasks.filter(status="done").count(),
            })
    return rows


def outputs_report(campus=None, funding_type=None):
    rows = []
    for p in _projects(campus, funding_type):
        expected = ExpectedOutputSerializer(p.expected_outputs.all(), many=True).data
        rows.append({
            "project_code": p.project_code, "title": p.title, "campus": p.campus,
            "publications": PublicationRecord.objects.filter(project=p).count(),
            "ip_records": IPRecord.objects.filter(project=p).count(),
            "creative_works": CreativeWorkRecord.objects.filter(project=p).count(),
            "expected_6p_targets": sum(e["target_count"] for e in expected),
            "expected_6p_rows_met": sum(1 for e in expected if e["actual_count"] >= e["target_count"]),
            "outcomes": p.outcomes.filter(kind="outcome").count(),
            "impacts": p.outcomes.filter(kind="impact").count(),
        })
    return rows
