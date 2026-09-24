from datetime import timedelta

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from budget_lib.models import LineItem
from accounts.permissions import scoped_projects
from .models import APPLIED_STATUSES, BudgetRealignment, Disbursement, ProcurementRequest

REALIGNMENT_REQUEST_ROLES = ["system_admin", "project_leader"]
REALIGNMENT_MAJOR_REVIEW_ROLES = ["system_admin", "university_admin"]
REALIGNMENT_BOR_REVIEW_ROLES = ["system_admin"]  # client-confirmed: BOR-tier approval is system_admin only
DISBURSEMENT_ROLES = ["system_admin", "finance_budget"]
PROCUREMENT_REQUEST_ROLES = ["system_admin", "program_leader", "project_leader"]  # "signed by the Lead Proponent"
PROCUREMENT_STATUS_ROLES = ["system_admin", "procurement_officer_lib"]

MINOR_TIER_MAX_PCT = 33
MAJOR_TIER_MAX_PCT = 100
REALIGNMENT_MIN_LEAD_DAYS = 60  # "at least two (2) months before the end of the project"


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


class DisbursementSerializer(serializers.ModelSerializer):
    funding_source = serializers.CharField(source="line_item.funding_source", read_only=True)

    class Meta:
        model = Disbursement
        fields = [
            "id", "line_item", "amount", "reference_number", "description", "payee", "supporting_document",
            "funding_source", "disbursed_on", "recorded_by", "created_at",
        ]
        read_only_fields = ["recorded_by"]

    def validate(self, attrs):
        line_item = attrs.get("line_item", getattr(self.instance, "line_item", None))
        document = attrs.get("supporting_document", getattr(self.instance, "supporting_document", None))
        if document and document.project_id != line_item.budget.project_id:
            raise serializers.ValidationError({"supporting_document": "Document belongs to a different project."})
        amount = attrs.get("amount", getattr(self.instance, "amount", None))
        if line_item.budget.status != "certified":
            raise serializers.ValidationError("Disbursements can only be recorded against a certified budget.")
        balance = line_item_balance(line_item)
        available = balance["available"] + (self.instance.amount if self.instance else 0)
        if amount > available:
            raise serializers.ValidationError(
                f"Amount {amount} exceeds the available balance ({available}) for this line item."
            )
        return attrs


class RealignmentReviewSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["approved", "rejected"])
    bor_resolution_number = serializers.CharField(required=False, allow_blank=True)


class BudgetRealignmentSerializer(serializers.ModelSerializer):
    tier = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)

    class Meta:
        model = BudgetRealignment
        fields = [
            "id", "from_line_item", "to_line_item", "new_item_category", "new_item_description",
            "amount", "tier", "status", "justification", "requested_by",
            "reviewed_by", "reviewed_at", "bor_resolution_number", "created_at",
        ]
        read_only_fields = ["requested_by", "reviewed_by", "reviewed_at", "bor_resolution_number"]

    def validate(self, attrs):
        from_item = attrs.get("from_line_item", getattr(self.instance, "from_line_item", None))
        validate_in_scope(self, from_item)
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

        project = from_item.budget.project
        if from_item.budget.status != "certified":
            raise serializers.ValidationError("Realignments can only be requested against a certified budget.")
        if to_item and to_item.budget_id != from_item.budget_id:
            raise serializers.ValidationError("from_line_item and to_line_item must belong to the same budget.")
        if to_item and to_item.pk == from_item.pk:
            raise serializers.ValidationError("from_line_item and to_line_item must be different.")

        if project.target_end_date:
            deadline = project.target_end_date - timedelta(days=REALIGNMENT_MIN_LEAD_DAYS)
            if timezone.localdate() > deadline:
                raise serializers.ValidationError(
                    f"Realignment requests must be submitted at least {REALIGNMENT_MIN_LEAD_DAYS} days "
                    "before the project's target end date."
                )

        already_requested = BudgetRealignment.objects.filter(
            from_line_item__budget__project=project, created_at__year=timezone.localdate().year,
        ).exclude(status="rejected")
        if self.instance:
            already_requested = already_requested.exclude(pk=self.instance.pk)
        if already_requested.exists():
            raise serializers.ValidationError(
                "This project has already requested a budget realignment this calendar year."
            )

        available = line_item_balance(from_item)["available"]
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
        tier = validated_data["tier"]
        validated_data["status"] = {
            "minor": "implemented", "major": "pending_approval", "bor": "pending_bor",
        }[tier]
        return BudgetRealignment.objects.create(**validated_data)


def review_realignment(realignment, reviewer, decision, bor_resolution_number=""):
    """Approve/reject a major or BOR-tier realignment. Caller must have checked it's still pending."""
    with transaction.atomic():
        if decision == "rejected":
            realignment.status = "rejected"
        elif realignment.tier == "major":
            realignment.status = "approved"
        else:  # bor
            if not bor_resolution_number:
                raise serializers.ValidationError({"bor_resolution_number": "Required to record Board of Regents approval."})
            if not realignment.to_line_item_id:
                realignment.to_line_item = LineItem.objects.create(
                    budget=realignment.from_line_item.budget,
                    category=realignment.new_item_category,
                    description=realignment.new_item_description,
                    amount=realignment.amount,
                )
            realignment.bor_resolution_number = bor_resolution_number
            realignment.status = "bor_approved"
        realignment.reviewed_by = reviewer
        realignment.reviewed_at = timezone.now()
        realignment.save(update_fields=["status", "to_line_item", "bor_resolution_number", "reviewed_by", "reviewed_at"])
    return realignment


def validate_in_scope(serializer, line_item):
    """Leaders may only file requests against projects in their own scope."""
    request = serializer.context.get("request")
    projects = scoped_projects(request.user) if request else None
    if projects is not None and not projects.filter(pk=line_item.budget.project_id).exists():
        raise serializers.ValidationError("This line item belongs to a project outside your scope.")


class ProcurementRequestSerializer(serializers.ModelSerializer):
    project = serializers.IntegerField(source="line_item.budget.project_id", read_only=True)
    routed_to = serializers.CharField(read_only=True)

    class Meta:
        model = ProcurementRequest
        fields = [
            "id", "project", "line_item", "description", "amount", "fiscal_year", "quarter", "routed_to",
            "status", "remarks", "requested_by", "requested_at", "processing_at", "released_at", "updated_by",
        ]
        read_only_fields = ["status", "requested_by", "requested_at", "processing_at", "released_at", "updated_by"]

    def validate(self, attrs):
        line_item = attrs["line_item"]
        validate_in_scope(self, line_item)
        if line_item.budget.status != "certified":
            raise serializers.ValidationError("Procurement can only be requested against a certified budget.")
        open_requests = line_item.procurement_requests.exclude(status__in=("released", "cancelled"))
        committed = open_requests.aggregate(total=Sum("amount"))["total"] or 0
        available = line_item_balance(line_item)["available"] - committed
        if attrs["amount"] > available:
            raise serializers.ValidationError(
                f"Amount {attrs['amount']} exceeds what is still available on this line item ({available})."
            )
        return attrs


PROCUREMENT_TRANSITIONS = {"requested": ("processing", "cancelled"), "processing": ("released", "cancelled")}


class ProcurementStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["processing", "released", "cancelled"])
    remarks = serializers.CharField(required=False, allow_blank=True)

    def validate_status(self, value):
        current = self.context["procurement"].status
        if value not in PROCUREMENT_TRANSITIONS.get(current, ()):
            raise serializers.ValidationError(f"Cannot move a '{current}' request to '{value}'.")
        return value
