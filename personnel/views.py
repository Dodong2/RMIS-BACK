from datetime import date

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.permissions import HasRole
from research_projects.models import Project
from .models import PersonnelChange, ProjectAssignment, StaffProfile, Task, TaskUpdate
from .serializers import (
    CLEARANCE_ROLES,
    MANAGE_ROLES,
    TASK_ASSIGNER_ROLES,
    LeaderAssignmentSerializer,
    PersonnelChangeSerializer,
    ProjectAssignmentSerializer,
    PropertyClearanceSerializer,
    StaffProfileSerializer,
    TaskSerializer,
    TaskUpdateSerializer,
    complete_change,
)


class ManageWritesMixin:
    """Authenticated read, MANAGE_ROLES write."""

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        return [HasRole(MANAGE_ROLES)]


class LeaderAssignmentView(APIView):
    permission_classes = [HasRole(MANAGE_ROLES)]

    def post(self, request):
        serializer = LeaderAssignmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record = serializer.save()
        return Response({"record_type": serializer.validated_data["record_type"], "record_id": record.pk, "lead": record.lead_id})


class LeaderLoadView(APIView):
    """Active leadership count per leader vs. the concurrency caps (programs 2, projects 3)."""

    permission_classes = [HasRole(MANAGE_ROLES + ["program_leader", "project_leader"])]

    def get(self, request):
        users = User.objects.filter(
            is_active=True, role__code__in=["program_leader", "project_leader"],
        ).annotate(
            programs=Count("led_programs", filter=Q(led_programs__status="active"), distinct=True),
            projects=Count("led_projects", filter=Q(led_projects__status="active"), distinct=True),
        )
        return Response([
            {
                "user": u.id, "email": u.email, "role": u.role.code,
                "active_programs": u.programs, "program_cap": 2,
                "active_projects": u.projects, "project_cap": 3,
            }
            for u in users.select_related("role")
        ])


class StaffProfileListCreateView(ManageWritesMixin, generics.ListCreateAPIView):
    queryset = StaffProfile.objects.select_related("user").order_by("user__email")
    serializer_class = StaffProfileSerializer


class StaffProfileDetailView(ManageWritesMixin, generics.RetrieveUpdateAPIView):
    queryset = StaffProfile.objects.all()
    serializer_class = StaffProfileSerializer


class AssignmentListCreateView(ManageWritesMixin, generics.ListCreateAPIView):
    serializer_class = ProjectAssignmentSerializer

    def get_queryset(self):
        qs = ProjectAssignment.objects.all().order_by("-start_date")
        for param in ("project", "study", "user"):
            value = self.request.query_params.get(param)
            if value:
                qs = qs.filter(**{f"{param}_id": value})
        if self.request.query_params.get("active") == "true":
            qs = qs.filter(end_date__isnull=True)
        return qs


class AssignmentDetailView(ManageWritesMixin, generics.RetrieveUpdateAPIView):
    queryset = ProjectAssignment.objects.all()
    serializer_class = ProjectAssignmentSerializer


class TaskListCreateView(generics.ListCreateAPIView):
    serializer_class = TaskSerializer

    def get_permissions(self):
        if self.request.method == "POST":
            return [HasRole(TASK_ASSIGNER_ROLES)]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        qs = Task.objects.all().order_by("due_date", "-created_at")
        if user.role and user.role.code == "project_staff":
            qs = qs.filter(assignee=user)
        for param in ("project", "study", "assignee", "status"):
            value = self.request.query_params.get(param)
            if value:
                qs = qs.filter(**{param if param == "status" else f"{param}_id": value})
        if self.request.query_params.get("overdue") == "true":
            qs = qs.filter(due_date__lt=date.today()).exclude(status="done")
        return qs

    def perform_create(self, serializer):
        serializer.save(assigned_by=self.request.user)


class TaskDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Task.objects.all()
    serializer_class = TaskSerializer

    def get_permissions(self):
        if self.request.method == "DELETE":
            return [HasRole(TASK_ASSIGNER_ROLES)]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.role and user.role.code == "project_staff":
            qs = qs.filter(assignee=user)
        return qs


