from rest_framework import serializers

from . import formula
from .models import (
    AHPMatrixRun, AHPPairwiseComparison, DecisionCriterion, DecisionRecord, FundingRecommendationRun, ProjectScore,
)

# Seed source for the permission table (accounts/permission_seed.py); gates use permission codes.
DSS_ROLES = ["system_admin", "vprei"]
DECISION_ROLES = DSS_ROLES + ["university_admin"]  # final approval: University President
DSS_VIEW_ROLES = ["system_admin", "vprei", "university_admin", "crc_chair"]  # client Task 76: who may open the DSS


class DecisionCriterionSerializer(serializers.ModelSerializer):
    class Meta:
        model = DecisionCriterion
        fields = ["id", "name", "metric_key", "description", "formula_mode", "custom_formula", "is_active", "created_at"]

    def validate(self, attrs):
        return validate_formula(attrs, self.instance)


def validate_formula(attrs, instance=None):
    mode = attrs.get("formula_mode", instance.formula_mode if instance else "standard")
    text = attrs.get("custom_formula", instance.custom_formula if instance else "")
    if mode == "custom":
        try:
            formula.validate(text)
        except ValueError as exc:
            raise serializers.ValidationError({"custom_formula": str(exc)})
        if "custom_formula" in attrs:
            attrs["custom_formula"] = formula.normalize(text)
    return attrs


class CriterionFormulaSerializer(serializers.ModelSerializer):
    """PATCH criteria/<id>/: only the scoring formula can change after an indicator is defined."""

    class Meta:
        model = DecisionCriterion
        fields = ["formula_mode", "custom_formula"]

    def validate(self, attrs):
        return validate_formula(attrs, self.instance)


class AHPPairwiseComparisonSerializer(serializers.ModelSerializer):
    class Meta:
        model = AHPPairwiseComparison
        fields = ["id", "run", "criterion_row", "criterion_col", "value"]


class AHPMatrixRunSerializer(serializers.ModelSerializer):
    comparisons = AHPPairwiseComparisonSerializer(many=True, read_only=True)

    class Meta:
        model = AHPMatrixRun
        fields = [
            "id", "label", "criteria", "created_by", "created_at", "status",
            "weights", "weight_source", "consistency_ratio", "is_consistent", "comparisons",
        ]
        read_only_fields = ["created_by", "status", "weights", "weight_source", "consistency_ratio", "is_consistent"]


class ProjectScoreSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectScore
        fields = ["id", "run", "project", "raw_scores", "normalized_scores", "composite_score", "rank"]


class FundingRecommendationRunSerializer(serializers.ModelSerializer):
    scores = ProjectScoreSerializer(many=True, read_only=True)

    class Meta:
        model = FundingRecommendationRun
        fields = [
            "id", "ahp_run", "label", "funding_type_filter", "campus_filter", "created_by", "created_at",
            "method", "weights_snapshot", "formulas_snapshot", "scores",
        ]
        read_only_fields = ["created_by", "method", "weights_snapshot", "formulas_snapshot"]


class DecisionRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = DecisionRecord
        fields = ["id", "run", "project", "decision", "indicative_amount", "rationale", "reference_number", "decided_by", "decided_at"]
        read_only_fields = ["run", "decided_by", "decided_at"]

    def validate_project(self, project):
        run = self.context["run"]
        if not run.scores.filter(project=project).exists():
            raise serializers.ValidationError("Project was not ranked in this recommendation run.")
        return project
