from rest_framework import serializers

from .models import BudgetOfficeImport, BudgetOfficeRecord

SYNC_ROLES = ["system_admin", "finance_budget"]


class BudgetOfficeImportSerializer(serializers.ModelSerializer):
    file = serializers.FileField(write_only=True)
    record_count = serializers.IntegerField(source="records.count", read_only=True)

    class Meta:
        model = BudgetOfficeImport
        fields = ["id", "file", "file_name", "uploaded_by", "uploaded_at", "record_count"]
        read_only_fields = ["file_name", "uploaded_by"]

    def validate_file(self, value):
        if not value.name.lower().endswith(".xlsx"):
            raise serializers.ValidationError("Upload the Budget Office workbook as .xlsx.")
        return value


class BudgetOfficeRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = BudgetOfficeRecord
        fields = [
            "id", "source", "sheet_name", "title", "leader_name", "implementing_unit",
            "mooe_total", "co_total", "grand_total", "project", "match_method",
        ]
        read_only_fields = [f for f in fields if f != "project"]

    def update(self, instance, validated_data):
        instance.project = validated_data.get("project")
        instance.match_method = "manual" if instance.project else ""
        instance.save(update_fields=["project", "match_method"])
        return instance
