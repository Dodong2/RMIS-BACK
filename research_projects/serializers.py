from rest_framework import serializers
from accounts.models import User
from accounts.permissions import LEADER_ROLES, ensure_in_scope, scoped_projects
from .models import Program, Project, ProjectStatusHistory, ProjectTeamMember, Study, TargetBeneficiary, WorkPlanMilestone


class LeadSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email"]


def validate_lead_role(user, required_code):
    if not user.role or user.role.code != required_code:
        raise serializers.ValidationError(f"{user.email} does not have the {required_code} role.")


def leader_owns(user, project=None, leads=()):
    """A leader is part of a record if they are one of `leads` (its own or its parent's leader) or `project` is
    already in their scope (they lead it, its program, or one of its studies)."""
    return user in leads or (project is not None and scoped_projects(user).filter(pk=project.pk).exists())


def ensure_registrant_in_scope(serializer, project=None, leads=()):
    """projects.register includes the leaders (Module Structure M2), but they may only register/edit records
    they are part of. Other roles fall back to ensure_in_scope for existing projects. The Excel importer sets
    context["defer_scope"] and checks the finished project instead, since its studies are saved after it."""
    request = serializer.context.get("request")
    if request is None or serializer.context.get("defer_scope"):
        return
    user = request.user
    if not (user.role and user.role.code in LEADER_ROLES):
        if project is not None:
            ensure_in_scope(serializer, project)
        return
    if not leader_owns(user, project, leads):
        raise serializers.ValidationError("Leaders can only register or edit records they lead or belong to.")


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
        ensure_registrant_in_scope(self, leads=[lead, getattr(self.instance, "lead", None)])
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
            "lead", "lead_detail", "lead_gender", "contact_number", "status", "start_date", "target_end_date",
            "rei_thrust", "is_continuing", "continuing_year", "research_type", "sectors", "sector_other",
            "research_priority_area", "research_typology", "sdgs", "campus", "college",
            "implementing_unit", "cooperating_agencies", "total_cost",
            "background", "objectives", "methodology", "socio_economic_significance", "monitoring_evaluation",
            "references", "description", "beneficiaries", "expected_outcomes", "expected_impacts",
            "proposal_submitted_on", "proposal_reviewed_on", "proposal_approved_on", "reviewing_body",
            "endorsed_by_dean", "endorsed_by_dean_on", "noted_by_rds_director", "noted_by_rds_director_on",
            "recommended_by_campus_director", "recommended_by_campus_director_on",
            "recommended_by_vprde", "recommended_by_vprde_on", "approved_by_president",
            "created_at",
        ]

    def validate_sdgs(self, value):
        if not isinstance(value, list) or any(
            not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= 17 for n in value
        ):
            raise serializers.ValidationError("sdgs must be a list of integers from 1 to 17.")
        return sorted(set(value))

    def validate_sectors(self, value):
        valid = {code for code, _ in Project.SECTOR_CHOICES}
        if not isinstance(value, list) or not set(value) <= valid:
            raise serializers.ValidationError(f"sectors must be a list of: {', '.join(sorted(valid))}.")
        return sorted(set(value))

    def validate_research_typology(self, value):
        valid = {code for code, _ in Project.TYPOLOGY_CHOICES}
        if not isinstance(value, list) or not set(value) <= valid:
            raise serializers.ValidationError(f"research_typology must be a list of: {', '.join(sorted(valid))}.")
        return value

    def validate(self, attrs):
        lead = attrs.get("lead", getattr(self.instance, "lead", None))
        funding_type = attrs.get("funding_type", getattr(self.instance, "funding_type", None))
        sectors = attrs.get("sectors", getattr(self.instance, "sectors", []))
        sector_other = attrs.get("sector_other", getattr(self.instance, "sector_other", ""))
        is_continuing = attrs.get("is_continuing", getattr(self.instance, "is_continuing", False))
        continuing_year = attrs.get("continuing_year", getattr(self.instance, "continuing_year", None))
        if not attrs.get("sdgs", getattr(self.instance, "sdgs", [])):
            raise serializers.ValidationError({"sdgs": "Select at least one Sustainable Development Goal."})
        if not sectors:
            raise serializers.ValidationError({"sectors": "Select at least one sector."})
        if "others" in sectors and not sector_other:
            raise serializers.ValidationError({"sector_other": "Specify the sector when 'others' is selected."})
        if is_continuing and (continuing_year or 0) < 2:
            raise serializers.ValidationError({"continuing_year": "A continuing proposal needs its year (2 or later)."})
        validate_lead_role(lead, "project_leader")
        program = attrs.get("program", getattr(self.instance, "program", None))
        ensure_registrant_in_scope(self, self.instance, leads=[lead, program.lead if program else None])
        validate_lead_concurrency(
            lead, funding_type, Project.objects.all(),
            self.instance.pk if self.instance else None, default_cap=3,
        )
        return attrs


class ProjectTeamMemberSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectTeamMember
        fields = ["id", "project", "member_role", "name", "gender", "user"]

    def validate(self, attrs):
        ensure_registrant_in_scope(self, attrs.get("project", getattr(self.instance, "project", None)))
        return attrs


class TargetBeneficiarySerializer(serializers.ModelSerializer):
    class Meta:
        model = TargetBeneficiary
        fields = ["id", "project", "group", "description", "total"]

    def validate(self, attrs):
        ensure_registrant_in_scope(self, attrs.get("project", getattr(self.instance, "project", None)))
        return attrs


class StudySerializer(serializers.ModelSerializer):
    lead_detail = LeadSerializer(source="lead", read_only=True)

    class Meta:
        model = Study
        fields = ["id", "project", "title", "lead", "lead_detail", "status", "created_at"]

    def validate(self, attrs):
        lead = attrs.get("lead", getattr(self.instance, "lead", None))
        project = attrs.get("project", getattr(self.instance, "project", None))
        validate_lead_role(lead, "study_leader")
        program_lead = project.program.lead if project.program else None
        ensure_registrant_in_scope(self, project, leads=[lead, project.lead, program_lead])
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
        ensure_in_scope(self, attrs.get("project", getattr(self.instance, "project", None)))
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
