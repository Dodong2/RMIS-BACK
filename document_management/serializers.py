import re

from rest_framework import serializers

from .models import Document
from .storage import get_signed_url, upload_document

# Seed source for the permission table (accounts/permission_seed.py); gates use permission codes.
MANAGE_ROLES = ["system_admin", "riuh"]
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25MB


def _safe_filename(name):
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


class DocumentListSerializer(serializers.ModelSerializer):
    """Lighter serializer for list views — skips the signed-URL call per row."""

    class Meta:
        model = Document
        fields = [
            "id", "project", "study", "document_type", "stage", "sensitivity", "version_number", "is_current",
            "file_name", "file_size", "content_type",
            "is_archived", "retention_until", "uploaded_by", "uploaded_at",
            "review_status", "review_remarks", "reviewed_by", "reviewed_at",
        ]


class DocumentSerializer(serializers.ModelSerializer):
    file = serializers.FileField(write_only=True)
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = [
            "id", "project", "study", "document_type", "stage", "sensitivity", "version_number", "is_current",
            "file", "file_name", "file_size", "content_type", "download_url",
            "is_archived", "retention_until", "uploaded_by", "uploaded_at",
            "review_status", "review_remarks", "reviewed_by", "reviewed_at",
        ]
        read_only_fields = [
            "version_number", "is_current", "file_name", "file_size", "content_type",
            "is_archived", "retention_until", "uploaded_by",
            "review_status", "review_remarks", "reviewed_by", "reviewed_at",
        ]

    def get_download_url(self, obj):
        return get_signed_url(obj.storage_path)

    def validate(self, attrs):
        project = attrs.get("project", getattr(self.instance, "project", None))
        study = attrs.get("study", getattr(self.instance, "study", None))
        if study and study.project_id != project.id:
            raise serializers.ValidationError({"study": "Study does not belong to this project."})
        file_obj = attrs.get("file")
        if file_obj and file_obj.size > MAX_UPLOAD_BYTES:
            raise serializers.ValidationError({"file": f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit."})
        return attrs

    def create(self, validated_data):
        if "sensitivity" not in self.initial_data and validated_data["document_type"] == "lib":
            validated_data["sensitivity"] = "financial"
        file_obj = validated_data.pop("file")
        project = validated_data["project"]
        document_type = validated_data["document_type"]
        study = validated_data.get("study")

        siblings = Document.objects.filter(project=project, document_type=document_type, study=study)
        last_version = siblings.order_by("-version_number").first()
        validated_data["version_number"] = (last_version.version_number + 1) if last_version else 1
        siblings.filter(is_current=True).update(is_current=False)

        path = f"{project.project_code}/{document_type}/v{validated_data['version_number']}_{_safe_filename(file_obj.name)}"
        upload_document(file_obj, path)

        return Document.objects.create(
            storage_path=path,
            file_name=file_obj.name,
            file_size=file_obj.size,
            content_type=file_obj.content_type or "",
            **validated_data,
        )
