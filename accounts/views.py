import requests as http
from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import F
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken

from .models import PROFILE_EDIT_LIMIT, AuditLog, Permission, Role, RolePermission, TemporaryReplacement, User
from .serializers import (
    AuditLogSerializer, RoleSerializer, PendingUserSerializer, RegistrationProfileSerializer, SelfProfileSerializer,
    TemporaryReplacementSerializer, UserListSerializer, UserProfileSerializer, UserScopeSerializer,
)
from .permissions import HasRole
from config.concurrency import lock
from .emails import (
    notify_admins_new_registration, send_rejection_email, send_role_confirmation_email, send_verification_email,
)
from .tokens import email_verification_token


def log_public_action(request, user, status_code):
    """AuditLogMiddleware logs only signed-in requests; registration and verification are anonymous, so they are
    logged here with the account itself as the actor (client 2026-10-27)."""
    AuditLog.objects.create(
        actor=user, method=request.method, path=request.path[:500], status_code=status_code,
        ip_address=request.META.get("REMOTE_ADDR"),
    )


class RegisterView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "register"

    def post(self, request):
        email = request.data.get("email", "").strip().lower()
        first_name = request.data.get("first_name", "").strip()
        last_name = request.data.get("last_name", "").strip()
        password = request.data.get("password")
        password2 = request.data.get("password2")

        if not email or not password or not password2:
            return Response({"detail": "Email and password are required."}, status=400)
        if not first_name or not last_name:
            return Response({"detail": "First and last name are required."}, status=400)
        if password != password2:
            return Response({"detail": "Passwords do not match."}, status=400)
        if User.objects.filter(email=email).exists():
            return Response({"detail": "Email already registered."}, status=400)
        profile = RegistrationProfileSerializer(data=request.data)
        if not profile.is_valid():
            return Response(profile.errors, status=400)
        try:
            validate_password(password, User(email=email, first_name=first_name, last_name=last_name))
        except DjangoValidationError as error:
            return Response({"password": error.messages}, status=400)

        username = f"{email.split('@')[0]}_{get_random_string(5)}"
        try:
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name[:150],
                last_name=last_name[:150],
                is_active=False,
                is_pending_role=True,
                registration_method="email",
                **profile.validated_data,
            )
        except IntegrityError:  # the same e-mail or Staff ID registered at the same moment
            return Response({"detail": "Email or Staff ID already registered."}, status=400)

        # Approach C (client 2026-10-27): the e-mail is verified first; admins hear about it only after that.
        send_verification_email(user)
        log_public_action(request, user, 201)

        return Response({
            "detail": "Registration received. Open the link we sent to your e-mail within 48 hours to verify it.",
        }, status=201)


class VerifyEmailView(APIView):
    """POST {uid, token} from the e-mailed link. Verifies the address once; then the System Admin is notified."""

    permission_classes = [AllowAny]
    throttle_scope = "verify"
    INVALID = "This link is invalid, already used or expired. Log in to see your account's status or ask for a new link."

    @transaction.atomic
    def post(self, request):
        try:
            user_id = int(force_str(urlsafe_base64_decode(str(request.data.get("uid", "")))))
        except (TypeError, ValueError, OverflowError):
            return Response({"detail": self.INVALID}, status=400)
        user = User.objects.select_for_update().filter(pk=user_id).first()
        if user is None or not email_verification_token.check_token(user, str(request.data.get("token", ""))):
            return Response({"detail": self.INVALID}, status=400)

        user.email_verified_at = timezone.now()
        user.save(update_fields=["email_verified_at"])
        log_public_action(request, user, 200)
        transaction.on_commit(lambda: notify_admins_new_registration(user))
        return Response({"detail": "Your e-mail is verified. The System Admin will review your registration."})


class ResendVerificationView(APIView):
    """POST {email}. Always the same answer, so it doesn't reveal which addresses are registered."""

    permission_classes = [AllowAny]
    throttle_scope = "resend"

    def post(self, request):
        email = str(request.data.get("email", "")).strip()
        user = User.objects.filter(
            email__iexact=email, email_verified_at__isnull=True, is_pending_role=True, account_status="active",
        ).first() if email else None
        if user:
            send_verification_email(user)
        return Response({"detail": "If that e-mail is registered and not yet verified, we sent it a new link."})


