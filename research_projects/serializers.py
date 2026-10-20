import re

from django.utils.text import slugify
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from accounts.models import Role, User
from accounts.permissions import LEADER_ROLES, acting_for, ensure_in_scope, scoped_projects
from .models import (
    CollegeUnit, CooperatingAgency, EndorserChoice, FundingType, Program, RdeThrust, Project, ProjectEndorser, ProjectStatusHistory, ProjectTeamMember, Study, TargetBeneficiary, WorkPlanMilestone,
)


class AdminChoiceSerializer(serializers.ModelSerializer):
    class Meta:
        fields = ["id", "name", "created_at"]

    def validate_name(self, value):
        value = value.strip()
        model = self.Meta.model
        if model.objects.filter(name__iexact=value).exclude(pk=getattr(self.instance, "pk", None)).exists():
            raise serializers.ValidationError(f"This {model._meta.verbose_name} already exists.")
        return value


class CodedChoiceSerializer(AdminChoiceSerializer):
    """Code + title in, combined `name` out (see CodedChoice)."""

    code = serializers.CharField(max_length=20)
    title = serializers.CharField(max_length=100)

    class Meta(AdminChoiceSerializer.Meta):
        fields = ["id", "code", "title", "name", "created_at"]
        read_only_fields = ["name"]

    def validate(self, attrs):
        model = self.Meta.model
        code = attrs.get("code", getattr(self.instance, "code", "")).strip()
        title = attrs.get("title", getattr(self.instance, "title", "")).strip()
        if not code or not title:
            raise serializers.ValidationError("Both the code and the title are required.")
        name = f"{code}{model.SEPARATOR}{title}"
        if len(name) > 100:
            raise serializers.ValidationError("The code and title together must be 100 characters or fewer.")
        others = model.objects.exclude(pk=getattr(self.instance, "pk", None))
        if others.filter(code__iexact=code).exists():
            raise serializers.ValidationError({"code": f"The code {code} is already used."})
        if others.filter(name__iexact=name).exists():
            raise serializers.ValidationError(f"This {model._meta.verbose_name} already exists.")
        return {**attrs, "code": code, "title": title}


def funding_type_codes():
    """Codes a program/project may use: the admin's Funding Types plus the three system ones, which the Manual's
    rules depend on and which exist even before the seed migration's rows do."""
    return {code for code, _ in Program.FUNDING_CHOICES} | set(FundingType.objects.values_list("code", flat=True))


def validate_funding_type(value):
    if value not in funding_type_codes():
        raise serializers.ValidationError(f"'{value}' is not a Funding Type in System Admin > Funding Types.")
    return value


class FundingTypeSerializer(AdminChoiceSerializer):
    """The admin types only the name; the stored code is made from it once and never changes."""

    class Meta(AdminChoiceSerializer.Meta):
        model = FundingType
        fields = ["id", "code", "name", "is_system", "created_at"]
        read_only_fields = ["code", "is_system"]

    def create(self, validated_data):
        base = slugify(validated_data["name"]).replace("-", "_")[:20].strip("_") or "funding_type"
        code, n = base, 2
        while code in funding_type_codes():
            suffix = f"_{n}"
            code, n = base[: 20 - len(suffix)] + suffix, n + 1
        return super().create({**validated_data, "code": code})


class CollegeUnitSerializer(CodedChoiceSerializer):
    class Meta(CodedChoiceSerializer.Meta):
        model = CollegeUnit


class RdeThrustSerializer(CodedChoiceSerializer):
    """RDE Agenda entry (client 2026-10-20): a thrust has a number code ("1"); a priority area sits under a thrust and
    its code is the thrust's code plus a number ("1.10"). Two levels only."""

    class Meta(CodedChoiceSerializer.Meta):
        model = RdeThrust
        fields = [*CodedChoiceSerializer.Meta.fields, "parent"]

    def validate(self, attrs):
        attrs = super().validate(attrs)
        parent = attrs.get("parent", getattr(self.instance, "parent", None))
        code = attrs["code"]
        if parent is None:
            if not re.fullmatch(r"\d+", code):
                raise serializers.ValidationError({"code": "A thrust's code is a number, e.g. 9."})
            return attrs
        if parent.parent_id is not None:
            raise serializers.ValidationError({"parent": "Pick a thrust; priority areas can't have their own."})
        if self.instance is not None and (parent.pk == self.instance.pk or self.instance.priorities.exists()):
            raise serializers.ValidationError({"parent": "A thrust with priority areas can't move under another thrust."})
        if not re.fullmatch(rf"{re.escape(parent.code)}\.\d+", code):
            raise serializers.ValidationError({"code": f"Use the thrust's number then a number, e.g. {parent.code}.1."})
        return attrs


