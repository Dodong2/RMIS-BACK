from rest_framework import serializers

from .models import ProjectRisk, RiskUpdate
from .services import risk_band

# Spec section 16 authorized users: Project Leader, Research Director, Compliance Officer (mapped to our role codes).
RISK_REGISTER_ROLES = ["system_admin", "drd", "vprei", "crc_chair", "riuh", "program_leader", "project_leader"]


class ProjectRiskSerializer(serializers.ModelSerializer):
    score = serializers.IntegerField(read_only=True)
    level = serializers.SerializerMethodField()
    owner_email = serializers.EmailField(source="owner.email", read_only=True)

    class Meta:
        model = ProjectRisk
        fields = [
            "id", "project", "description", "category", "likelihood", "impact", "score", "level",
            "owner", "owner_email", "mitigation", "status", "created_by", "created_at", "updated_at",
        ]
        read_only_fields = ["created_by"]

    def get_level(self, obj):
        return risk_band(obj.score)[0]


class RiskUpdateSerializer(serializers.ModelSerializer):
    author_email = serializers.EmailField(source="author.email", read_only=True)

    class Meta:
        model = RiskUpdate
        fields = ["id", "risk", "note", "new_status", "author", "author_email", "created_at"]
        read_only_fields = ["risk", "author"]
