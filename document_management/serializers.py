import logging
import os
import re

import requests
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from .models import Document, DocumentShare
from .storage import get_signed_url, upload_document

logger = logging.getLogger(__name__)

# Seed source for the permission table (accounts/permission_seed.py); gates use permission codes.
MANAGE_ROLES = ["system_admin", "riuh"]
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25MB

# Checked by extension (browsers send inconsistent MIME types, e.g. CSV as application/vnd.ms-excel on Windows),
# and the mapped type is what gets sent to Supabase. Keep in sync with the research-documents bucket's
# "Allowed MIME types" setting in the Supabase dashboard, or the upload is rejected there.
ALLOWED_FILE_TYPES = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


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
        # A failed signing shouldn't turn an already-saved upload into a 500 (the user would retry and create a
        # duplicate version); the list/detail endpoints can sign it again later.
        try:
            return get_signed_url(obj.storage_path)
        except requests.RequestException:
            logger.exception("Could not sign a download URL for document %s", obj.pk)
            return None

    def validate(self, attrs):
        project = attrs.get("project", getattr(self.instance, "project", None))
        study = attrs.get("study", getattr(self.instance, "study", None))
        if study and study.project_id != project.id:
            raise serializers.ValidationError({"study": "Study does not belong to this project."})
        file_obj = attrs.get("file")
        if file_obj and file_obj.size > MAX_UPLOAD_BYTES:
            raise serializers.ValidationError({"file": f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit."})
        if file_obj and os.path.splitext(file_obj.name)[1].lower() not in ALLOWED_FILE_TYPES:
            raise serializers.ValidationError(
                {"file": f"Unsupported file type. Allowed: {', '.join(sorted(ALLOWED_FILE_TYPES))}."}
            )
        return attrs

    def create(self, validated_data):
        if "sensitivity" not in self.initial_data and validated_data["document_type"] == "lib":
            validated_data["sensitivity"] = "financial"
        file_obj = validated_data.pop("file")
        project = validated_data["project"]
        document_type = validated_data["document_type"]
        study = validated_data.get("study")
        content_type = ALLOWED_FILE_TYPES[os.path.splitext(file_obj.name)[1].lower()]

        siblings = Document.objects.filter(project=project, document_type=document_type, study=study)
        last_version = siblings.order_by("-version_number").first()
        validated_data["version_number"] = (last_version.version_number + 1) if last_version else 1

        # Upload first: if storage rejects the file, nothing in the DB has changed yet (the previous version
        # stays current) and the user gets a 400 instead of a 500.
        path = f"{project.project_code}/{document_type}/v{validated_data['version_number']}_{_safe_filename(file_obj.name)}"
        try:
            upload_document(file_obj, path, content_type)
        except requests.RequestException as exc:
            logger.exception("Document upload to storage failed for %s", path)
            detail = getattr(exc.response, "text", "") if exc.response is not None else str(exc)
            raise serializers.ValidationError({"file": f"The file storage rejected the upload: {detail[:200]}"})

        with transaction.atomic():
            siblings.filter(is_current=True).update(is_current=False)
            return Document.objects.create(
                storage_path=path,
                file_name=file_obj.name,
                file_size=file_obj.size,
                content_type=content_type,
                **validated_data,
            )


class DocumentShareSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)
    user_role = serializers.CharField(source="user.role.name", read_only=True, default=None)
    granted_by_email = serializers.EmailField(source="granted_by.email", read_only=True)
    is_active = serializers.SerializerMethodField()

    class Meta:
        model = DocumentShare
        fields = [
            "id", "document", "user", "user_email", "user_role", "reason", "expires_on",
            "granted_by", "granted_by_email", "granted_at", "revoked_by", "revoked_at", "is_active",
        ]
        read_only_fields = ["document", "granted_by", "revoked_by", "revoked_at"]

    def get_is_active(self, obj):
        return obj.revoked_at is None and obj.expires_on >= timezone.localdate()

    def validate_expires_on(self, value):
        if value < timezone.localdate():
            raise serializers.ValidationError("Expiry date can't be in the past.")
        return value

    def validate_user(self, user):
        if user.account_status != "active" or user.is_pending_role:
            raise serializers.ValidationError("Share only with an active, confirmed account.")
        return user