def validate_rde_alignment(serializer, attrs):
    """Project/Program RDE Thrust + RDE Priority Area (client 2026-10-20): both or neither, the thrust must be in
    Admin > RDE Thrusts and the priority area must be one of its own. Checked only when either field is sent, so
    older records keep their values on unrelated edits."""
    if "rde_thrust" not in attrs and "rde_priority" not in attrs:
        return
    instance = serializer.instance
    thrust = attrs.get("rde_thrust", getattr(instance, "rde_thrust", ""))
    priority = attrs.get("rde_priority", getattr(instance, "rde_priority", ""))
    if not thrust and not priority:
        return
    if not priority:
        raise serializers.ValidationError({"rde_priority": "Select the RDE Priority Area under the RDE Thrust."})
    row = RdeThrust.objects.filter(parent=None, name=thrust).first() if thrust else None
    if row is None:
        raise serializers.ValidationError({"rde_thrust": "Select an RDE Thrust from System Admin > RDE Thrusts."})
    if not row.priorities.filter(name=priority).exists():
        raise serializers.ValidationError({"rde_priority": "This RDE Priority Area isn't under the selected RDE Thrust."})


class CooperatingAgencySerializer(AdminChoiceSerializer):
    class Meta(AdminChoiceSerializer.Meta):
        model = CooperatingAgency


class EndorserChoiceSerializer(AdminChoiceSerializer):
    class Meta(AdminChoiceSerializer.Meta):
        model = EndorserChoice
        fields = ["id", "name", "designation", "created_at"]


class LeadSerializer(serializers.ModelSerializer):
    # Names, not e-mails, in pickers and tables (client meeting 2026-10-01, #13)
    full_name = serializers.CharField(source="display_name", read_only=True)

    class Meta:
        model = User
        fields = ["id", "email", "full_name"]


def validate_lead_role(user, required_code):
    if not user.role or user.role.code != required_code:
        raise serializers.ValidationError(f"{user.email} does not have the {required_code} role.")


def leader_owns(user, project=None, leads=()):
    """A leader is part of a record if they are one of `leads` (its own or its parent's leader) or `project` is
    already in their scope (they lead it, its program, or one of its studies)."""
    return user in leads or (project is not None and scoped_projects(user).filter(pk=project.pk).exists())


def ensure_registrant_in_scope(serializer, project=None, leads=()):
    """projects.edit includes the leaders, but they may only edit records they are part of. Other roles fall back
    to ensure_in_scope for existing projects. The Excel importer sets context["defer_scope"] and checks the
    finished project instead, since its studies are saved after it."""
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


def ensure_leader_keeps(serializer, attrs, fields):
    """Client decision 2026-09-29 (Option A): the CRC Chair (or DRD/RIUH) sets the official code, the leader and the
    hierarchy placement (Clarification Answers Q4 + summary table); leaders edit the rest of their own records.
    Unchanged values are fine, so the frontend can still PATCH the whole form."""
    request = serializer.context.get("request")
    if request is None or serializer.instance is None or not (request.user.role and request.user.role.code in LEADER_ROLES):
        return
    changed = [f for f in fields if f in attrs and attrs[f] != getattr(serializer.instance, f)]
    if changed:
        raise serializers.ValidationError({f: "Only the System Admin can change this." for f in changed})


def can_edit_registration(user, project):
    """Client request 2026-10-09: once registered, a project's SF-018 data is edited only by the System Admin and the
    project's own Project Leader (or their acting replacement)."""
    code = user.role.code if user.role else None
    return code == "system_admin" or (code == "project_leader" and project.lead_id in [user.pk, *acting_for(user)])


def ensure_registration_editor(serializer, project, attrs, fields=None):
    """Blocks everyone else from changing a registered project's form data (`fields`, default: everything but the
    status, which the Closure tab changes). Creating rows is left alone: the wizard and the Excel import add them
    right after registering, as CRC Chair, DRD or RIUH too."""
    request = serializer.context.get("request")
    if request is None or serializer.instance is None or can_edit_registration(request.user, project):
        return
    guarded = [f for f in attrs if (f in fields if fields else f != "status")]
    if any(attrs[f] != getattr(serializer.instance, f) for f in guarded):
        raise PermissionDenied("Only the System Admin or the project's Project Leader can edit a registered project.")


def ensure_project_leader_registers_self(serializer, lead):
    """Client meeting 2026-10-01: a Project Leader may register a project (manual or Excel) only with themselves as
    its leader. Edits are covered by ensure_leader_keeps."""
    request = serializer.context.get("request")
    if request is None or serializer.instance is not None:
        return
    user = request.user
    if user.role and user.role.code == "project_leader" and lead != user:
        raise serializers.ValidationError({"lead": "Project Leaders can only register projects they lead."})


