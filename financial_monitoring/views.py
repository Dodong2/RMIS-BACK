import uuid
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import BudgetScopedMixin, HasRole, role_can, scoped_projects
from budget_lib.models import LineItem, LineItemBudget
from config.concurrency import idempotent, lock, lock_line_items
from realtime.notify import notify, project_audience
from . import notifications
from .models import (
    PROCUREMENT_CLOSED_STATUSES, PROCUREMENT_DELAY_DAYS, BudgetRealignment, Disbursement, ProcurementRequest,
    ProcurementStatusEvent,
)
from .serializers import (
    BudgetRealignmentSerializer,
    DisbursementSerializer,
    ProcurementPaySerializer,
    ProcurementRequestSerializer,
    ProcurementStatusSerializer,
    RealignmentReviewSerializer,
    line_item_balance,
    uncommitted_balance,
    post_procurement_disbursement,
    project_years,
    review_realignment,
    year_balance,
)


def in_scope(queryset, user, project_lookup):
    """queryset limited to the user's scoped projects (campus-scoped Finance/Procurement), for the write endpoints that
    lock a row by pk: without it a campus-scoped account could act on another campus's record by its id (2026-10-22)."""
    projects = scoped_projects(user)
    return queryset if projects is None else queryset.filter(**{f"{project_lookup}__in": projects})


def record_procurement_event(procurement, from_status, user, remarks=""):
    ProcurementStatusEvent.objects.create(
        procurement=procurement, from_status=from_status, to_status=procurement.status, actor=user, remarks=remarks,
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
            return [HasRole("financial.record_disbursement")]
        return [permissions.IsAuthenticated()]

    @idempotent
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

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
        qs = BudgetRealignment.objects.select_related("from_line_item", "to_line_item", "reviewed_by").order_by("-created_at")
        budget_id = self.request.query_params.get("budget")
        if budget_id:
            qs = qs.filter(from_line_item__budget_id=budget_id)
        return qs

    def get_permissions(self):
        if self.request.method == "POST":
            return [HasRole("financial.request_realignment")]
        return [permissions.IsAuthenticated()]

    @idempotent
    def create(self, request, *args, **kwargs):
        """
        Accepts one realignment or a list of them (client 2026-10-10: bulk request,
        one submission). A list is saved all-or-nothing under one batch id.
        """
        many = isinstance(request.data, list)
        serializer = self.get_serializer(data=request.data, many=many)
        serializer.is_valid(raise_exception=True)
        rows = serializer.validated_data if many else [serializer.validated_data]
        if not rows:
            raise ValidationError("Add at least one realignment.")
        if len({row["from_line_item"].budget_id for row in rows}) > 1:
            raise ValidationError("All realignments in one request must belong to the same budget.")

        # Each row was checked against its source's balance alone; rows sharing a source must fit together.
        per_source = defaultdict(Decimal)
        for row in rows:
            per_source[row["from_line_item"]] += row["amount"]
        for item, total in per_source.items():
            available = uncommitted_balance(item)
            if total > available:
                raise ValidationError(
                    f"Realignments from '{item.description}' total {total}, more than its available balance ({available})."
                )

        serializer.save(requested_by=request.user, batch=uuid.uuid4())
        saved = serializer.instance if many else [serializer.instance]
        realignment_signal("financial.realignment.created", saved[0])  # one signal per request, even for a bulk one
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class RealignmentDetailView(BudgetScopedMixin, generics.RetrieveAPIView):
    project_lookup = "from_line_item__budget__project"
    queryset = BudgetRealignment.objects.select_related("from_line_item", "to_line_item")
    serializer_class = BudgetRealignmentSerializer
    permission_classes = [permissions.IsAuthenticated]


class RealignmentReviewView(APIView):
    """
    Approve/reject a pending realignment. Every tier is reviewed by the
    Finance/Budget Officer or system_admin (client 2026-10-08); BOR-tier
    still needs the Board of Regents resolution number (no BOR role exists).
    """

    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request, pk):
        # Locked so a double-click or a second reviewer waits, then sees it is no longer pending.
        realignment = lock(in_scope(BudgetRealignment.objects.all(), request.user, "from_line_item__budget__project"), pk=pk)
        if realignment.status not in ("pending_approval", "pending_bor"):
            return Response({"detail": "This realignment is not awaiting review."}, status=status.HTTP_400_BAD_REQUEST)

        code = "financial.review_bor_realignment" if realignment.tier == "bor" else "financial.review_major_realignment"
        if not role_can(request.user, code):
            return Response({"detail": "You do not have permission to review this realignment."}, status=status.HTTP_403_FORBIDDEN)

        serializer = RealignmentReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        realignment = review_realignment(
            realignment, request.user,
            serializer.validated_data["decision"],
        )
        realignment_signal("financial.realignment.reviewed", realignment)
        return Response(BudgetRealignmentSerializer(realignment).data)


