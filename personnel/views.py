from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.permissions import HasRole
from .models import PersonnelChange, ProjectAssignment, StaffProfile, Task
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
