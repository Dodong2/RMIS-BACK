from datetime import date

from dj_rest_auth.serializers import LoginSerializer, UserDetailsSerializer
from rest_framework import serializers
from .models import AuditLog, Role, TemporaryReplacement, User


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ["id", "code", "name"]


class CustomUserDetailsSerializer(UserDetailsSerializer):
    role = RoleSerializer(read_only=True)
    is_pending_role = serializers.BooleanField(read_only=True)

    class Meta(UserDetailsSerializer.Meta):
        fields = UserDetailsSerializer.Meta.fields + ("role", "is_pending_role", "is_active", "office", "position")


class EmailLoginSerializer(LoginSerializer):
    """Registration stores e-mails lowercased, but login matched them exactly, so "Leader@lspu.edu.ph" (phones
    auto-capitalize) failed as a wrong password. Swap in the stored spelling before authenticating."""

    def validate_email(self, value):
        user = User.objects.filter(email__iexact=value.strip()).only("email").first() if value else None
        return user.email if user else value


class PendingUserSerializer(serializers.ModelSerializer):
    requested_role = RoleSerializer(read_only=True)

    class Meta:
        model = User
        fields = ["id", "email", "registration_method", "requested_role", "date_joined"]


class UserListSerializer(serializers.ModelSerializer):
    role = RoleSerializer(read_only=True)

    class Meta:
        model = User
        fields = ["id", "email", "role", "office", "position", "scope", "is_active", "account_status", "date_joined"]


class UserScopeSerializer(serializers.Serializer):
    """Admin-assigned scope (client clarification Q2/Q12). A blank or null value clears that key."""

    campus = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=100)
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

    class Meta:
        model = AuditLog
        fields = ["id", "actor", "actor_email", "method", "path", "status_code", "ip_address", "created_at"]

class TemporaryReplacementSerializer(serializers.ModelSerializer):
    suspended_user_email = serializers.EmailField(source="suspended_user.email", read_only=True)
    replacement_email = serializers.EmailField(source="replacement.email", read_only=True)
    is_current = serializers.SerializerMethodField()

    class Meta:
        model = TemporaryReplacement
        fields = [
            "id", "suspended_user", "suspended_user_email", "replacement", "replacement_email", "designation",
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