class GoogleRequestView(APIView):
    """Google sign-up: the same registration fields as e-mail sign-up except the password (client 2026-10-27).
    Supabase/Google already proved the address, so the registration goes straight to the System Admin's Pending list."""

    permission_classes = [AllowAny]
    throttle_scope = "google"

    def post(self, request):
        token = request.data.get("supabase_access_token")
        first_name = request.data.get("first_name", "").strip()
        last_name = request.data.get("last_name", "").strip()

        if not token:
            return Response({"detail": "Missing token."}, status=400)
        if not first_name or not last_name:
            return Response({"detail": "First and last name are required."}, status=400)

        resp = http.get(
            f"{settings.SUPABASE_URL}/auth/v1/user",
            headers={"Authorization": f"Bearer {token}", "apikey": settings.SUPABASE_PUBLISHABLE_KEY},
        )
        if resp.status_code != 200:
            return Response({"detail": "Invalid Supabase token."}, status=401)

        supa_user = resp.json()
        email = supa_user["email"].strip().lower()
        supabase_uid = supa_user["id"]

        if User.objects.filter(email__iexact=email).exists():
            return Response({"detail": "Request received. Please wait for confirmation."}, status=201)
        profile = RegistrationProfileSerializer(data=request.data)
        if not profile.is_valid():
            return Response(profile.errors, status=400)

        username = f"{email.split('@')[0]}_{get_random_string(5)}"
        try:
            user = User(
                username=username,
                email=email,
                supabase_uid=supabase_uid,
                first_name=first_name[:150],
                last_name=last_name[:150],
                is_active=False,
                is_pending_role=True,
                registration_method="google",
                email_verified_at=timezone.now(),
                **profile.validated_data,
            )
            user.set_unusable_password()
            user.save()
        except IntegrityError:  # the same e-mail, Google account or Staff ID registered at the same moment
            return Response({"detail": "Email or Staff ID already registered."}, status=400)
        log_public_action(request, user, 201)
        notify_admins_new_registration(user)

        return Response({"detail": "Request received. Please wait for confirmation."}, status=201)


class GoogleExchangeView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "google"

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


class RegistrationOptionsView(APIView):
    """Dropdowns for the public registration form (client 2026-10-27): the fixed campuses, the System Admin's College
    Units and the roles that can be requested (not System Admin)."""

    permission_classes = [AllowAny]

    def get(self, request):
        from research_projects.models import CollegeUnit

        return Response({
            "campuses": [value for value, _label in User.CAMPUS_CHOICES],
            "college_units": list(CollegeUnit.objects.values_list("name", flat=True)),
            "roles": RoleSerializer(Role.objects.exclude(code="system_admin").order_by("id"), many=True).data,
            "genders": [{"value": value, "label": label} for value, label in User.GENDER_CHOICES],
        })


class RolesListView(generics.ListAPIView):
    serializer_class = RoleSerializer
    permission_classes = [AllowAny]
    queryset = Role.objects.all()


class PendingUsersListView(generics.ListAPIView):
    """Registrations waiting for the System Admin: e-mail verified, not yet approved or rejected (client 2026-10-27)."""

    serializer_class = PendingUserSerializer
    permission_classes = [HasRole("accounts.manage_users")]
    queryset = User.objects.filter(is_pending_role=True, account_status="active", email_verified_at__isnull=False)


class UsersListView(generics.ListAPIView):
    serializer_class = UserListSerializer
    permission_classes = [HasRole("accounts.manage_users")]
    queryset = User.objects.filter(is_pending_role=False)


class AssignRoleView(APIView):
    permission_classes = [HasRole("accounts.manage_users")]

    @transaction.atomic
    def patch(self, request, user_id):
        role_id = request.data.get("role_id")
        role = get_object_or_404(Role, id=role_id)
        # Locked and pending-only: confirming twice (double click, two admins) can't send two e-mails.
        user = lock(User.objects.all(), id=user_id)
        if user.account_status == "rejected":
            return Response({"detail": "This registration was rejected."}, status=400)
        if not user.is_pending_role:
            return Response({"detail": "This registration was already confirmed."}, status=400)
        if user.email_verified_at is None:
            return Response({"detail": "This e-mail address isn't verified yet."}, status=400)

        user.role = role
        user.is_pending_role = False
        user.is_active = True
        user.save()

        transaction.on_commit(lambda: send_role_confirmation_email(user))  # only once the approval is saved

        return Response({"detail": "Role assigned and confirmation sent."})
    
    
