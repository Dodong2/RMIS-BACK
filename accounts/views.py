import requests as http
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils.crypto import get_random_string
from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.tokens import RefreshToken

from .models import AuditLog, Permission, Role, RolePermission, TemporaryReplacement, User
from .serializers import (
    AuditLogSerializer, RoleSerializer, PendingUserSerializer, TemporaryReplacementSerializer, UserListSerializer,
    UserScopeSerializer,
)
from .permissions import HasRole
from .emails import notify_admins_new_registration, send_role_confirmation_email


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get("email", "").strip().lower()
        password = request.data.get("password")
        password2 = request.data.get("password2")
        requested_role_id = request.data.get("requested_role")

        if not email or not password or not password2:
            return Response({"detail": "Email and password are required."}, status=400)
        if password != password2:
            return Response({"detail": "Passwords do not match."}, status=400)
        if User.objects.filter(email=email).exists():
            return Response({"detail": "Email already registered."}, status=400)

        requested_role = Role.objects.filter(id=requested_role_id).first() if requested_role_id else None
        username = f"{email.split('@')[0]}_{get_random_string(5)}"

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            is_active=False,
            is_pending_role=True,
            registration_method="email",
            requested_role=requested_role,
        )

        notify_admins_new_registration(user)

        return Response({"detail": "Registration received. Please wait for confirmation."}, status=201)


class GoogleRequestView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        token = request.data.get("supabase_access_token")
        requested_role_id = request.data.get("requested_role")

        if not token:
            return Response({"detail": "Missing token."}, status=400)

        resp = http.get(
            f"{settings.SUPABASE_URL}/auth/v1/user",
            headers={"Authorization": f"Bearer {token}", "apikey": settings.SUPABASE_PUBLISHABLE_KEY},
        )
        print("SUPABASE STATUS:", resp.status_code)
        print("SUPABASE BODY:", resp.text)
        if resp.status_code != 200:
            return Response({"detail": "Invalid Supabase token."}, status=401)

        supa_user = resp.json()
        email = supa_user["email"]
        supabase_uid = supa_user["id"]
        requested_role = Role.objects.filter(id=requested_role_id).first() if requested_role_id else None

        user = User.objects.filter(email=email).first()
        if user is None:
            username = f"{email.split('@')[0]}_{get_random_string(5)}"
            user = User.objects.create(
                username=username,
                email=email,
                supabase_uid=supabase_uid,
                is_active=False,
                is_pending_role=True,
                registration_method="google",
                requested_role=requested_role,
            )
            user.set_unusable_password()
            user.save()
            notify_admins_new_registration(user)

        return Response({"detail": "Request received. Please wait for confirmation."}, status=201)


class GoogleExchangeView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        token = request.data.get("supabase_access_token")
        if not token:
            return Response({"detail": "Missing token."}, status=400)

        resp = http.get(
            f"{settings.SUPABASE_URL}/auth/v1/user",
            headers={"Authorization": f"Bearer {token}", "apikey": settings.SUPABASE_PUBLISHABLE_KEY},
        )
        if resp.status_code != 200:
            return Response({"detail": "Invalid Supabase token."}, status=401)

        email = resp.json()["email"]
        user = User.objects.filter(email=email).first()

        if user is None:
            return Response({"detail": "No account found. Please register first."}, status=404)

        if not user.is_active:
            return Response({"detail": "Your account is not yet confirmed.", "is_pending_role": user.is_pending_role}, status=403)

        refresh = RefreshToken.for_user(user)
        return Response({"access": str(refresh.access_token), "refresh": str(refresh)})


class RolesListView(generics.ListAPIView):
    serializer_class = RoleSerializer
    permission_classes = [AllowAny]
    queryset = Role.objects.all()


class PendingUsersListView(generics.ListAPIView):
    serializer_class = PendingUserSerializer
    permission_classes = [HasRole("accounts.manage_users")]
    queryset = User.objects.filter(is_pending_role=True)