def realignment_signal(event_type, realignment):
    """Real-time "this project's realignments changed" (realtime/notify.py), sent after commit to the roles holding a
    financial.* permission, the project lead and the requester, so the Budget Officer's bell and the leader's
    Realignment tab refetch."""
    project = realignment.from_line_item.budget.project
    notify(project_audience(project, "financial.", realignment.requested_by_id), event_type,
           id=realignment.id, project=project.id)


def procurement_signal(event_type, procurement):
    """Real-time "this procurement request changed" (realtime/notify.py), sent after commit to the roles holding a
    financial.* permission, the project lead and the requester, so the leader's open Procurement page and bell refetch."""
    project = procurement.line_item.budget.project
    notify(project_audience(project, "financial.", procurement.requested_by_id), event_type,
           id=procurement.id, project=project.id, status=procurement.status)


PR_PROJECT = "line_item__budget__project"


class ProcurementRequestListCreateView(BudgetScopedMixin, generics.ListCreateAPIView):
    project_lookup = "line_item__budget__project"
    serializer_class = ProcurementRequestSerializer

    def get_queryset(self):
        qs = ProcurementRequest.objects.select_related("line_item__budget", "disbursement__recorded_by").order_by("-requested_at")
        params = self.request.query_params
        if params.get("project"):
            qs = qs.filter(line_item__budget__project_id=params["project"])
        for param in ("status", "project_year", "fiscal_year", "quarter"):
            if params.get(param):
                qs = qs.filter(**{param: params[param]})
        if params.get("overdue") == "true":
            cutoff = timezone.now() - timedelta(days=PROCUREMENT_DELAY_DAYS)
            qs = qs.exclude(status__in=PROCUREMENT_CLOSED_STATUSES).filter(requested_at__lt=cutoff)
        if params.get("active") == "true":
            qs = qs.exclude(status__in=PROCUREMENT_CLOSED_STATUSES)
        if params.get("payment") == "awaiting":
            qs = qs.filter(status="completed", disbursement__isnull=True)
        elif params.get("payment") == "paid":
            qs = qs.filter(disbursement__isnull=False)
        return qs

    def get_permissions(self):
        if self.request.method == "POST":
            return [HasRole("financial.request_procurement")]
        return [permissions.IsAuthenticated()]

    @idempotent
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        procurement = serializer.save(requested_by=self.request.user)
        record_procurement_event(procurement, "", self.request.user)
        procurement_signal("procurement.created", procurement)
        transaction.on_commit(lambda: notifications.request_filed(procurement))


class ProcurementReceiveView(APIView):
    """Client 2026-10-12: the Procurement Officer marks a submitted request Received -> Under Review."""

    permission_classes = [HasRole("financial.update_procurement")]

    @transaction.atomic
    def post(self, request, pk):
        procurement = lock(in_scope(ProcurementRequest.objects.all(), request.user, PR_PROJECT), pk=pk)
        if procurement.status != "requested":
            return Response({"detail": "Only a submitted request can be marked received."}, status=status.HTTP_400_BAD_REQUEST)
        procurement.status = "under_review"
        procurement.received_by = procurement.updated_by = request.user
        procurement.received_at = timezone.now()
        procurement.save()
        record_procurement_event(procurement, "requested", request.user)
        procurement_signal("procurement.updated", procurement)
        transaction.on_commit(lambda: notifications.request_received(procurement))
        return Response(ProcurementRequestSerializer(procurement).data)


