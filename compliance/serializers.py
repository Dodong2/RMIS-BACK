from rest_framework import serializers

from .models import (
    AIUseDeclaration,
    ConflictOfInterestDisclosure,
    EthicsReviewReference,
    MisconductCaseReference,
    SimilarityCheckRecord,
)

MANAGE_ROLES = ["system_admin", "riuh"]


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
            "decision_date", "remarks", "recorded_by", "created_at",
        ]
        read_only_fields = ["recorded_by"]

    def validate(self, attrs):
        return validate_study_belongs_to_project(attrs, self.instance)


class SimilarityCheckRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = SimilarityCheckRecord
        fields = [
            "id", "project", "study", "document_type", "document_title", "similarity_index",
            "is_within_threshold", "software_used", "checked_on", "recorded_by", "created_at",
        ]
        read_only_fields = ["is_within_threshold", "recorded_by"]

    def validate(self, attrs):
        return validate_study_belongs_to_project(attrs, self.instance)


class AIUseDeclarationSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIUseDeclaration
        fields = [
            "id", "project", "study", "declared_by", "tool_name", "purpose",
            "extent", "declared_on", "created_at",
        ]
        read_only_fields = ["declared_by"]

    def validate(self, attrs):
        return validate_study_belongs_to_project(attrs, self.instance)


class ConflictOfInterestDisclosureSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConflictOfInterestDisclosure
        fields = [
            "id", "project", "discloser", "description", "mitigation_measures",
            "status", "disclosed_on", "recorded_by", "created_at",
        ]
        read_only_fields = ["recorded_by"]


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
