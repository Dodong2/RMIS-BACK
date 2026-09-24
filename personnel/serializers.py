from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from accounts.models import User
from research_projects.models import Program, Project, Study
from research_projects.serializers import (
    LeadSerializer,
    validate_lead_concurrency,
    validate_lead_role,
)
from .models import PersonnelChange, ProjectAssignment, PropertyClearance, StaffProfile, Task, TaskUpdate

MANAGE_ROLES = ["system_admin", "crc_chair", "drd", "riuh"]
TASK_ASSIGNER_ROLES = MANAGE_ROLES + ["program_leader", "project_leader", "study_leader"]
CLEARANCE_ROLES = MANAGE_ROLES + ["procurement_officer_lib"]

# record type -> (model, required lead role, concurrency cap or None for no cap)
LEAD_RECORDS = {
    "program": (Program, "program_leader", 2),
    "project": (Project, "project_leader", 3),
    "study": (Study, "study_leader", None),
}


def apply_lead(record_type, record, user):
    """Validate and set `user` as lead of `record`. Raises ValidationError on failure."""
    model, role_code, cap = LEAD_RECORDS[record_type]
    validate_lead_role(user, role_code)
    if cap:
        validate_lead_concurrency(user, record.funding_type, model.objects.all(), record.pk, default_cap=cap)
    record.lead = user
    record.save(update_fields=["lead"])


class StaffProfileSerializer(serializers.ModelSerializer):
    user_detail = LeadSerializer(source="user", read_only=True)

    class Meta:
        model = StaffProfile
        fields = ["id", "user", "user_detail", "staff_level", "updated_at"]

    def validate_user(self, user):
        if not user.role or user.role.code != "project_staff":
            raise serializers.ValidationError("Staff level applies to project_staff users only.")
        return user


class LeaderAssignmentSerializer(serializers.Serializer):
    record_type = serializers.ChoiceField(choices=list(LEAD_RECORDS))
    record_id = serializers.IntegerField()
    lead = serializers.PrimaryKeyRelatedField(queryset=User.objects.filter(is_active=True))

    def validate(self, attrs):
        model, role_code, cap = LEAD_RECORDS[attrs["record_type"]]
        try:
            record = model.objects.get(pk=attrs["record_id"])
        except model.DoesNotExist:
            raise serializers.ValidationError({"record_id": "Record not found."})
        validate_lead_role(attrs["lead"], role_code)
        if cap:
            validate_lead_concurrency(attrs["lead"], record.funding_type, model.objects.all(), record.pk, default_cap=cap)
        attrs["record"] = record
        return attrs

    def save(self, **kwargs):
        record = self.validated_data["record"]
        record.lead = self.validated_data["lead"]
        record.save(update_fields=["lead"])
        return record


class ProjectAssignmentSerializer(serializers.ModelSerializer):
    user_detail = LeadSerializer(source="user", read_only=True)
    is_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = ProjectAssignment
        fields = ["id", "user", "user_detail", "project", "study", "role_label", "department",
                  "start_date", "end_date", "is_active", "created_at"]

    def validate(self, attrs):
        project = attrs.get("project", getattr(self.instance, "project", None))
        study = attrs.get("study", getattr(self.instance, "study", None))
        if bool(project) == bool(study):
            raise serializers.ValidationError("Assign to exactly one of project or study.")
        user = attrs.get("user", getattr(self.instance, "user", None))
        if not user.role or user.role.code != "project_staff":
            raise serializers.ValidationError(f"{user.email} is not a project_staff user.")
        if not attrs.get("department") and not self.instance:
            attrs["department"] = user.office
        return attrs


class TaskSerializer(serializers.ModelSerializer):
    assignee_detail = LeadSerializer(source="assignee", read_only=True)

    class Meta:
        model = Task
        fields = ["id", "project", "study", "title", "description", "due_date", "status",
                  "assignee", "assignee_detail", "assigned_by", "created_at"]
        read_only_fields = ["assigned_by"]

    def validate(self, attrs):
        user = self.context["request"].user
        if user.role.code not in TASK_ASSIGNER_ROLES:
            # Assignees may only update the status of their own task.
            if not self.instance or self.instance.assignee_id != user.id or set(attrs) - {"status"}:
                raise serializers.ValidationError("You may only update the status of your own tasks.")
            return attrs
        study = attrs.get("study", getattr(self.instance, "study", None))
        project = attrs.get("project", getattr(self.instance, "project", None))
        if study and study.project_id != project.id:
            raise serializers.ValidationError({"study": "Study does not belong to this project."})
        return attrs