class TaskUpdateListCreateView(generics.ListCreateAPIView):
    serializer_class = TaskUpdateSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_task(self):
        # Reuse TaskDetailView's visibility rule (project_staff only see their own tasks).
        tasks = Task.objects.all()
        user = self.request.user
        if user.role and user.role.code == "project_staff":
            tasks = tasks.filter(assignee=user)
        return generics.get_object_or_404(tasks, pk=self.kwargs["pk"])

    def get_queryset(self):
        return self.get_task().updates.select_related("author").order_by("-created_at", "-id")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.request.method == "POST":
            context["task"] = self.get_task()
        return context

    def perform_create(self, serializer):
        task = serializer.context["task"]
        update = serializer.save(task=task, author=self.request.user)
        if update.new_status and update.new_status != task.status:
            task.status = update.new_status
            task.save(update_fields=["status"])


class WorkloadView(APIView):
    """Open/overdue/done task counts per assignee (DPMIS-based spec PTM-06/07)."""

    permission_classes = [HasRole(TASK_ASSIGNER_ROLES)]

    def get(self, request):
        tasks = Task.objects.all()
        project_id = request.query_params.get("project")
        if project_id:
            tasks = tasks.filter(project_id=project_id)
        rows = (
            tasks.values("assignee", "assignee__email")
            .annotate(
                open=Count("id", filter=~Q(status="done")),
                overdue=Count("id", filter=Q(due_date__lt=date.today()) & ~Q(status="done")),
                done=Count("id", filter=Q(status="done")),
            )
            .order_by("-open", "assignee__email")
        )
        return Response([
            {"assignee": r["assignee"], "email": r["assignee__email"], "open": r["open"], "overdue": r["overdue"], "done": r["done"]}
            for r in rows
        ])


class CollaborationView(APIView):
    """Departments involved per active project (Objective 1c). Departments come from the project
    leader's and study leaders' `office` plus each active assignment's `department`."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        projects = Project.objects.filter(status="active").select_related("lead").prefetch_related(
            "studies__lead", "assignments", "studies__assignments",
        )
        if request.query_params.get("project"):
            projects = projects.filter(pk=request.query_params["project"])
        rows = []
        for project in projects:
            members = [project.lead.office] + [study.lead.office for study in project.studies.all()]
            assignments = list(project.assignments.all()) + [a for st in project.studies.all() for a in st.assignments.all()]
            members += [a.department for a in assignments if a.end_date is None]
            departments = sorted({d.strip() for d in members if d and d.strip()})
            rows.append({
                "project": project.id, "project_code": project.project_code, "title": project.title,
                "departments": departments, "department_count": len(departments),
                "is_cross_departmental": len(departments) >= 2,
            })
        if request.query_params.get("cross_only") == "true":
            rows = [r for r in rows if r["is_cross_departmental"]]
        return Response(rows)


class PersonnelChangeListCreateView(ManageWritesMixin, generics.ListCreateAPIView):
    queryset = PersonnelChange.objects.select_related("clearance").order_by("-created_at")
    serializer_class = PersonnelChangeSerializer


class PersonnelChangeDetailView(generics.RetrieveAPIView):
    queryset = PersonnelChange.objects.select_related("clearance")
    serializer_class = PersonnelChangeSerializer
    permission_classes = [permissions.IsAuthenticated]


class ClearanceView(APIView):
    """Record PAR details and, when `acknowledge` is true, sign off the clearance."""

    permission_classes = [HasRole(CLEARANCE_ROLES)]

    def patch(self, request, pk):
        change = generics.get_object_or_404(PersonnelChange.objects.select_related("clearance"), pk=pk)
        if change.status in ("cleared", "completed"):
            return Response({"detail": "Clearance is already signed off."}, status=status.HTTP_400_BAD_REQUEST)
        clearance = change.clearance
        serializer = PropertyClearanceSerializer(clearance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        clearance = serializer.save()

        if request.data.get("acknowledge"):
            if not clearance.par_number:
                return Response({"par_number": "PAR number is required to acknowledge."}, status=status.HTTP_400_BAD_REQUEST)
            clearance.acknowledged_by = request.user
            clearance.acknowledged_at = timezone.now()
            clearance.save(update_fields=["acknowledged_by", "acknowledged_at"])
            change.status = "cleared"
        else:
            change.status = "clearance_pending"
        change.save(update_fields=["status"])
        return Response(PersonnelChangeSerializer(change).data)


class CompleteChangeView(APIView):
    permission_classes = [HasRole(MANAGE_ROLES)]

    def post(self, request, pk):
        change = generics.get_object_or_404(PersonnelChange, pk=pk)
        if change.status != "cleared":
            return Response({"detail": "Property clearance must be signed off before completing."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(PersonnelChangeSerializer(complete_change(change)).data)
