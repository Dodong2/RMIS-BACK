from rest_framework import serializers
from accounts.models import User
from .models import Program, Project, ProjectStatusHistory, Study, WorkPlanMilestone


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
            "rei_thrust", "is_continuing", "research_type", "sector", "sector_other",
            "research_priority_area", "research_typology", "sdgs", "campus",
            "implementing_unit", "cooperating_agencies", "total_cost",
            "description", "objectives", "beneficiaries", "expected_outcomes", "expected_impacts",
            "proposal_submitted_on", "proposal_reviewed_on", "proposal_approved_on", "reviewing_body",
            "created_at",
        ]

    def validate_sdgs(self, value):
        if not isinstance(value, list) or any(
            not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= 17 for n in value
        ):
            raise serializers.ValidationError("sdgs must be a list of integers from 1 to 17.")
        return sorted(set(value))

    def validate_research_typology(self, value):
        valid = {code for code, _ in Project.TYPOLOGY_CHOICES}
        if not isinstance(value, list) or not set(value) <= valid:
            raise serializers.ValidationError(f"research_typology must be a list of: {', '.join(sorted(valid))}.")
        return value

    def validate(self, attrs):
        lead = attrs.get("lead", getattr(self.instance, "lead", None))
        funding_type = attrs.get("funding_type", getattr(self.instance, "funding_type", None))
        sector = attrs.get("sector", getattr(self.instance, "sector", ""))
        sector_other = attrs.get("sector_other", getattr(self.instance, "sector_other", ""))
        if not attrs.get("sdgs", getattr(self.instance, "sdgs", [])):
            raise serializers.ValidationError({"sdgs": "Select at least one Sustainable Development Goal."})
        if not sector:
            raise serializers.ValidationError({"sector": "This field is required."})
        if sector == "others" and not sector_other:
            raise serializers.ValidationError({"sector_other": "Specify the sector when 'others' is selected."})
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
    responsible_detail = LeadSerializer(source="responsible", read_only=True)

    class Meta:
        model = WorkPlanMilestone
        fields = [
            "id", "project", "title", "start_date", "target_date", "status", "objective", "deliverable",
            "responsible", "responsible_detail", "remarks", "created_at",
        ]

    def validate(self, attrs):
        start = attrs.get("start_date", getattr(self.instance, "start_date", None))
        target = attrs.get("target_date", getattr(self.instance, "target_date", None))
        if start and target and start > target:
            raise serializers.ValidationError({"start_date": "Start date cannot be after the target date."})
        return attrs


class ProjectStatusHistorySerializer(serializers.ModelSerializer):
    changed_by_email = serializers.EmailField(source="changed_by.email", read_only=True)

    class Meta:
        model = ProjectStatusHistory
        fields = ["id", "project", "from_status", "to_status", "remarks", "changed_by", "changed_by_email", "changed_at"]
