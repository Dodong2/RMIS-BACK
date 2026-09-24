"""The monitoring indicators the client listed (clarification Q10), computed live for one project.
Each one reuses the module that owns the data; nothing here is stored."""
from datetime import timedelta

from django.utils import timezone

from compliance.models import AI_CONTENT_THRESHOLD, AIUseDeclaration, SimilarityCheckRecord
from financial_monitoring.models import PROCUREMENT_DELAY_DAYS, BudgetRealignment, ProcurementRequest
from forecasting.models import ForecastRun

from .models import ExtensionRequest
from .serializers import compute_budget_used_pct, compute_deliverables_pct, compute_escalation_status


def compute_indicators(project):
    today = timezone.localdate()
    escalation = compute_escalation_status(project)
    budget_pct = compute_budget_used_pct(project)
    deliverables_pct = compute_deliverables_pct(project)
    latest_eval = project.evaluations.order_by("-scheduled_date").first()
    latest_forecast = ForecastRun.objects.filter(project=project, status="success").order_by("-run_at").first()
    latest_sync = project.budget_office_records.select_related("source").order_by("-source__uploaded_at").first()
    delayed_procurement = ProcurementRequest.objects.filter(
        line_item__budget__project=project, status__in=("requested", "processing"),
        requested_at__lt=timezone.now() - timedelta(days=PROCUREMENT_DELAY_DAYS),
    ).count()
    similarity = SimilarityCheckRecord.objects.filter(project=project)
    outputs_target = sum(e.target_count for e in project.expected_outputs.all())

    budget_office_status = None
    if latest_sync:
        from budget_sync.services import reconcile  # local import: budget_sync depends on budget_lib, not monitoring
        row = next(r for r in reconcile(latest_sync.source)["records"] if r["record"] == latest_sync.id)
        budget_office_status = row["status"]

    return {
        "monthly_report": {"status": escalation["status"], "months_since_last_report": escalation["months_since_last_report"]},
        "midterm_report_years": list(project.midterm_reports.values_list("project_year", flat=True)),
        "budget_utilization_pct": budget_pct,
        "budget_utilization_meets_70": budget_pct is not None and budget_pct >= 70,
        "deliverables_pct": deliverables_pct,
        "deliverables_meets_70": deliverables_pct is not None and deliverables_pct >= 70,
        "terminal_report_submitted": hasattr(project, "terminal_report"),
        "latest_evaluation": latest_eval and {"scheduled_date": latest_eval.scheduled_date, "outcome": latest_eval.outcome},
        "extension_requests": list(ExtensionRequest.objects.filter(project=project).values("status", "requested_end_date")),
        "realignments_this_year": BudgetRealignment.objects.filter(
            from_line_item__budget__project=project, created_at__year=today.year,
        ).exclude(status="rejected").count(),
        "procurement_delayed": delayed_procurement,
        "ai_declarations": {
            "total": AIUseDeclaration.objects.filter(project=project).count(),
            "over_threshold": AIUseDeclaration.objects.filter(project=project, ai_content_pct__gt=AI_CONTENT_THRESHOLD).count(),
        },
        "similarity_checks": {"total": similarity.count(), "over_threshold": similarity.filter(is_within_threshold=False).count()},
        "outputs_6ps": {"target": outputs_target, "expected_output_rows": project.expected_outputs.count()},
        "forecast_overrun_risk": latest_forecast.is_overrun_risk if latest_forecast else None,
        "budget_office_status": budget_office_status,
    }
