from django.conf import settings
from django.db import models

from research_projects.models import Program, Project, Study


class StaffProfile(models.Model):
    LEVEL_CHOICES = ((1, "Level 1"), (2, "Level 2"), (3, "Level 3"))

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="staff_profile")
    staff_level = models.PositiveSmallIntegerField(choices=LEVEL_CHOICES)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.email} (Level {self.staff_level})"


class ProjectAssignment(models.Model):
    """A staff member's assignment to a project or a study (exactly one of the two)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="assignments")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, null=True, blank=True, related_name="assignments")
    study = models.ForeignKey(Study, on_delete=models.CASCADE, null=True, blank=True, related_name="assignments")
    role_label = models.CharField(max_length=120, blank=True)
    # Home department/college of the member (Objective 1c cross-departmental collaboration).
    # Defaults to the user's office on create.
    department = models.CharField(max_length=150, blank=True)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def is_active(self):
        return self.end_date is None

    def __str__(self):
        return f"{self.user.email} -> {self.project or self.study}"


class Task(models.Model):
    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("in_progress", "In Progress"),
        ("done", "Done"),
        ("blocked", "Blocked"),
    )

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="tasks")
    study = models.ForeignKey(Study, on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks")
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="tasks")
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="tasks_assigned")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class TaskUpdate(models.Model):
    """Progress note on a task (DPMIS-based spec PTM-04); a non-blank new_status also moves the task."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="updates")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="task_updates")
    note = models.TextField()
    new_status = models.CharField(max_length=20, choices=Task.STATUS_CHOICES, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.task} update by {self.author}"


class PersonnelChange(models.Model):
    TYPE_CHOICES = (("leader", "Leader"), ("staff", "Staff"))
    STATUS_CHOICES = (
        ("initiated", "Initiated"),
        ("clearance_pending", "Clearance Pending"),
        ("cleared", "Cleared"),
        ("completed", "Completed"),
    )

    change_type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    # Leader change targets exactly one of program/project/study; staff change targets an assignment.
    program = models.ForeignKey(Program, on_delete=models.PROTECT, null=True, blank=True, related_name="personnel_changes")
    project = models.ForeignKey(Project, on_delete=models.PROTECT, null=True, blank=True, related_name="personnel_changes")
    study = models.ForeignKey(Study, on_delete=models.PROTECT, null=True, blank=True, related_name="personnel_changes")
    assignment = models.ForeignKey(ProjectAssignment, on_delete=models.PROTECT, null=True, blank=True, related_name="personnel_changes")
    outgoing = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="changes_out")
    incoming = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="changes_in")
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="initiated")
    initiated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="changes_initiated")
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.change_type}: {self.outgoing.email} -> {self.incoming.email}"


class PropertyClearance(models.Model):
    """Property Acknowledgement Receipt (PAR) clearance for the outgoing person."""

    change = models.OneToOneField(PersonnelChange, on_delete=models.CASCADE, related_name="clearance")
    items = models.TextField(blank=True, help_text="Property items to be returned")
    par_number = models.CharField(max_length=50, blank=True)
    acknowledged_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="clearances_acknowledged")
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    remarks = models.TextField(blank=True)

    def __str__(self):
        return f"Clearance for change #{self.change_id}"
