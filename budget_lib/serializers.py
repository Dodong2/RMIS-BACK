from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from accounts.permissions import ensure_in_scope
from .models import INSTITUTIONAL_DRY_RESEARCH_CAP, BudgetReview, LibItem, LineItem, LineItemBudget, allocation_periods

# Seed source for the permission table (accounts/permission_seed.py); gates use permission codes.
CERTIFY_ROLES = ["system_admin", "finance_budget"]
ENDORSE_ROLES = ["system_admin", "crc_chair"]
QUARTER_FIELDS = ["q1_amount", "q2_amount", "q3_amount", "q4_amount"]


def line_total(quantity, unit_cost):
    """Qty x Unit Cost, rounded to centavos."""
    return (Decimal(str(quantity)) * Decimal(str(unit_cost))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def catalog_item_name(category, description):
    """Client 2026-10-20: an LIB row's item is picked from the System Admin's active LIB Items of its class. Returns the
    catalog spelling, or raises."""
    item = LibItem.objects.filter(category=category, name__iexact=(description or "").strip(), is_active=True).first()
    if item is None:
        label = dict(LineItem.CATEGORY_CHOICES).get(category, category)
        raise serializers.ValidationError(
            {"description": f"'{description}' is not an active {label} item in System Admin > LIB Items."}
        )
    return item.name


class LibItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = LibItem
        fields = ["id", "category", "name", "uacs_code", "is_active", "created_at"]

    def validate(self, attrs):
        category = attrs.get("category", getattr(self.instance, "category", None))
        name = attrs.get("name", getattr(self.instance, "name", "")).strip()
        if not name:
            raise serializers.ValidationError({"name": "Enter the item."})
        others = LibItem.objects.exclude(pk=getattr(self.instance, "pk", None))
        if others.filter(category=category, name__iexact=name).exists():
            raise serializers.ValidationError({"name": f"{name} is already an item under this class."})
        return {**attrs, "name": name, "uacs_code": attrs.get("uacs_code", getattr(self.instance, "uacs_code", "")).strip()}


class LineItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = LineItem
        fields = [
            "id", "budget", "category", "description", "amount", "unit", "quantity", "unit_cost",
            "fiscal_year", "funding_source", "is_counterpart", "justification", "q1_amount", "q2_amount", "q3_amount", "q4_amount", "allocations", "is_app_flagged", "created_at",
        ]
        read_only_fields = ["is_app_flagged"]

    def validate(self, attrs):
        # A row stays in its LIB; otherwise moving it to a draft would take it out of a locked one (audit 2026-10-21).
        if self.instance is not None and "budget" in attrs and attrs["budget"].pk != self.instance.budget_id:
            raise serializers.ValidationError({"budget": "A line item can't be moved to another LIB."})
        budget = attrs.get("budget", getattr(self.instance, "budget", None))
        ensure_in_scope(self, budget.project)
        # Locked (and re-read) so an item can't slip into a LIB that is being certified at the same moment.
        budget = LineItemBudget.objects.select_for_update().get(pk=budget.pk)
        if budget.status not in LineItemBudget.EDITABLE_STATUSES:
            raise serializers.ValidationError(f"This LIB is {budget.get_status_display().lower()} and can no longer be edited.")
        category = attrs.get("category", getattr(self.instance, "category", None))
        description = attrs.get("description", getattr(self.instance, "description", ""))
        # Only a new row or a changed item is checked, so rows encoded before the catalog keep their text
        if self.instance is None or (category, description) != (self.instance.category, self.instance.description):
            attrs["description"] = catalog_item_name(category, description)
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


class BudgetReviewSerializer(serializers.ModelSerializer):
    acted_by_name = serializers.CharField(source="acted_by.display_name", read_only=True)

    class Meta:
        model = BudgetReview
        fields = ["id", "action", "remarks", "acted_by", "acted_by_name", "acted_at"]


class LineItemBudgetSerializer(serializers.ModelSerializer):
    line_items = LineItemSerializer(many=True, read_only=True)
    reviews = BudgetReviewSerializer(many=True, read_only=True)
    endorsed_by_name = serializers.CharField(source="endorsed_by.display_name", read_only=True, default=None)
    certified_by_name = serializers.CharField(source="certified_by.display_name", read_only=True, default=None)
    total_amount = serializers.SerializerMethodField()
    exceeds_dry_cap = serializers.SerializerMethodField()

    class Meta:
        model = LineItemBudget
        fields = [
            "id", "project", "version_number", "is_current", "status",
            "certified_by", "certified_at", "certified_by_name", "endorsed_by", "endorsed_at", "endorsed_by_name",
            "created_at", "line_items", "total_amount", "exceeds_dry_cap", "reviews",
        ]
        read_only_fields = ["version_number", "is_current", "status", "certified_by", "certified_at", "endorsed_by", "endorsed_at"]

    def get_total_amount(self, obj):
        return obj.line_items.aggregate(total=Sum("amount"))["total"] or 0

    def validate_project(self, project):
        ensure_in_scope(self, project)
        return project

    def get_exceeds_dry_cap(self, obj):
        """Warning only: institutional dry research over the Manual's P100k/year cap. Items split per project year
        (Y1Q1..YnQ4) count each year's four quarters together; other items count by fiscal year (one-year projects
        are a single year)."""
        project = obj.project
        if project.funding_type != "institutional" or not project.is_dry_research:
            return False
        per_year = defaultdict(Decimal)
        for item in obj.line_items.all():
            if item.allocations and item.allocations[0]["period"].startswith("Y"):
                for row in item.allocations:
                    per_year[row["period"].split("Q")[0]] += Decimal(row["amount"])
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


def total_cost_problem(budget):
    """Why this LIB can't move on (client 2026-10-18: Grand Total must equal Total Project/Study Cost, checked on the
    server too), or None. Same rule as the registration wizard: an empty LIB is refused; no Total Cost skips the check."""
    total = budget.line_items.aggregate(total=Sum("amount"))["total"]
    if total is None:
        return "This LIB has no line items."
    cost = budget.project.total_cost
    if cost is not None and total != cost:
        return f"The LIB Grand Total ({total:,.2f}) must equal the Total Project/Study Cost ({cost:,.2f})."
    return None


def review_budget(budget, user, action, remarks=""):
    """Move a LIB one step along the endorsement chain and keep the step in its history. Caller has locked the row
    and checked the current status and the user's right to take this step."""
    now = timezone.now()
    budget.status = {"endorsed": "endorsed", "returned": "returned", "resubmitted": "draft", "certified": "certified"}[action]
    if action == "endorsed":
        budget.endorsed_by, budget.endorsed_at = user, now
    elif action == "certified":
        budget.certified_by, budget.certified_at = user, now
    elif action == "resubmitted":
        budget.endorsed_by, budget.endorsed_at = None, None
    budget.save(update_fields=["status", "endorsed_by", "endorsed_at", "certified_by", "certified_at"])
    BudgetReview.objects.create(budget=budget, action=action, remarks=remarks, acted_by=user)
    return budget