def validate_lead_concurrency(user, funding_type, queryset, exclude_pk, default_cap):
    # Lock the leader's row: two registrations for the same leader take turns, so both can't count the old load.
    # Callers run inside a transaction (AtomicMutationMixin / @idempotent / the importer's atomic block).
    if user is None:
        return
    type(user).objects.select_for_update().get(pk=user.pk)
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
            "id", "code", "title", "funding_type", "rde_thrust", "rde_priority",
            "lead", "lead_detail", "status", "start_date", "created_at",
        ]

    def validate_funding_type(self, value):
        return validate_funding_type(value)

    def validate(self, attrs):
        lead = attrs.get("lead", getattr(self.instance, "lead", None))
        funding_type = attrs.get("funding_type", getattr(self.instance, "funding_type", None))
        validate_lead_role(lead, "program_leader")
        validate_rde_alignment(self, attrs)
        ensure_leader_keeps(self, attrs, ["code", "lead"])
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
            "rde_thrust", "rde_priority", "is_continuing", "continuing_year", "research_type", "sectors", "sector_other",
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

    def validate_funding_type(self, value):
        return validate_funding_type(value)

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
        validate_rde_alignment(self, attrs)
        ensure_project_leader_registers_self(self, lead)
        ensure_leader_keeps(self, attrs, ["project_code", "lead", "program"])
        if self.instance is not None:
            ensure_registration_editor(self, self.instance, attrs)
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
        project = attrs.get("project", getattr(self.instance, "project", None))
        ensure_registrant_in_scope(self, project)
        ensure_registration_editor(self, project, attrs)
        return attrs


class ProjectEndorserSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectEndorser
        fields = ["id", "project", "role_code", "user", "name", "designation", "signed_on"]

    def validate(self, attrs):
        project = attrs.get("project", getattr(self.instance, "project", None))
        ensure_registrant_in_scope(self, project)
        ensure_registration_editor(self, project, attrs)
        role_code = attrs.get("role_code", getattr(self.instance, "role_code", ""))
        user = attrs.get("user", getattr(self.instance, "user", None))
        if role_code and not Role.objects.filter(code=role_code).exists():
            raise serializers.ValidationError({"role_code": f"Unknown role '{role_code}'."})
        if user and role_code and (not user.role or user.role.code != role_code):
            raise serializers.ValidationError({"user": f"{user.email} does not have the {role_code} role."})
        return attrs


class TargetBeneficiarySerializer(serializers.ModelSerializer):
    class Meta:
        model = TargetBeneficiary
        fields = ["id", "project", "group", "description", "total"]

    def validate(self, attrs):
        project = attrs.get("project", getattr(self.instance, "project", None))
        ensure_registrant_in_scope(self, project)
        ensure_registration_editor(self, project, attrs)
        return attrs


class StudySerializer(serializers.ModelSerializer):
    lead_detail = LeadSerializer(source="lead", read_only=True)

    class Meta:
        model = Study
        fields = ["id", "project", "title", "lead", "lead_detail", "status", "created_at"]

    def validate(self, attrs):
        lead = attrs.get("lead", getattr(self.instance, "lead", None))
        project = attrs.get("project", getattr(self.instance, "project", None))
        if lead:
            validate_lead_role(lead, "study_leader")
        ensure_leader_keeps(self, attrs, ["project", "lead"])
        program_lead = project.program.lead if project.program else None
        ensure_registrant_in_scope(self, project, leads=[lead, project.lead, program_lead])
        ensure_registration_editor(self, project, attrs, fields=["title"])
        return attrs


class WorkPlanMilestoneSerializer(serializers.ModelSerializer):
    """Client meeting 2026-10-01 (#14): personnel tasks are the activities under a milestone; its progress is the share
    of done tasks, and it can't be marked done while any of them is open. Milestones without tasks work as before."""

    responsible_detail = LeadSerializer(source="responsible", read_only=True)
    tasks_total = serializers.SerializerMethodField()
    tasks_done = serializers.SerializerMethodField()
    progress_pct = serializers.SerializerMethodField()

    class Meta:
        model = WorkPlanMilestone
        fields = [
            "id", "project", "title", "start_date", "target_date", "status", "objective", "deliverable",
            "responsible", "responsible_detail", "remarks", "tasks_total", "tasks_done", "progress_pct", "created_at",
        ]

    def get_tasks_total(self, obj):
        return obj.tasks.count()

    def get_tasks_done(self, obj):
        return obj.tasks.filter(status="done").count()

    def get_progress_pct(self, obj):
        total = self.get_tasks_total(obj)
        if not total:
            return 100 if obj.status == "done" else 0
        return round(self.get_tasks_done(obj) * 100 / total)

    def validate(self, attrs):
        ensure_in_scope(self, attrs.get("project", getattr(self.instance, "project", None)))
        if attrs.get("status") == "done" and self.instance:
            still_open = self.instance.tasks.exclude(status="done").count()
            if still_open:
                raise serializers.ValidationError(
                    {"status": f"{still_open} task(s) under this milestone are not done yet."}
                )
        start = attrs.get("start_date", getattr(self.instance, "start_date", None))
        target = attrs.get("target_date", getattr(self.instance, "target_date", None))
        if start and target and start > target:
            raise serializers.ValidationError({"start_date": "Start date cannot be after the target date."})
        return attrs


class ProjectStatusHistorySerializer(serializers.ModelSerializer):
    changed_by_email = serializers.EmailField(source="changed_by.email", read_only=True)
    changed_by_name = serializers.CharField(source="changed_by.display_name", read_only=True, default=None)

    class Meta:
        model = ProjectStatusHistory
        fields = ["id", "project", "from_status", "to_status", "remarks", "changed_by", "changed_by_email", "changed_by_name", "changed_at"]
