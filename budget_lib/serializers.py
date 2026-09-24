from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from .models import INSTITUTIONAL_DRY_RESEARCH_CAP, LineItem, LineItemBudget

CERTIFY_ROLES = ["system_admin", "finance_budget"]


class LineItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = LineItem
        fields = [
            "id", "budget", "category", "description", "amount", "fiscal_year", "funding_source", "is_counterpart",
            "is_app_flagged", "created_at",
        ]
        read_only_fields = ["is_app_flagged"]

    def validate(self, attrs):
        budget = attrs.get("budget", getattr(self.instance, "budget", None))
        if budget.status == "certified":
            raise serializers.ValidationError("This budget is certified and can no longer be edited.")
        return attrs


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

    def get_exceeds_dry_cap(self, obj):
        """Warning only: institutional dry research over the Manual's P100k/year cap (per fiscal year if set)."""
        project = obj.project
        if project.funding_type != "institutional" or not project.is_dry_research:
            return False
        per_year = obj.line_items.values("fiscal_year").annotate(total=Sum("amount"))
        return any(row["total"] > INSTITUTIONAL_DRY_RESEARCH_CAP for row in per_year)

    def create(self, validated_data):
        project = validated_data["project"]
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
