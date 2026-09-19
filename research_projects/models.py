from django.conf import settings
from django.db import models


class Program(models.Model):
    FUNDING_CHOICES = (
        ("institutional", "Institutional (LSPU-Funded)"),
        ("core_funded", "Core-Funded (Self-Funded)"),
        ("externally_funded", "Externally-Funded"),
    )
    STATUS_CHOICES = (
        ("active", "Active"),
        ("completed", "Completed"),
        ("archived", "Archived"),
    )

    code = models.CharField(max_length=50, unique=True, blank=True, null=True)
    title = models.CharField(max_length=300)
    funding_type = models.CharField(max_length=20, choices=FUNDING_CHOICES)
    rei_thrust = models.CharField(max_length=150, blank=True)
    lead = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="led_programs")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    start_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class Project(models.Model):
    FUNDING_CHOICES = Program.FUNDING_CHOICES
    STATUS_CHOICES = Program.STATUS_CHOICES

    program = models.ForeignKey(Program, on_delete=models.SET_NULL, null=True, blank=True, related_name="projects")
    title = models.CharField(max_length=300)
    project_code = models.CharField(max_length=50, unique=True)
    funding_type = models.CharField(max_length=20, choices=FUNDING_CHOICES)
    ntp_number = models.CharField(max_length=50, blank=True)
    ntp_date = models.DateField(null=True, blank=True)
    toe_signed_date = models.DateField(null=True, blank=True)
    is_dry_research = models.BooleanField(default=True)
    lead = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="led_projects")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    start_date = models.DateField(null=True, blank=True)
    target_end_date = models.DateField(null=True, blank=True)
    rei_thrust = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.project_code} - {self.title}"


class Study(models.Model):
    STATUS_CHOICES = Program.STATUS_CHOICES

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="studies")
    title = models.CharField(max_length=300)
    lead = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="led_studies")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class WorkPlanMilestone(models.Model):
    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("in_progress", "In Progress"),
        ("done", "Done"),
        ("delayed", "Delayed"),
    )

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="milestones")
    title = models.CharField(max_length=300)
    target_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title