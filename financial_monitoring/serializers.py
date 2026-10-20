from datetime import timedelta

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from budget_lib.models import LineItem
from accounts.permissions import ensure_in_scope
from budget_lib.models import LineItemBudget
from budget_lib.serializers import catalog_item_name
from config.concurrency import lock_line_items
from .models import APPLIED_STATUSES, PROCUREMENT_CLOSED_STATUSES, BudgetRealignment, Disbursement, ProcurementRequest

# Seed source for the permission table (accounts/permission_seed.py); gates use permission codes.
# Client 2026-10-11: system_admin only approves, so only the project leader files realignments.
REALIGNMENT_REQUEST_ROLES = ["project_leader"]
# Client 2026-10-08: the Finance/Budget Officer approves realignments; system_admin can too (for testing).
REALIGNMENT_MAJOR_REVIEW_ROLES = ["system_admin", "finance_budget"]
REALIGNMENT_BOR_REVIEW_ROLES = ["system_admin", "finance_budget"]
DISBURSEMENT_ROLES = ["system_admin", "finance_budget"]
PROCUREMENT_REQUEST_ROLES = ["system_admin", "program_leader", "project_leader"]  # "signed by the Lead Proponent"
PROCUREMENT_STATUS_ROLES = ["system_admin", "procurement_officer_lib"]

MINOR_TIER_MAX_PCT = 33
MAJOR_TIER_MAX_PCT = 100
REALIGNMENT_MIN_LEAD_DAYS = 60  # "at least two (2) months before the end of the project"
PENDING_STATUSES = ("pending_approval", "pending_bor")


def line_item_balance(line_item, exclude_realignment_pk=None):
    """Approved / Adjusted / Actual / Available figures for one line item."""
    applied_in = line_item.realignments_to.filter(status__in=APPLIED_STATUSES)
    applied_out = line_item.realignments_from.filter(status__in=APPLIED_STATUSES)
    if exclude_realignment_pk:
        applied_in = applied_in.exclude(pk=exclude_realignment_pk)
        applied_out = applied_out.exclude(pk=exclude_realignment_pk)

    moved_in = applied_in.aggregate(total=Sum("amount"))["total"] or 0
    moved_out = applied_out.aggregate(total=Sum("amount"))["total"] or 0
    adjusted = line_item.amount + moved_in - moved_out
    actual = line_item.disbursements.aggregate(total=Sum("amount"))["total"] or 0
    return {
        "approved": line_item.amount,
        "adjusted": adjusted,
        "actual": actual,
        "available": adjusted - actual,
    }


def uncommitted_balance(line_item, exclude_procurement_pk=None):
    """
    What can still be spent or moved: Available minus open procurement requests, which already reserve their amount.
    Every write that uses a line item's money checks this one figure (under the item's row lock), so
    Actual + open requests never exceeds Adjusted.
    """
    open_requests = line_item.procurement_requests.exclude(status__in=PROCUREMENT_CLOSED_STATUSES)
    if exclude_procurement_pk:
        open_requests = open_requests.exclude(pk=exclude_procurement_pk)
    reserved = open_requests.aggregate(total=Sum("amount"))["total"] or 0
    return line_item_balance(line_item)["available"] - reserved


class DisbursementSerializer(serializers.ModelSerializer):
    funding_source = serializers.CharField(source="line_item.funding_source", read_only=True)

    class Meta:
        model = Disbursement
        fields = [
            "id", "line_item", "amount", "reference_number", "description", "payee", "supporting_document",
            "funding_source", "disbursed_on", "recorded_by", "procurement_request", "created_at",
        ]
        read_only_fields = ["recorded_by", "procurement_request"]

    def validate(self, attrs):
        line_item = attrs.get("line_item", getattr(self.instance, "line_item", None))
        document = attrs.get("supporting_document", getattr(self.instance, "supporting_document", None))
        if document and document.project_id != line_item.budget.project_id:
            raise serializers.ValidationError({"supporting_document": "Document belongs to a different project."})
        amount = attrs.get("amount", getattr(self.instance, "amount", None))
        if line_item.budget.status != "certified":
            raise serializers.ValidationError("Disbursements can only be recorded against a certified budget.")
        lock_line_items(line_item)  # held until commit: no other spend on this item can pass the check meanwhile
        available = uncommitted_balance(line_item) + (self.instance.amount if self.instance else 0)
        if amount > available:
            raise serializers.ValidationError(
                f"Amount {amount} exceeds the available balance ({available}) for this line item."
            )
        return attrs