class RejectRegistrationView(APIView):
    """POST {reason?}: the System Admin turns a pending registration down (client 2026-10-27). The account stays a
    never-confirmed registration (is_pending_role) with account_status "rejected", so it is in neither the Pending nor
    the Users list and can't log in; the e-mail can't be registered again."""

    permission_classes = [HasRole("accounts.manage_users")]

    @transaction.atomic
    def post(self, request, user_id):
        user = lock(User.objects.all(), id=user_id)
        if not user.is_pending_role or user.account_status != "active":
            return Response({"detail": "This registration was already decided."}, status=400)
        reason = str(request.data.get("reason", "")).strip()[:1000]

        user.account_status = "rejected"
        user.is_active = False
        user.save(update_fields=["account_status", "is_active"])
        transaction.on_commit(lambda: send_rejection_email(user, reason))

        return Response({"detail": "Registration rejected and the applicant notified."})


class UpdateUserRoleView(APIView):
    permission_classes = [HasRole("accounts.manage_users")]
 
    def patch(self, request, user_id):
        role_id = request.data.get("role_id")
        if not role_id:
            return Response({"detail": "role_id is required."}, status=400)
 
        role = get_object_or_404(Role, id=role_id)
        with transaction.atomic():
            user = lock(User.objects.all(), id=user_id, is_pending_role=False)
            user.role = role
            user.save(update_fields=["role"])
 
        return Response({"detail": "Role updated."})
 
 
class ToggleUserActiveView(APIView):
    """Kept for the existing frontend: flips active <-> suspended. A deactivated account can't be toggled back."""

    permission_classes = [HasRole("accounts.manage_users")]

    @transaction.atomic
    def patch(self, request, user_id):
        user = lock(User.objects.all(), id=user_id, is_pending_role=False)
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

    @transaction.atomic
    def post(self, request, user_id):
        user = lock(User.objects.all(), id=user_id, is_pending_role=False)
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


class UserProfileView(APIView):
    """PATCH {first_name, last_name, office, position, staff_id, gender, campus, college_unit, mobile_number}: the admin
    fills in who an account is, for the people pickers and the Annex A endorser auto-fill (client meeting 2026-10-01;
    registration fields 2026-10-27)."""

    permission_classes = [HasRole("accounts.manage_users")]

    def patch(self, request, user_id):
        user = get_object_or_404(User, id=user_id)
        serializer = UserProfileSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserListSerializer(user).data)


PROFILE_LIMIT_MESSAGE = (
    f"You have used all {PROFILE_EDIT_LIMIT} profile edits. Ask the RMIS System Admin to change your profile."
)


class SelfProfileView(APIView):
    """GET/PATCH auth/profile/: the signed-in user's own profile (client 2026-10-28), always request.user. A PATCH
    sends first_name, last_name, gender and mobile_number; each successful one uses one of PROFILE_EDIT_LIMIT edits.
    The save is one conditional UPDATE, so two concurrent saves can't both use the last edit."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(SelfProfileSerializer(request.user).data)

    def patch(self, request):
        user = request.user
        if user.profile_edit_count >= PROFILE_EDIT_LIMIT:
            return Response({"detail": PROFILE_LIMIT_MESSAGE}, status=403)
        serializer = SelfProfileSerializer(user, data=request.data)
        serializer.is_valid(raise_exception=True)
        saved = User.objects.filter(pk=user.pk, profile_edit_count__lt=PROFILE_EDIT_LIMIT).update(
            **serializer.validated_data, profile_edit_count=F("profile_edit_count") + 1,
        )
        if not saved:
            return Response({"detail": PROFILE_LIMIT_MESSAGE}, status=403)
        user.refresh_from_db()
        return Response(SelfProfileSerializer(user).data)


class UserScopeView(APIView):
    """PATCH {"campus": "...", "college": "..."}. Both are enforced against Project.campus/college
    for campus-scoped roles (accounts.permissions.scoped_projects). campus is stored on User.campus."""

    permission_classes = [HasRole("accounts.manage_users")]

    def patch(self, request, user_id):
        user = get_object_or_404(User, id=user_id, is_pending_role=False)
        serializer = UserScopeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        if "campus" in data:
            user.campus = data.pop("campus") or ""
        scope = dict(user.scope or {})
        scope.pop("campus", None)  # campus lives on User.campus since 2026-10-27
        for key, value in data.items():
            if value:
                scope[key] = value
            else:
                scope.pop(key, None)
        user.scope = scope
        user.save(update_fields=["scope", "campus"])
        return Response({"id": user.id, "scope": user.scope, "campus": user.campus})


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
        with transaction.atomic():
            return self._end(lock(TemporaryReplacement.objects.all(), pk=pk))

    def _end(self, replacement):
        from django.utils import timezone

        if replacement.ended_at:
            return Response({"detail": "This replacement has already ended."}, status=400)
        replacement.ended_at = timezone.now()
        replacement.save(update_fields=["ended_at"])
        return Response(TemporaryReplacementSerializer(replacement).data)
