from datetime import timedelta

from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import BudgetScopedMixin, HasRole, scoped_projects
from budget_lib.models import LineItemBudget
from .models import PROCUREMENT_DELAY_DAYS, BudgetRealignment, Disbursement, ProcurementRequest
from .serializers import (
    DISBURSEMENT_ROLES,
    PROCUREMENT_REQUEST_ROLES,
    PROCUREMENT_STATUS_ROLES,
    REALIGNMENT_BOR_REVIEW_ROLES,
    REALIGNMENT_MAJOR_REVIEW_ROLES,
    REALIGNMENT_REQUEST_ROLES,
    BudgetRealignmentSerializer,
    DisbursementSerializer,
    ProcurementRequestSerializer,
    ProcurementStatusSerializer,
    RealignmentReviewSerializer,
    line_item_balance,
    review_realignment,
)


class DisbursementListCreateView(BudgetScopedMixin, generics.ListCreateAPIView):
    project_lookup = "line_item__budget__project"
    serializer_class = DisbursementSerializer

    def get_queryset(self):
        qs = Disbursement.objects.select_related("line_item").order_by("-disbursed_on")
        line_item_id = self.request.query_params.get("line_item")
        budget_id = self.request.query_params.get("budget")
        if line_item_id:
            qs = qs.filter(line_item_id=line_item_id)
        if budget_id:
            qs = qs.filter(line_item__budget_id=budget_id)
        params = self.request.query_params
        if params.get("project"):
            qs = qs.filter(line_item__budget__project_id=params["project"])
        if params.get("from"):
            qs = qs.filter(disbursed_on__gte=params["from"])
        if params.get("to"):
            qs = qs.filter(disbursed_on__lte=params["to"])
        return qs

    def get_permissions(self):
        if self.request.method == "POST":
            return [HasRole(DISBURSEMENT_ROLES)]
        return [permissions.IsAuthenticated()]

    def perform_create(self, serializer):
        serializer.save(recorded_by=self.request.user)


class DisbursementDetailView(BudgetScopedMixin, generics.RetrieveAPIView):
    project_lookup = "line_item__budget__project"
    queryset = Disbursement.objects.select_related("line_item")
    serializer_class = DisbursementSerializer
    permission_classes = [permissions.IsAuthenticated]


class RealignmentListCreateView(BudgetScopedMixin, generics.ListCreateAPIView):
    project_lookup = "from_line_item__budget__project"
    serializer_class = BudgetRealignmentSerializer

    def get_queryset(self):
        qs = BudgetRealignment.objects.select_related("from_line_item", "to_line_item").order_by("-created_at")
        budget_id = self.request.query_params.get("budget")
        if budget_id:
            qs = qs.filter(from_line_item__budget_id=budget_id)
        return qs

    def get_permissions(self):
        if self.request.method == "POST":
            return [HasRole(REALIGNMENT_REQUEST_ROLES)]
        return [permissions.IsAuthenticated()]

    def perform_create(self, serializer):
        serializer.save(requested_by=self.request.user)


class RealignmentDetailView(BudgetScopedMixin, generics.RetrieveAPIView):
    project_lookup = "from_line_item__budget__project"
    queryset = BudgetRealignment.objects.select_related("from_line_item", "to_line_item")
    serializer_class = BudgetRealignmentSerializer
    permission_classes = [permissions.IsAuthenticated]