class TaskUpdateSerializer(serializers.ModelSerializer):
    author_email = serializers.EmailField(source="author.email", read_only=True)

    class Meta:
        model = TaskUpdate
        fields = ["id", "task", "author", "author_email", "note", "new_status", "created_at"]
        read_only_fields = ["task", "author"]

    def validate(self, attrs):
        user = self.context["request"].user
        task = self.context["task"]
        if user.role.code not in TASK_ASSIGNER_ROLES and task.assignee_id != user.id:
            raise serializers.ValidationError("Only the assignee or a task assigner can post updates on this task.")
        return attrs


class PropertyClearanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = PropertyClearance
        fields = ["id", "items", "par_number", "acknowledged_by", "acknowledged_at", "remarks"]
        read_only_fields = ["acknowledged_by", "acknowledged_at"]


class PersonnelChangeSerializer(serializers.ModelSerializer):
    clearance = PropertyClearanceSerializer(read_only=True)
    outgoing_detail = LeadSerializer(source="outgoing", read_only=True)
    incoming_detail = LeadSerializer(source="incoming", read_only=True)

    class Meta:
        model = PersonnelChange
        fields = ["id", "change_type", "program", "project", "study", "assignment",
                  "outgoing", "outgoing_detail", "incoming", "incoming_detail", "reason",
                  "status", "initiated_by", "created_at", "completed_at", "clearance"]
        read_only_fields = ["status", "initiated_by", "completed_at"]

    def validate(self, attrs):
        if self.instance:
            raise serializers.ValidationError("Personnel changes cannot be edited; advance the workflow instead.")
        outgoing, incoming = attrs["outgoing"], attrs["incoming"]
        if outgoing == incoming:
            raise serializers.ValidationError("Outgoing and incoming must be different users.")

        if attrs["change_type"] == "staff":
            assignment = attrs.get("assignment")
            if not assignment or not assignment.is_active:
                raise serializers.ValidationError({"assignment": "An active assignment is required for a staff change."})
            if assignment.user_id != outgoing.id:
                raise serializers.ValidationError({"assignment": "Assignment does not belong to the outgoing user."})
            if not incoming.role or incoming.role.code != "project_staff":
                raise serializers.ValidationError({"incoming": "Incoming user must be project_staff."})
            return attrs

        targets = [t for t in ("program", "project", "study") if attrs.get(t)]
        if len(targets) != 1:
            raise serializers.ValidationError("A leader change targets exactly one of program, project or study.")
        record = attrs[targets[0]]
        if record.lead_id != outgoing.id:
            raise serializers.ValidationError({"outgoing": "Outgoing user is not the current lead of that record."})
        model, role_code, cap = LEAD_RECORDS[targets[0]]
        validate_lead_role(incoming, role_code)
        if cap:
            validate_lead_concurrency(incoming, record.funding_type, model.objects.all(), record.pk, default_cap=cap)
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        change = PersonnelChange.objects.create(initiated_by=self.context["request"].user, **validated_data)
        PropertyClearance.objects.create(change=change)
        return change


def complete_change(change):
    """Apply a cleared personnel change. Caller must have checked change.status == 'cleared'."""
    with transaction.atomic():
        if change.change_type == "leader":
            record_type = next(t for t in ("program", "project", "study") if getattr(change, t + "_id"))
            apply_lead(record_type, getattr(change, record_type), change.incoming)
        else:
            old = change.assignment
            today = timezone.localdate()
            old.end_date = today
            old.save(update_fields=["end_date"])
            ProjectAssignment.objects.create(
                user=change.incoming, project=old.project, study=old.study,
                role_label=old.role_label, start_date=today,
            )
            scope = {"project": old.project} if old.project else {"study": old.study}
            Task.objects.filter(assignee=change.outgoing, **scope).exclude(status="done").update(assignee=change.incoming)
        change.status = "completed"
        change.completed_at = timezone.now()
        change.save(update_fields=["status", "completed_at"])
    return change
