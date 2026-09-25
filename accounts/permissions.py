from rest_framework.permissions import BasePermission


class HasRole(BasePermission):
    """HasRole("budget.certify") checks a permission code against the RolePermission table (client clarification Q2).
    Every app gates by permission code; the HasRole([...role codes]) list form is kept only for compatibility."""

    def __init__(self, allowed_codes):
        self.allowed_codes = allowed_codes

    def __call__(self):
        return self

    def has_permission(self, request, view):
        user = request.user
        if not (user.is_authenticated and user.role is not None):
            return False
        if isinstance(self.allowed_codes, str):
            return role_can(user, self.allowed_codes)
        return user.role.code in self.allowed_codes


def role_can(user, permission_code):
    """True if the user's role holds this permission code in the DB. For inline checks outside permission_classes."""
    from accounts.models import RolePermission

    if not user.is_authenticated or user.role_id is None:
        return False
    return RolePermission.objects.filter(role_id=user.role_id, permission__code=permission_code).exists()

# Row-level scope for budget/financial data (client clarification Q12, Q1c).
# Leaders see only projects they lead (directly, or via a study/program they lead); project_staff see
# no budget data; campus-level roles are limited to User.scope["campus"] when an admin has set it.
# Everyone else (system_admin, vprei, drd, university_admin) is university-wide.
LEADER_ROLES = ["program_leader", "project_leader", "study_leader"]
CAMPUS_SCOPED_ROLES = ["crc_chair", "finance_budget", "procurement_officer_lib", "riuh"]


def scoped_projects(user):
    """Project queryset this user may see budget data for, or None for no restriction."""
    from django.db.models import Q
    from research_projects.models import Project

    code = user.role.code if user.role else None
    if code in LEADER_ROLES:
        return Project.objects.filter(
            Q(lead=user) | Q(studies__lead=user) | Q(program__lead=user)
        ).distinct()
    if code == "project_staff" or code is None:
        return Project.objects.none()
    campus = (user.scope or {}).get("campus")
    if code in CAMPUS_SCOPED_ROLES and campus:
        return Project.objects.filter(campus__iexact=campus)
    return None


def ensure_in_scope(serializer, project):
    """Serializer-side guard for writes: the request user must have the project in scope."""
    from rest_framework.exceptions import ValidationError

    request = serializer.context.get("request")
    projects = scoped_projects(request.user) if request else None
    if projects is not None and not projects.filter(pk=project.pk).exists():
        raise ValidationError("This project is outside your scope.")


class BudgetScopedMixin:
    """Restricts list and detail lookups to the user's scoped projects. Hooks filter_queryset (used by both
    list() and get_object()) so views with their own get_queryset still get scoped.
    Set project_lookup to the path from the model to Project."""

    project_lookup = "project"

    def filter_queryset(self, queryset):
        qs = super().filter_queryset(queryset)
        projects = scoped_projects(self.request.user)
        if projects is None:
            return qs
        return qs.filter(**{f"{self.project_lookup}__in": projects})


# Document visibility by sensitivity level (client clarification Q8).
UNIVERSITY_WIDE_ROLES = ["system_admin", "vprei", "drd", "university_admin"]


def visible_documents(user, queryset):
    from django.db.models import Q
    from research_projects.models import Project

    code = user.role.code if user.role else None
    if code in UNIVERSITY_WIDE_ROLES:
        return queryset
    if code == "riuh":
        return queryset.filter(sensitivity__in=("project_team", "restricted"))
    if code == "crc_chair":
        return queryset.filter(sensitivity="project_team")
    if code in ("finance_budget", "procurement_officer_lib"):
        return queryset.filter(sensitivity="financial")
    if code in LEADER_ROLES or code == "project_staff":
        team = Project.objects.filter(
            Q(lead=user) | Q(studies__lead=user) | Q(program__lead=user)
            | Q(assignments__user=user) | Q(studies__assignments__user=user)
        )
        led = Project.objects.filter(Q(lead=user) | Q(program__lead=user))
        return queryset.filter(
            Q(sensitivity="project_team", project__in=team) | Q(sensitivity="financial", project__in=led)
        ).distinct()
    return queryset.none()
