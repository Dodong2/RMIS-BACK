from rest_framework import serializers

from .models import GeneratedReportLog


class GeneratedReportLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeneratedReportLog
        fields = ["id", "report_type", "format", "filters", "generated_by", "generated_at"]