class UsersListView(generics.ListAPIView):
    serializer_class = UserListSerializer
    permission_classes = [HasRole("accounts.manage_users")]
    queryset = User.objects.filter(is_pending_role=False)


class AssignRoleView(APIView):
    permission_classes = [HasRole("accounts.manage_users")]

    def patch(self, request, user_id):
        role_id = request.data.get("role_id")
        role = get_object_or_404(Role, id=role_id)
        user = get_object_or_404(User, id=user_id)

        user.role = role
        user.is_pending_role = False
        user.is_active = True
        user.save()

        send_role_confirmation_email(user)

        return Response({"detail": "Role assigned and confirmation sent."})
    
    
class UpdateUserRoleView(APIView):
    permission_classes = [HasRole("accounts.manage_users")]
 
    def patch(self, request, user_id):
        role_id = request.data.get("role_id")
        if not role_id:
            return Response({"detail": "role_id is required."}, status=400)
 
        role = get_object_or_404(Role, id=role_id)
        user = get_object_or_404(User, id=user_id, is_pending_role=False)
 
        user.role = role
        user.save()
 
        return Response({"detail": "Role updated."})
 
 
class ToggleUserActiveView(APIView):
    """Kept for the existing frontend: flips active <-> suspended. A deactivated account can't be toggled back."""

    permission_classes = [HasRole("accounts.manage_users")]

    def patch(self, request, user_id):
        user = get_object_or_404(User, id=user_id, is_pending_role=False)
        if user.account_status == "deactivated":
            return Response({"detail": "Account is deactivated and can't be reactivated."}, status=400)
        user.account_status = "suspended" if user.is_active else "active"
        user.is_active = user.account_status == "active"
        user.save(update_fields=["account_status", "is_active"])
        if user.is_active:
            end_replacements(user)
        return Response({"detail": "Activated." if user.is_active else "Suspended.", "is_active": user.is_active,
                         "account_status": user.account_status})


def active_responsibilities(user):
    """What must be handed over (via the personnel-change workflow) before a permanent deactivation."""
    from datetime import date
    from django.db.models import Q
    from personnel.models import ProjectAssignment

    today = date.today()
    return {
        "programs": user.led_programs.filter(status="active").count(),
        "projects": user.led_projects.filter(status="active").count(),
        "studies": user.led_studies.filter(status="active").count(),
        "assignments": ProjectAssignment.objects.filter(user=user).filter(Q(end_date__isnull=True) | Q(end_date__gte=today)).count(),
    }


def end_replacements(user):
    """A replacement only covers a suspension, so reactivating or deactivating the user ends it."""
    from django.utils import timezone

    TemporaryReplacement.objects.filter(suspended_user=user, ended_at__isnull=True).update(ended_at=timezone.now())


class UserAccountStatusView(APIView):
    """POST {"action": "suspend" | "reactivate" | "deactivate"}."""

    permission_classes = [HasRole("accounts.manage_users")]

    def post(self, request, user_id):
        user = get_object_or_404(User, id=user_id, is_pending_role=False)
        action = request.data.get("action")
        if action not in ("suspend", "reactivate", "deactivate"):
            return Response({"action": "must be 'suspend', 'reactivate', or 'deactivate'."}, status=400)
        if user.account_status == "deactivated":
            return Response({"detail": "Account is already deactivated (permanent)."}, status=400)
        if action == "deactivate":
            pending = {k: v for k, v in active_responsibilities(user).items() if v}
            if pending:
                return Response({
                    "detail": "Hand over this user's active leadership/assignments through a personnel change first.",
                    "active": pending,
                }, status=400)
        user.account_status = {"suspend": "suspended", "reactivate": "active", "deactivate": "deactivated"}[action]
        user.is_active = user.account_status == "active"
        user.save(update_fields=["account_status", "is_active"])
        if action != "suspend":
            end_replacements(user)
        return Response({"id": user.id, "account_status": user.account_status, "is_active": user.is_active})


