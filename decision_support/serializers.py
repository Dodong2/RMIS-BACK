from rest_framework import serializers

from .models import (
    AHPMatrixRun, AHPPairwiseComparison, DecisionCriterion, DecisionRecord, FundingRecommendationRun, ProjectScore,
)

# Seed source for the permission table (accounts/permission_seed.py); gates use permission codes.
DSS_ROLES = ["system_admin", "drd", "vprei"]
DECISION_ROLES = DSS_ROLES + ["university_admin"]  # final approval: University President


class DecisionCriterionSerializer(serializers.ModelSerializer):
    class Meta:
        model = DecisionCriterion
        fields = ["id", "name", "metric_key", "description", "is_active", "created_at"]


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
            "weights", "consistency_ratio", "is_consistent", "comparisons",
        ]
        read_only_fields = ["created_by", "status", "weights", "consistency_ratio", "is_consistent"]


class ProjectScoreSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectScore
        fields = ["id", "run", "project", "raw_scores", "normalized_scores", "composite_score", "rank"]


class FundingRecommendationRunSerializer(serializers.ModelSerializer):
    scores = ProjectScoreSerializer(many=True, read_only=True)

    class Meta:
        model = FundingRecommendationRun
        fields = ["id", "ahp_run", "label", "funding_type_filter", "campus_filter", "created_by", "created_at", "scores"]
        read_only_fields = ["created_by"]


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
