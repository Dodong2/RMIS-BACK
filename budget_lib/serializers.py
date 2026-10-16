from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from accounts.permissions import ensure_in_scope
from .models import INSTITUTIONAL_DRY_RESEARCH_CAP, LineItem, LineItemBudget, allocation_periods

# Seed source for the permission table (accounts/permission_seed.py); gates use permission codes.
CERTIFY_ROLES = ["system_admin", "finance_budget"]
QUARTER_FIELDS = ["q1_amount", "q2_amount", "q3_amount", "q4_amount"]


def line_total(quantity, unit_cost):
    """Qty x Unit Cost, rounded to centavos."""
    return (Decimal(str(quantity)) * Decimal(str(unit_cost))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class LineItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = LineItem
        fields = [
            "id", "budget", "category", "description", "amount", "unit", "quantity", "unit_cost",
            "fiscal_year", "funding_source", "is_counterpart", "justification", "q1_amount", "q2_amount", "q3_amount", "q4_amount", "allocations", "is_app_flagged", "created_at",
        ]
        read_only_fields = ["is_app_flagged"]

    def validate(self, attrs):
        budget = attrs.get("budget", getattr(self.instance, "budget", None))
        ensure_in_scope(self, budget.project)
        # Locked (and re-read) so an item can't slip into a LIB that is being certified at the same moment.
        budget = LineItemBudget.objects.select_for_update().get(pk=budget.pk)
        if budget.status == "certified":
            raise serializers.ValidationError("This budget is certified and can no longer be edited.")
        quarters = [attrs.get(f, getattr(self.instance, f, None)) for f in QUARTER_FIELDS]
        amount = attrs.get("amount", getattr(self.instance, "amount", None))
        if any(q is not None for q in quarters) and sum(q or 0 for q in quarters) != amount:
            raise serializers.ValidationError({"amount": "QTR1-QTR4 amounts must add up to the line item amount."})
        quantity = attrs.get("quantity", getattr(self.instance, "quantity", None))
        unit_cost = attrs.get("unit_cost", getattr(self.instance, "unit_cost", None))
        if quantity is not None and unit_cost is not None and line_total(quantity, unit_cost) != amount:
            raise serializers.ValidationError({"amount": "Total must equal Qty x Unit Cost."})
        allocations = attrs.get("allocations", getattr(self.instance, "allocations", None) or [])
        if allocations or self.context.get("require_allocations"):
            attrs["allocations"] = clean_allocations(allocations, allocation_periods(budget.project), amount)
        return attrs


def clean_allocations(allocations, periods, amount):
    """Per-year (Y1..Yn) or per-quarter (Q1-Q4) split of a line item (client meeting 2026-10-14). Returns every
    period in order, missing ones as 0.00, and refuses unknown periods or a split that doesn't add up to the amount."""
    if periods is None:
        raise serializers.ValidationError({"allocations": "Set the project's start and target end dates first."})
    if not isinstance(allocations, list):
        raise serializers.ValidationError({"allocations": "Send a list of {period, amount}."})
    by_period = {}
    for row in allocations:
        period = row.get("period") if isinstance(row, dict) else None
        if period not in periods or period in by_period:
            raise serializers.ValidationError({"allocations": f"Use each of {', '.join(periods)} at most once."})
        try:
            value = Decimal(str(row.get("amount") or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except InvalidOperation:
            raise serializers.ValidationError({"allocations": f"{period} amount is not a number."})
        if value < 0:
            raise serializers.ValidationError({"allocations": f"{period} amount can't be negative."})
        by_period[period] = value
    if sum(by_period.values()) != amount:
        raise serializers.ValidationError({"allocations": f"{' + '.join(periods)} must add up to the line item total ({amount})."})
    return [{"period": p, "amount": str(by_period.get(p, Decimal("0.00")))} for p in periods]


class LineItemBudgetSerializer(serializers.ModelSerializer):
    line_items = LineItemSerializer(many=True, read_only=True)
    total_amount = serializers.SerializerMethodField()
    exceeds_dry_cap = serializers.SerializerMethodField()

    class Meta:
        model = LineItemBudget
        fields = [
            "id", "project", "version_number", "is_current", "status",
            "certified_by", "certified_at", "created_at", "line_items", "total_amount", "exceeds_dry_cap",
        ]
        read_only_fields = ["version_number", "is_current", "status", "certified_by", "certified_at"]

    def get_total_amount(self, obj):
        return obj.line_items.aggregate(total=Sum("amount"))["total"] or 0

    def validate_project(self, project):
        ensure_in_scope(self, project)
        return project

    def get_exceeds_dry_cap(self, obj):
        """Warning only: institutional dry research over the Manual's P100k/year cap. Items split per year (Y1..Yn)
        count each year's allocation; other items count by fiscal year (one-year projects are a single year)."""
        project = obj.project
        if project.funding_type != "institutional" or not project.is_dry_research:
            return False
        per_year = defaultdict(Decimal)
        for item in obj.line_items.all():
            if item.allocations and item.allocations[0]["period"].startswith("Y"):
                for row in item.allocations:
                    per_year[row["period"]] += Decimal(row["amount"])
            else:
                per_year[item.fiscal_year] += item.amount
        return any(total > INSTITUTIONAL_DRY_RESEARCH_CAP for total in per_year.values())

    def create(self, validated_data):
        project = validated_data["project"]
        type(project).objects.select_for_update().get(pk=project.pk)  # one version number per project at a time
        last_version = LineItemBudget.objects.filter(project=project).order_by("-version_number").first()
        validated_data["version_number"] = (last_version.version_number + 1) if last_version else 1
        LineItemBudget.objects.filter(project=project, is_current=True).update(is_current=False)
        return LineItemBudget.objects.create(**validated_data)


def certify_budget(budget, user):
    """Certify a draft budget. Caller must have checked budget.status == 'draft'."""
    budget.status = "certified"
    budget.certified_by = user
    budget.certified_at = timezone.now()
    budget.save(update_fields=["status", "certified_by", "certified_at"])
    return budget