def post_procurement_disbursement(procurement):
    """
    Client 2026-10-12: a Completed procurement request is the fund release (LSPU has no separate
    Disbursement office), so it is posted as the project's Actual for the full request amount.
    """
    return Disbursement.objects.create(
        line_item=procurement.line_item,
        amount=procurement.amount,
        reference_number=f"PR-{procurement.pk:04d}",
        description=procurement.description[:300],
        disbursed_on=timezone.localdate(procurement.completed_at),
        recorded_by=procurement.updated_by,
        procurement_request=procurement,
    )


class RealignmentReviewSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["approved", "rejected"])


class BudgetRealignmentSerializer(serializers.ModelSerializer):
    tier = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    reviewed_by_name = serializers.CharField(source="reviewed_by.display_name", read_only=True, default=None)

    class Meta:
        model = BudgetRealignment
        fields = [
            "id", "from_line_item", "to_line_item", "new_item_category", "new_item_description",
            "amount", "tier", "status", "justification", "requested_by",
            "reviewed_by", "reviewed_by_name", "reviewed_at", "bor_resolution_number", "batch", "created_at",
        ]
        read_only_fields = ["requested_by", "reviewed_by", "reviewed_at", "bor_resolution_number", "batch"]

    def validate(self, attrs):
        from_item = attrs.get("from_line_item", getattr(self.instance, "from_line_item", None))
        ensure_in_scope(self, from_item.budget.project)
        to_item = attrs.get("to_line_item", getattr(self.instance, "to_line_item", None))
        new_category = attrs.get("new_item_category", "")
        new_description = attrs.get("new_item_description", "")
        amount = attrs.get("amount", getattr(self.instance, "amount", None))

        if bool(to_item) == bool(new_category or new_description):
            raise serializers.ValidationError(
                "Provide either to_line_item (existing item) or new_item_category/new_item_description (new item), not both."
            )
        if new_category and not new_description:
            raise serializers.ValidationError({"new_item_description": "Required when creating a new expense item."})
        if new_category:
            try:
                attrs["new_item_description"] = catalog_item_name(new_category, new_description)
            except serializers.ValidationError as exc:
                raise serializers.ValidationError({"new_item_description": exc.detail["description"]})

        project = from_item.budget.project
        if from_item.budget.status != "certified":
            raise serializers.ValidationError("Realignments can only be requested against a certified budget.")
        # Budget first, then items in id order: every realignment write takes locks in this same order.
        LineItemBudget.objects.select_for_update().get(pk=from_item.budget_id)
        lock_line_items(from_item, to_item)
        if to_item and to_item.budget_id != from_item.budget_id:
            raise serializers.ValidationError("from_line_item and to_line_item must belong to the same budget.")
        if to_item and to_item.pk == from_item.pk:
            raise serializers.ValidationError("from_line_item and to_line_item must be different.")
        # Client 2026-10-10: internal (within class) realignment only, e.g. MOOE -> MOOE.
        target_category = to_item.category if to_item else new_category
        if target_category and target_category != from_item.category:
            raise serializers.ValidationError(
                f"Realignment must stay within the same class: the source item is "
                f"{from_item.get_category_display()}, so the destination must be too."
            )

        if project.target_end_date:
            deadline = project.target_end_date - timedelta(days=REALIGNMENT_MIN_LEAD_DAYS)
            if timezone.localdate() > deadline:
                raise serializers.ValidationError(
                    f"Realignment requests must be submitted at least {REALIGNMENT_MIN_LEAD_DAYS} days "
                    "before the project's target end date."
                )

        # Client 2026-10-10: no yearly limit, but only one open request at a time.
        if BudgetRealignment.objects.filter(
            from_line_item__budget__project=project, status__in=PENDING_STATUSES,
        ).exists():
            raise serializers.ValidationError(
                "This project still has a pending realignment request. "
                "Wait for the Budget Officer's decision before submitting another."
            )

        available = uncommitted_balance(from_item)
        if amount > available:
            raise serializers.ValidationError(
                f"Amount {amount} exceeds the available balance ({available}) on the source line item."
            )

        if new_category:
            attrs["tier"] = "bor"
        else:
            pct = (amount / from_item.amount) * 100 if from_item.amount else 100
            attrs["tier"] = "minor" if pct <= MINOR_TIER_MAX_PCT else "major" if pct <= MAJOR_TIER_MAX_PCT else "bor"
        return attrs

    def create(self, validated_data):
        # Client 2026-10-08: every realignment, minor ones included, waits for the Budget Officer.
        validated_data["status"] = "pending_bor" if validated_data["tier"] == "bor" else "pending_approval"
        return BudgetRealignment.objects.create(**validated_data)


