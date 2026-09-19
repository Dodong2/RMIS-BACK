from rest_framework import serializers
from accounts.models import User
from .models import Program, Project, Study, WorkPlanMilestone


class LeadSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email"]


def validate_lead_role(user, required_code):
    if not user.role or user.role.code != required_code:
        raise serializers.ValidationError(f"{user.email} does not have the {required_code} role.")


def validate_lead_concurrency(user, funding_type, queryset, exclude_pk, default_cap):
    qs = queryset.filter(lead=user, status="active")
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    cap = 1 if funding_type == "institutional" else default_cap
    count = qs.count()
    if count >= cap:
        raise serializers.ValidationError(
            f"{user.email} already leads {count} active record(s) under {funding_type} funding (limit is {cap})."
        )


class ProgramSerializer(serializers.ModelSerializer):
    lead_detail = LeadSerializer(source="lead", read_only=True)

    class Meta:
        model = Program
        fields = [
            "id", "code", "title", "funding_type", "rei_thrust",
            "lead", "lead_detail", "status", "start_date", "created_at",
        ]

    def validate(self, attrs):
        lead = attrs.get("lead", getattr(self.instance, "lead", None))
        funding_type = attrs.get("funding_type", getattr(self.instance, "funding_type", None))
        validate_lead_role(lead, "program_leader")
        validate_lead_concurrency(
            lead, funding_type, Program.objects.all(),
            self.instance.pk if self.instance else None, default_cap=2,
        )
        return attrs


class ProjectSerializer(serializers.ModelSerializer):
    lead_detail = LeadSerializer(source="lead", read_only=True)

    class Meta:
        model = Project
        fields = [
            "id", "program", "title", "project_code", "funding_type",
            "ntp_number", "ntp_date", "toe_signed_date", "is_dry_research",
            "lead", "lead_detail", "status", "start_date", "target_end_date",
            "rei_thrust", "created_at",
        ]

    def validate(self, attrs):
        lead = attrs.get("lead", getattr(self.instance, "lead", None))
        funding_type = attrs.get("funding_type", getattr(self.instance, "funding_type", None))
        validate_lead_role(lead, "project_leader")
        validate_lead_concurrency(
            lead, funding_type, Project.objects.all(),
            self.instance.pk if self.instance else None, default_cap=3,
        )
        return attrs


class StudySerializer(serializers.ModelSerializer):
    lead_detail = LeadSerializer(source="lead", read_only=True)

    class Meta:
        model = Study
        fields = ["id", "project", "title", "lead", "lead_detail", "status", "created_at"]

    def validate(self, attrs):
        lead = attrs.get("lead", getattr(self.instance, "lead", None))
        validate_lead_role(lead, "study_leader")
        return attrs


class WorkPlanMilestoneSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkPlanMilestone
        fields = ["id", "project", "title", "target_date", "status", "remarks", "created_at"]