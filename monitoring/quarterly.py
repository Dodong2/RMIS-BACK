"""Helpers for R&D Quarterly Progress Reports: quarter dates, overdue rule, and the prefill from RMIS data."""
import datetime

from django.db.models import Sum
from django.utils import timezone

from budget_lib.models import LineItem
from financial_monitoring.models import Disbursement
from financial_monitoring.serializers import line_item_balance

OVERDUE_GRACE_DAYS = 15  # prototype rule: due 15 days after the quarter ends (not in the Manual; client to confirm)


def today():
    return timezone.localdate()


def quarter_range(year, quarter):
    start = datetime.date(year, (quarter - 1) * 3 + 1, 1)
    next_start = datetime.date(year + 1, 1, 1) if quarter == 4 else datetime.date(year, quarter * 3 + 1, 1)
    return start, next_start - datetime.timedelta(days=1)


def is_overdue(report):
    if report.status == "approved":
        return False
    _, end = quarter_range(report.year, report.quarter)
    return today() > end + datetime.timedelta(days=OVERDUE_GRACE_DAYS)


def _current_items(project):
    return LineItem.objects.filter(budget__project=project, budget__is_current=True)


def funding_agency(project):
    """Projects carry no agency field; same source as Analytics > Overview: the current LIB's funding sources."""
    sources = _current_items(project).exclude(funding_source="").values_list("funding_source", flat=True)
    return ", ".join(sorted({s.strip() for s in sources}))


def objective_list(project):
    return [line.strip() for line in project.objectives.splitlines() if line.strip()]


def financial_snapshot(project, year, quarter):
    start, end = quarter_range(year, quarter)
    items = list(_current_items(project))
    original = sum(float(item.amount) for item in items)
    adjusted = sum(float(line_item_balance(item)["adjusted"]) for item in items)
    spent = Disbursement.objects.filter(line_item__in=items)
    in_quarter = spent.filter(disbursed_on__range=(start, end))
    quarter_total = float(in_quarter.aggregate(total=Sum("amount"))["total"] or 0)
    cumulative = float(spent.filter(disbursed_on__lte=end).aggregate(total=Sum("amount"))["total"] or 0)
    return {
        "original_budget": original,
        "approved_adjustments": adjusted - original,
        "adjusted_budget": adjusted,
        "quarter_disbursements": quarter_total,
        "cumulative_disbursements": cumulative,
        "remaining_budget": adjusted - cumulative,
        "utilization_pct": round(cumulative / adjusted * 100) if adjusted else 0,
        "transaction_count": in_quarter.count(),
        "over_budget": cumulative > adjusted,
    }


def prefill_accomplishments(project, year, quarter):
    """One row per work-plan activity active during the quarter; the leader fills in the actuals."""
    start, end = quarter_range(year, quarter)
    rows = []
    for m in project.milestones.order_by("target_date", "id"):
        if (m.start_date or m.target_date) > end or m.target_date < start:
            continue
        rows.append({
            "objective": m.objective, "activity": m.title, "target": m.deliverable, "actual": "", "cumulative": "",
            "target_date": m.target_date.isoformat(), "actual_date": "",
            "completion_pct": 100 if m.status == "done" else 0, "variance": "", "remarks": m.remarks,
        })
    return rows