class UsersByRoleView(generics.ListAPIView):
    serializer_class = UserListSerializer
    permission_classes = [HasRole("accounts.view_users_by_role")]

    def get_queryset(self):
        code = self.request.query_params.get("code")
        qs = User.objects.filter(is_pending_role=False, is_active=True)
        if code:
            qs = qs.filter(role__code=code)
        return qs


class AuditLogListView(generics.ListAPIView):
    serializer_class = AuditLogSerializer
    permission_classes = [HasRole("accounts.manage_users")]

    def get_queryset(self):
        qs = AuditLog.objects.select_related("actor").all()
        actor_id = self.request.query_params.get("actor")
        method = self.request.query_params.get("method")
        if actor_id:
            qs = qs.filter(actor_id=actor_id)
        if method:
            qs = qs.filter(method=method.upper())
        return qs


class PermissionMatrixView(APIView):
    """Read-only role x permission matrix from the seeded tables (client clarification Q2). Editing is future work."""

    permission_classes = [HasRole("accounts.manage_users")]

    def get(self, request):
        grants = {}
        for permission_code, role_code in RolePermission.objects.values_list("permission__code", "role__code"):
            grants.setdefault(permission_code, []).append(role_code)
        permissions = [
            {"code": p.code, "module": p.module, "name": p.name, "roles": sorted(grants.get(p.code, []))}
            for p in Permission.objects.order_by("module", "code")
        ]
        return Response({"roles": list(Role.objects.order_by("id").values_list("code", flat=True)), "permissions": permissions})


class UserScopeView(APIView):
    """PATCH {"campus": "...", "college": "..."}. Both are enforced against Project.campus/college
    for campus-scoped roles (accounts.permissions.scoped_projects)."""

    permission_classes = [HasRole("accounts.manage_users")]

    def patch(self, request, user_id):
        user = get_object_or_404(User, id=user_id, is_pending_role=False)
        serializer = UserScopeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        scope = dict(user.scope or {})
        for key, value in serializer.validated_data.items():
            if value:
                scope[key] = value
            else:
                scope.pop(key, None)
        user.scope = scope
        user.save(update_fields=["scope"])
        return Response({"id": user.id, "scope": user.scope})


class TemporaryReplacementListCreateView(generics.ListCreateAPIView):
    """Temporary replacements for suspended users (client clarification Q3). ?suspended_user=<id>, ?current=true."""

    serializer_class = TemporaryReplacementSerializer
    permission_classes = [HasRole("accounts.manage_users")]

    def get_queryset(self):
        from datetime import date

        qs = TemporaryReplacement.objects.select_related("suspended_user", "replacement").order_by("-start_date", "-id")
        suspended_user = self.request.query_params.get("suspended_user")
        if suspended_user:
            qs = qs.filter(suspended_user_id=suspended_user)
        if self.request.query_params.get("current") == "true":
            today = date.today()
            qs = qs.filter(ended_at__isnull=True, start_date__lte=today, end_date__gte=today)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class TemporaryReplacementDetailView(generics.RetrieveUpdateAPIView):
    queryset = TemporaryReplacement.objects.all()
    serializer_class = TemporaryReplacementSerializer
    permission_classes = [HasRole("accounts.manage_users")]


class TemporaryReplacementEndView(APIView):
    """POST: end a replacement early."""

    permission_classes = [HasRole("accounts.manage_users")]

    def post(self, request, pk):
        from django.utils import timezone

        replacement = get_object_or_404(TemporaryReplacement, pk=pk)
        if replacement.ended_at:
            return Response({"detail": "This replacement has already ended."}, status=400)
        replacement.ended_at = timezone.now()
        replacement.save(update_fields=["ended_at"])
        return Response(TemporaryReplacementSerializer(replacement).data)