def review_realignment(realignment, reviewer, decision):
    """Approve/reject a pending realignment. Caller must hold its row lock and have checked it's still pending."""
    with transaction.atomic():
        if decision != "rejected":
            LineItemBudget.objects.select_for_update().get(pk=realignment.from_line_item.budget_id)
            lock_line_items(realignment.from_line_item, realignment.to_line_item)
            # Money may have been spent from the source since the request was filed.
            available = uncommitted_balance(realignment.from_line_item)
            if realignment.amount > available:
                raise serializers.ValidationError(
                    f"The source item now has only {available} available, less than this realignment ({realignment.amount})."
                )
        if decision == "rejected":
            realignment.status = "rejected"
        elif realignment.tier != "bor":
            realignment.status = "approved"
        else:  # bor; client 2026-10-10: no BOR resolution no. needed, the budget is already approved
            if not realignment.to_line_item_id:
                realignment.to_line_item = LineItem.objects.create(
                    budget=realignment.from_line_item.budget,
                    category=realignment.new_item_category,
                    description=realignment.new_item_description,
                    amount=realignment.amount,
                )
            realignment.status = "bor_approved"
        realignment.reviewed_by = reviewer
        realignment.reviewed_at = timezone.now()
        realignment.save(update_fields=["status", "to_line_item", "reviewed_by", "reviewed_at"])
    return realignment


class ProcurementRequestSerializer(serializers.ModelSerializer):
    project = serializers.IntegerField(source="line_item.budget.project_id", read_only=True)
    routed_to = serializers.CharField(read_only=True)
    requested_by_name = serializers.CharField(source="requested_by.display_name", read_only=True)
    received_by_name = serializers.CharField(source="received_by.display_name", read_only=True, default=None)
    received_by_role = serializers.CharField(source="received_by.role.name", read_only=True, default=None)

    class Meta:
        model = ProcurementRequest
        fields = [
            "id", "project", "line_item", "description", "amount", "fiscal_year", "quarter", "routed_to",
            "status", "remarks", "requested_by", "requested_by_name", "requested_at",
            "received_by", "received_by_name", "received_by_role", "received_at", "completed_at", "updated_by",
        ]
        read_only_fields = ["status", "requested_by", "requested_at", "received_by", "received_at", "completed_at", "updated_by"]

    def validate(self, attrs):
        line_item = attrs.get("line_item", getattr(self.instance, "line_item", None))
        amount = attrs.get("amount", getattr(self.instance, "amount", None))
        ensure_in_scope(self, line_item.budget.project)
        if line_item.budget.status != "certified":
            raise serializers.ValidationError("Procurement can only be requested against a certified budget.")
        lock_line_items(line_item)  # held until commit: no other spend on this item can pass the check meanwhile
        available = uncommitted_balance(line_item, exclude_procurement_pk=self.instance.pk if self.instance else None)
        if amount > available:
            raise serializers.ValidationError(
                f"Amount {amount} exceeds what is still available on this line item ({available})."
            )
        return attrs


# Client 2026-10-12: after Received, the Procurement Officer picks any of these (Completed closes the request).
PROCUREMENT_UPDATE_STATUSES = [
    "returned_for_revision", "for_procurement", "procurement_in_progress", "order_placed",
    "awaiting_delivery", "delivered", "ready_for_release", "completed",
]


class ProcurementStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=PROCUREMENT_UPDATE_STATUSES)
    remarks = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        current = self.context["procurement"].status
        if current in ("requested", "returned_for_revision") or current in PROCUREMENT_CLOSED_STATUSES:
            raise serializers.ValidationError(f"A request that is '{current}' can't be updated here.")
        if attrs["status"] == current:
            raise serializers.ValidationError("The request already has this status.")
        if attrs["status"] == "returned_for_revision" and not attrs.get("remarks", "").strip():
            raise serializers.ValidationError({"remarks": "Remarks are required when returning a request for revision."})
        return attrs
