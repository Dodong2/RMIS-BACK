from rest_framework import serializers

from .models import PlanningTarget

# Seed source for the permission table (accounts/permission_seed.py); gates use permission codes.
MANAGE_ROLES = ["system_admin", "riuh", "drd", "vprei"]


class PlanningTargetSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanningTarget
        fields = ["id", "metric", "campus", "target_year", "target_value", "set_by", "created_at"]
        read_only_fields = ["set_by"]