class RealignmentReviewView(APIView):
    """
    Approve/reject a major or BOR-tier realignment. Major (33-100%) may be
    reviewed by University Administration; BOR-tier (>100%/new item) is
    system_admin only, per client confirmation (no Board of Regents role exists).
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        realignment = generics.get_object_or_404(BudgetRealignment, pk=pk)
        if realignment.status not in ("pending_approval", "pending_bor"):
            return Response({"detail": "This realignment is not awaiting review."}, status=status.HTTP_400_BAD_REQUEST)

        allowed_roles = REALIGNMENT_BOR_REVIEW_ROLES if realignment.tier == "bor" else REALIGNMENT_MAJOR_REVIEW_ROLES
        user_role = request.user.role.code if request.user.role else None
        if user_role not in allowed_roles:
            return Response({"detail": "You do not have permission to review this realignment."}, status=status.HTTP_403_FORBIDDEN)

        serializer = RealignmentReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        realignment = review_realignment(
            realignment, request.user,
            serializer.validated_data["decision"],
            serializer.validated_data.get("bor_resolution_number", ""),
        )
        return Response(BudgetRealignmentSerializer(realignment).data)


class ProcurementRequestListCreateView(BudgetScopedMixin, generics.ListCreateAPIView):
    project_lookup = "line_item__budget__project"
    serializer_class = ProcurementRequestSerializer

    def get_queryset(self):
        qs = ProcurementRequest.objects.select_related("line_item__budget").order_by("-requested_at")
        params = self.request.query_params
        if params.get("project"):
            qs = qs.filter(line_item__budget__project_id=params["project"])
        for param in ("status", "fiscal_year", "quarter"):
            if params.get(param):
                qs = qs.filter(**{param: params[param]})
        if params.get("overdue") == "true":
            cutoff = timezone.now() - timedelta(days=PROCUREMENT_DELAY_DAYS)
            qs = qs.filter(status__in=("requested", "processing"), requested_at__lt=cutoff)
        return qs

    def get_permissions(self):
        if self.request.method == "POST":
            return [HasRole(PROCUREMENT_REQUEST_ROLES)]
        return [permissions.IsAuthenticated()]

    def perform_create(self, serializer):
        serializer.save(requested_by=self.request.user)


class ProcurementStatusView(APIView):
    """Procurement Office moves a request Requested -> Processing -> Released (or Cancelled)."""

    permission_classes = [HasRole(PROCUREMENT_STATUS_ROLES)]

    def post(self, request, pk):
        procurement = generics.get_object_or_404(ProcurementRequest, pk=pk)
        serializer = ProcurementStatusSerializer(data=request.data, context={"procurement": procurement})
        serializer.is_valid(raise_exception=True)
        procurement.status = serializer.validated_data["status"]
        procurement.remarks = serializer.validated_data.get("remarks", procurement.remarks)
        procurement.updated_by = request.user
        if procurement.status == "processing":
            procurement.processing_at = timezone.now()
        elif procurement.status == "released":
            procurement.released_at = timezone.now()
        procurement.save()
        return Response(ProcurementRequestSerializer(procurement).data)


class BudgetSummaryView(APIView):
    """Approved / Adjusted / Actual figures per line item for a certified budget."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        budgets = LineItemBudget.objects.select_related("project")
        projects = scoped_projects(request.user)
        if projects is not None:
            budgets = budgets.filter(project__in=projects)
        budget = generics.get_object_or_404(budgets, pk=pk)
        line_items = budget.line_items.all().order_by("category", "id")
        fiscal_year = request.query_params.get("fiscal_year")
        if fiscal_year:
            line_items = line_items.filter(fiscal_year=fiscal_year)
        items = []
        for item in line_items:
            balance = line_item_balance(item)
            items.append({
                "line_item": item.pk, "category": item.category, "description": item.description,
                "fiscal_year": item.fiscal_year, "funding_source": item.funding_source,
                "is_counterpart": item.is_counterpart, **balance, "utilization_pct": _utilization_pct(balance),
            })
        return Response({
            "budget": budget.pk, "project": budget.project_id, "line_items": items,
            "by_category": _subtotals(items, "category"),
            "by_funding_source": _subtotals(items, "funding_source"),
            "totals": _sum_figures(items),
        })


def _utilization_pct(figures):
    """Actual spent as a % of the adjusted (realigned) amount (DPMIS-based spec BM-06)."""
    if not figures["adjusted"]:
        return None
    return round(float(figures["actual"]) / float(figures["adjusted"]) * 100, 2)


def _sum_figures(rows):
    totals = {key: sum(row[key] for row in rows) for key in ("approved", "adjusted", "actual", "available")}
    totals["utilization_pct"] = _utilization_pct(totals)
    return totals


def _subtotals(rows, key):
    groups = {}
    for row in rows:
        groups.setdefault(row[key] or "", []).append(row)
    return [{key: group, **_sum_figures(group_rows)} for group, group_rows in groups.items()]
