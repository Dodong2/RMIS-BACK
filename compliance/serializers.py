from django.utils import timezone
from rest_framework import serializers

from .models import (
    AI_CONTENT_THRESHOLD,
    ComplianceRequirement,
    AIUseDeclaration,
    ConflictOfInterestDisclosure,
    EthicsReviewReference,
    MisconductCaseReference,
    SimilarityCheckRecord,
)

# Seed source for the permission table (accounts/permission_seed.py); gates use permission codes.
MANAGE_ROLES = ["system_admin", "riuh"]
# Leaders encode compliance records; RIUH verifies (client clarification Q1a).
ENCODE_ROLES = MANAGE_ROLES + ["program_leader", "project_leader", "study_leader"]


def validate_study_belongs_to_project(attrs, instance):
    project = attrs.get("project", getattr(instance, "project", None))
    study = attrs.get("study", getattr(instance, "study", None))
    if study and project and study.project_id != project.id:
        raise serializers.ValidationError({"study": "Study does not belong to this project."})
    return attrs


class EthicsReviewReferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = EthicsReviewReference
        fields = [
            "id", "project", "study", "review_body", "reference_number", "status",
            "decision_date", "remarks", "recorded_by", "created_at", "verified_by", "verified_at",
        ]
        read_only_fields = ["recorded_by", "verified_by", "verified_at"]

    def validate(self, attrs):
        return validate_study_belongs_to_project(attrs, self.instance)


class SimilarityCheckRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = SimilarityCheckRecord
        fields = [
            "id", "project", "study", "document_type", "document_title", "similarity_index",
            "is_within_threshold", "software_used", "checked_on", "recorded_by", "created_at", "verified_by", "verified_at",
        ]
        read_only_fields = ["is_within_threshold", "recorded_by", "verified_by", "verified_at"]

    def validate(self, attrs):
        return validate_study_belongs_to_project(attrs, self.instance)


class AIUseDeclarationSerializer(serializers.ModelSerializer):
    exceeds_ai_threshold = serializers.SerializerMethodField()

    def get_exceeds_ai_threshold(self, obj):
        return obj.ai_content_pct is not None and obj.ai_content_pct > AI_CONTENT_THRESHOLD

    def validate_ai_content_pct(self, value):
        if value is not None and not 0 <= value <= 100:
            raise serializers.ValidationError("Must be between 0 and 100.")
        return value

    class Meta:
        model = AIUseDeclaration
        fields = [
            "id", "project", "study", "declared_by", "tool_name", "purpose",
            "extent", "ai_content_pct", "exceeds_ai_threshold", "declared_on", "created_at", "verified_by", "verified_at",
        ]
        read_only_fields = ["declared_by", "verified_by", "verified_at"]

    def validate(self, attrs):
        return validate_study_belongs_to_project(attrs, self.instance)


class ConflictOfInterestDisclosureSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConflictOfInterestDisclosure
        fields = [
            "id", "project", "discloser", "description", "mitigation_measures",
            "status", "disclosed_on", "recorded_by", "created_at", "verified_by", "verified_at",
        ]
        read_only_fields = ["recorded_by", "verified_by", "verified_at"]


class MisconductCaseReferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = MisconductCaseReference
        fields = [
            "id", "project", "subject", "subject_name", "case_type", "referred_to",
            "status", "remarks", "reported_by", "reported_on", "resolved_on", "created_at",
        ]
        read_only_fields = ["reported_by"]

    def validate(self, attrs):
        subject = attrs.get("subject", getattr(self.instance, "subject", None))
        subject_name = attrs.get("subject_name", getattr(self.instance, "subject_name", ""))
        if not subject and not subject_name:
            raise serializers.ValidationError("Provide either subject (system user) or subject_name.")
        return attrs


class ComplianceRequirementSerializer(serializers.ModelSerializer):
    is_overdue = serializers.SerializerMethodField()

    class Meta:
        model = ComplianceRequirement
        fields = [
            "id", "project", "title", "description", "responsible", "deadline", "status", "is_overdue",
            "document", "submitted_at", "review_remarks", "reviewed_by", "reviewed_at", "created_by", "created_at",
        ]
        read_only_fields = ["status", "submitted_at", "review_remarks", "reviewed_by", "reviewed_at", "created_by"]

    def get_is_overdue(self, obj):
        return obj.status in ("pending", "returned") and obj.deadline < timezone.localdate()

    def validate(self, attrs):
        project = attrs.get("project", getattr(self.instance, "project", None))
        document = attrs.get("document", getattr(self.instance, "document", None))
        if document and document.project_id != project.id:
            raise serializers.ValidationError({"document": "Document belongs to a different project."})
        return attrs
