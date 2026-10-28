from datetime import date

from dj_rest_auth.jwt_auth import CookieTokenRefreshSerializer
from dj_rest_auth.serializers import LoginSerializer, UserDetailsSerializer
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from .models import PROFILE_EDIT_LIMIT, AuditLog, Role, TemporaryReplacement, User


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ["id", "code", "name"]


class CustomUserDetailsSerializer(UserDetailsSerializer):
    role = RoleSerializer(read_only=True)
    is_pending_role = serializers.BooleanField(read_only=True)
    has_password = serializers.SerializerMethodField()  # False for Google accounts: no local password to change

    class Meta(UserDetailsSerializer.Meta):
        fields = UserDetailsSerializer.Meta.fields + (
            "role", "is_pending_role", "is_active", "office", "position", "has_password",
        )
        # PATCH auth/user/ used to change the name with no limit; self-service edits go through auth/profile/ now.
        read_only_fields = fields

    def get_has_password(self, user):
        return user.has_usable_password()


class EmailLoginSerializer(LoginSerializer):
    """Registration stores e-mails lowercased, but login matched them exactly, so "Leader@lspu.edu.ph" (phones
    auto-capitalize) failed as a wrong password. Swap in the stored spelling before authenticating."""

    def validate_email(self, value):
        user = User.objects.filter(email__iexact=value.strip()).only("email").first() if value else None
        return user.email if user else value

    def validate(self, attrs):
        """With the right password, say why an inactive account can't log in (client 2026-10-27); with a wrong one,
        keep the generic error so it doesn't reveal anything."""
        try:
            return super().validate(attrs)
        except serializers.ValidationError:
            user = User.objects.filter(email=attrs.get("email")).first()
            if user and not user.is_active and user.check_password(attrs.get("password") or ""):
                state, message = login_block(user)
                raise serializers.ValidationError({"detail": message, "account_state": state})
            raise


def login_block(user):
    """(account_state, message) for an account that can't log in yet or anymore."""
    if user.account_status == "rejected":
        return "rejected", "Your registration was not approved. Contact the RMIS System Admin."
    if user.account_status == "suspended":
        return "suspended", "Your account is suspended. Contact the RMIS System Admin."
    if user.account_status == "deactivated":
        return "deactivated", "This account has been deactivated."
    if user.email_verified_at is None:
        return "unverified", f"Verify your e-mail first: open the link we sent to {user.email}, or ask for a new one."
    return "pending_approval", "Your e-mail is verified. Your registration is waiting for the System Admin's approval."


class RefreshSerializer(CookieTokenRefreshSerializer):
    """A refresh token of a deleted account answered 500 (SimpleJWT's .get raised DoesNotExist); now 401."""

    def validate(self, attrs):
        try:
            return super().validate(attrs)
        except User.DoesNotExist:
            raise AuthenticationFailed("No active account found for the given token.", "no_active_account")


PROFILE_FIELDS = ["staff_id", "gender", "campus", "college_unit", "mobile_number"]


def validate_college_unit(value):
    from research_projects.models import CollegeUnit

    if value and not CollegeUnit.objects.filter(name=value).exists():
        raise serializers.ValidationError("Pick a College Unit from the list.")
    return value


class RegistrationProfileSerializer(serializers.ModelSerializer):
    """The registration fields besides name, e-mail and password (client 2026-10-27). All required; System Admin
    can't be requested, only assigned."""

    requested_role = serializers.PrimaryKeyRelatedField(
        queryset=Role.objects.exclude(code="system_admin"),
        error_messages={"does_not_exist": "Pick one of the listed roles.", "incorrect_type": "Pick one of the listed roles."},
    )

    class Meta:
        model = User
        fields = [*PROFILE_FIELDS, "requested_role"]
        extra_kwargs = {field: {"required": True, "allow_blank": False} for field in PROFILE_FIELDS}

    validate_college_unit = staticmethod(validate_college_unit)


class PendingUserSerializer(serializers.ModelSerializer):
    requested_role = RoleSerializer(read_only=True)
    full_name = serializers.CharField(source="display_name", read_only=True)

    class Meta:
        model = User
        fields = ["id", "email", "full_name", "registration_method", "requested_role", "date_joined", *PROFILE_FIELDS]


class UserListSerializer(serializers.ModelSerializer):
    role = RoleSerializer(read_only=True)
    full_name = serializers.CharField(source="display_name", read_only=True)

    class Meta:
        model = User
        fields = [
            "id", "email", "full_name", "first_name", "last_name", "role", "office", "position", "scope", "is_active",
            "account_status", "date_joined", *PROFILE_FIELDS,
        ]


