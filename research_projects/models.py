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

    # Fields from LSPU-RDO-SF-018 (Research Proposal Form), Section I
    SECTOR_CHOICES = (
        ("agriculture_fisheries", "Agriculture/Fisheries"),
        ("education", "Education"),
        ("community_development", "Community Development"),
        ("information_tech", "Information Tech."),
        ("politics", "Politics"),
        ("others", "Others"),
    )
    RESEARCH_TYPE_CHOICES = (("basic", "Basic Research"), ("applied", "Applied Research"))
    PRIORITY_AREA_CHOICES = (
        ("science_math", "Science and Mathematics"),
        ("education_teacher_training", "Education and Teacher's Training"),
        ("health", "Health and Health Profession"),
        ("ict", "Information and Communication Tech."),
        ("engineering", "Engineering"),
        ("agriculture_fisheries", "Agriculture and Fisheries"),
        ("environmental_science", "Environmental Science"),
        ("social_sciences_humanities", "Social Sciences and Humanities"),
    )
    TYPOLOGY_CHOICES = (
        ("operations", "Operations Research"),
        ("development", "Development Research"),
        ("qualitative", "Qualitative Research"),
        ("quantitative", "Quantitative Research"),
        ("descriptive_survey", "Descriptive/Survey Research"),
        ("laboratory_field", "Laboratory/Field Research"),
        ("quasi_experimental", "Quasi-Experimental Research"),
        ("pure_experimental", "Pure Experimental Research"),
    )

    GENDER_CHOICES = (("male", "Male"), ("female", "Female"))

    is_continuing = models.BooleanField(default=False)  # False = New Proposal
    continuing_year = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Year 2, Year 3, ... when continuing")
    research_type = models.CharField(max_length=10, choices=RESEARCH_TYPE_CHOICES, blank=True)
    sectors = models.JSONField(default=list, blank=True)  # list of SECTOR_CHOICES codes; the form allows several
    sector_other = models.CharField(max_length=150, blank=True)
    research_priority_area = models.CharField(max_length=40, choices=PRIORITY_AREA_CHOICES, blank=True)
    research_typology = models.JSONField(default=list, blank=True)  # list of TYPOLOGY_CHOICES codes
    sdgs = models.JSONField(default=list, blank=True)  # list of SDG numbers, 1-17
    campus = models.CharField(max_length=100, blank=True)
    college = models.CharField(max_length=100, blank=True, help_text="College Unit (Annex A endorsement page)")
    implementing_unit = models.CharField(max_length=150, blank=True)
    cooperating_agencies = models.TextField(blank=True)
    total_cost = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    lead_gender = models.CharField(max_length=10, choices=GENDER_CHOICES, blank=True)
    contact_number = models.CharField(max_length=50, blank=True)

    # LSPU-RDO-SF-018 Sections II, IV, VI, VIII, IX (III Objectives is `objectives` below)
    background = models.TextField(blank=True)
    methodology = models.TextField(blank=True)
    socio_economic_significance = models.TextField(blank=True)
    monitoring_evaluation = models.TextField(blank=True)
    references = models.TextField(blank=True)

    # DPMIS-based spec PM-03 project details
    description = models.TextField(blank=True)
    objectives = models.TextField(blank=True)
    beneficiaries = models.TextField(blank=True)
    expected_outcomes = models.TextField(blank=True)
    expected_impacts = models.TextField(blank=True)

    # Pre-RMIS proposal pipeline, reference only — RMIS starts at NTP (Module Structure docx, Module 2),
    # so Proposal -> Review -> Approval is recorded here, not run as an in-system workflow.
    proposal_submitted_on = models.DateField(null=True, blank=True)
    proposal_reviewed_on = models.DateField(null=True, blank=True)
    proposal_approved_on = models.DateField(null=True, blank=True)
    reviewing_body = models.CharField(max_length=150, blank=True, help_text="e.g. ITRC, ETRC, CRC")
    # Annex A endorsement page, recorded as reference like the dates above (no in-system signing).
    # proposal_submitted_on = "Submitted by" date, proposal_approved_on = University President's date.
    endorsed_by_dean = models.CharField(max_length=150, blank=True)
    endorsed_by_dean_on = models.DateField(null=True, blank=True)
    noted_by_rds_director = models.CharField(max_length=150, blank=True)
    noted_by_rds_director_on = models.DateField(null=True, blank=True)
    recommended_by_campus_director = models.CharField(max_length=150, blank=True)
    recommended_by_campus_director_on = models.DateField(null=True, blank=True)
    recommended_by_vprde = models.CharField(max_length=150, blank=True)
    recommended_by_vprde_on = models.DateField(null=True, blank=True)
    approved_by_president = models.CharField(max_length=150, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.project_code} - {self.title}"


class ProjectTeamMember(models.Model):
    """Co-Project Leader and Project Team rows of LSPU-RDO-SF-018 Section I. Name is free text because the form
    lists people who may not have RMIS accounts, or whole groups (e.g. "EIU Coordinators"); user is optional."""

    ROLE_CHOICES = (("co_leader", "Co-Project Leader"), ("member", "Team Member"))

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="team_members")
    member_role = models.CharField(max_length=10, choices=ROLE_CHOICES, default="member")
    name = models.CharField(max_length=200)
    gender = models.CharField(max_length=10, choices=Project.GENDER_CHOICES, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="team_memberships"
    )

    def __str__(self):
        return f"{self.project.project_code}: {self.name} ({self.get_member_role_display()})"


class TargetBeneficiary(models.Model):
    """LSPU-RDO-SF-018 Section VII: one row per beneficiary group with its total."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="target_beneficiaries")
    group = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    total = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.project.project_code}: {self.group} ({self.total})"


class ProjectStatusHistory(models.Model):
    """One row per Project.status change (DPMIS-based spec PM-09), written by ProjectDetailView."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="status_history")
    from_status = models.CharField(max_length=20, choices=Project.STATUS_CHOICES)
    to_status = models.CharField(max_length=20, choices=Project.STATUS_CHOICES)
    remarks = models.TextField(blank=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="project_status_changes")
    changed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.project.project_code}: {self.from_status} -> {self.to_status}"


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
    start_date = models.DateField(null=True, blank=True)
    target_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    objective = models.TextField(blank=True, help_text="Which project objective this activity serves")
    deliverable = models.TextField(blank=True)
    responsible = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="milestones_responsible"
    )
    remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title