class ProcurementStatusView(APIView):
    """After Received, the Procurement Office picks the next status until Completed."""

    permission_classes = [HasRole("financial.update_procurement")]

    @transaction.atomic
    def post(self, request, pk):
        # Locked so two "Completed" clicks can't both pass the status check (one disbursement, then a clean 400).
        procurement = lock(in_scope(ProcurementRequest.objects.all(), request.user, PR_PROJECT), pk=pk)
        previous = procurement.status
        serializer = ProcurementStatusSerializer(data=request.data, context={"procurement": procurement})
        serializer.is_valid(raise_exception=True)
        procurement.status = serializer.validated_data["status"]
        procurement.remarks = serializer.validated_data.get("remarks", procurement.remarks)
        procurement.updated_by = request.user
        if procurement.status == "completed":
            procurement.completed_at = timezone.now()  # not paid yet: Finance confirms the payment (ProcurementPayView)
        procurement.save()
        record_procurement_event(procurement, previous, request.user, serializer.validated_data.get("remarks", ""))
        procurement_signal("procurement.updated", procurement)
        if procurement.status == "returned_for_revision":
            transaction.on_commit(lambda: notifications.request_returned(procurement))
        elif procurement.status == "completed":
            transaction.on_commit(lambda: notifications.request_completed(procurement))
        return Response(ProcurementRequestSerializer(procurement).data)


class ProcurementPayView(APIView):
    """Task 23 (2026-10-30): Finance/Accounting/Budget confirms the full payment of a Completed request (Q5/Q6); only
    then is it paid/utilized. Paying twice is refused."""

    permission_classes = [HasRole("financial.record_disbursement")]

    @transaction.atomic
    def post(self, request, pk):
        procurement = lock(in_scope(ProcurementRequest.objects.all(), request.user, PR_PROJECT), pk=pk)
        if Disbursement.objects.filter(procurement_request=procurement).exists():
            return Response({"detail": "This request has already been paid."}, status=status.HTTP_400_BAD_REQUEST)
        if procurement.status != "completed":
            return Response({"detail": "Only a request the Procurement Office has completed can be paid."},
                            status=status.HTTP_400_BAD_REQUEST)
        serializer = ProcurementPaySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        lock_line_items(procurement.line_item)
        post_procurement_disbursement(procurement, user=request.user, **serializer.validated_data)
        procurement_signal("procurement.updated", procurement)
        return Response(ProcurementRequestSerializer(ProcurementRequest.objects.get(pk=procurement.pk)).data)


class ProcurementResubmitView(BudgetScopedMixin, generics.GenericAPIView):
    """The leader edits a request Returned for Revision and sends it back as Request Submitted."""

    project_lookup = "line_item__budget__project"
    queryset = ProcurementRequest.objects.select_related("line_item__budget")
    serializer_class = ProcurementRequestSerializer
    permission_classes = [HasRole("financial.request_procurement")]

    @transaction.atomic
    def post(self, request, pk):
        procurement = lock(ProcurementRequest.objects.all(), pk=self.get_object().pk)
        if procurement.status != "returned_for_revision":
            return Response({"detail": "Only a request returned for revision can be resubmitted."}, status=status.HTTP_400_BAD_REQUEST)
        data = {k: v for k, v in request.data.items() if k in ("description", "amount", "project_year", "quarter")}
        data["remarks"] = request.data.get("remarks", "")  # the leader's note replaces the Procurement Office's return reason
        serializer = self.get_serializer(procurement, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        procurement = serializer.save(status="requested", received_by=None, received_at=None)
        record_procurement_event(procurement, "returned_for_revision", request.user, data["remarks"])
        procurement_signal("procurement.updated", procurement)
        return Response(serializer.data)


class ProcurementBalanceView(APIView):
    """Task 22 (2026-10-30): a LIB item's procurement figures per project year (and its quarters) for the New
    Procurement Request modal; the same year_balance() the request validation uses."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        items = in_scope(LineItem.objects.select_related("budget__project"), request.user, "budget__project")
        item = generics.get_object_or_404(items, pk=request.query_params.get("line_item") or 0)
        years = project_years(item.budget.project)
        return Response({"line_item": item.pk, "years": [year_balance(item, year) for year in years]})


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