class UserProfileSerializer(serializers.ModelSerializer):
    """Admin edit of the name/office/position shown in people pickers and Annex A (client meeting 2026-10-01)."""

    class Meta:
        model = User
        fields = ["first_name", "last_name", "office", "position", *PROFILE_FIELDS]

    validate_college_unit = staticmethod(validate_college_unit)

    def validate_staff_id(self, value):
        return value or None  # cleared = NULL, so several accounts without one don't clash on the unique column


SELF_PROFILE_FIELDS = ["first_name", "last_name", "gender", "mobile_number"]


class SelfProfileSerializer(serializers.ModelSerializer):
    """The signed-in user's own Profile page (client 2026-10-28). Only name, gender and mobile can be changed, all
    four sent and filled in, at least one really changed. Campus and College Unit stay read-only: campus is the
    project scope of campus-level roles and a Project Leader's project campus, so only the System Admin sets them."""

    role = RoleSerializer(read_only=True)
    edits_left = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "email", "role", *SELF_PROFILE_FIELDS, "staff_id", "campus", "college_unit", "registration_method",
            "profile_edit_count", "edits_left",
        ]
        read_only_fields = [field for field in fields if field not in SELF_PROFILE_FIELDS]
        extra_kwargs = {field: {"required": True, "allow_blank": False} for field in SELF_PROFILE_FIELDS}

    def get_edits_left(self, user):
        return max(0, PROFILE_EDIT_LIMIT - user.profile_edit_count)

    def validate(self, attrs):
        locked = set(self.initial_data) - set(SELF_PROFILE_FIELDS)
        if locked:
            raise serializers.ValidationError({key: "This field can't be changed on your profile." for key in sorted(locked)})
        if all(attrs[field] == getattr(self.instance, field) for field in SELF_PROFILE_FIELDS):
            raise serializers.ValidationError("Nothing changed. Change at least one field.")
        return attrs


class UserScopeSerializer(serializers.Serializer):
    """Admin-assigned scope (client clarification Q2/Q12). A blank or null value clears that key. campus is the
    account's User.campus (one of the 4 campuses, client 2026-10-27); college stays in User.scope."""

    campus = serializers.ChoiceField(choices=User.CAMPUS_CHOICES, required=False, allow_blank=True, allow_null=True)
    college = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=100)

    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({key: "Unknown scope key." for key in sorted(unknown)})
        if not attrs:
            raise serializers.ValidationError("Send at least one of: campus, college.")
        return attrs


class AuditLogSerializer(serializers.ModelSerializer):
    actor_email = serializers.CharField(source="actor.email", read_only=True, default=None)
    actor_name = serializers.CharField(source="actor.display_name", read_only=True, default=None)

    class Meta:
        model = AuditLog
        fields = ["id", "actor", "actor_email", "actor_name", "method", "path", "status_code", "ip_address", "error_detail", "created_at"]

class TemporaryReplacementSerializer(serializers.ModelSerializer):
    suspended_user_email = serializers.EmailField(source="suspended_user.email", read_only=True)
    replacement_email = serializers.EmailField(source="replacement.email", read_only=True)
    replacement_name = serializers.CharField(source="replacement.display_name", read_only=True)
    is_current = serializers.SerializerMethodField()

    class Meta:
        model = TemporaryReplacement
        fields = [
            "id", "suspended_user", "suspended_user_email", "replacement", "replacement_email", "replacement_name", "designation",
            "coverage", "start_date", "end_date", "basis", "created_by", "created_at", "ended_at", "is_current",
        ]
        read_only_fields = ["created_by", "ended_at"]

    def get_is_current(self, obj):
        return obj.ended_at is None and obj.start_date <= date.today() <= obj.end_date

    def validate(self, attrs):
        suspended = attrs.get("suspended_user", getattr(self.instance, "suspended_user", None))
        replacement = attrs.get("replacement", getattr(self.instance, "replacement", None))
        start = attrs.get("start_date", getattr(self.instance, "start_date", None))
        end = attrs.get("end_date", getattr(self.instance, "end_date", None))
        if self.instance is None and suspended.account_status != "suspended":
            raise serializers.ValidationError({"suspended_user": "Only a suspended account can have a temporary replacement."})
        if replacement == suspended:
            raise serializers.ValidationError({"replacement": "A user can't replace themselves."})
        if replacement.account_status != "active" or replacement.is_pending_role:
            raise serializers.ValidationError({"replacement": "The replacement must be an active, confirmed account."})
        if start and end and start > end:
            raise serializers.ValidationError({"end_date": "End date cannot be before the start date."})
        return attrs
