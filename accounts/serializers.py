from dj_rest_auth.serializers import UserDetailsSerializer
from rest_framework import serializers
from .models import AuditLog, Role, User


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ["id", "code", "name"]


class CustomUserDetailsSerializer(UserDetailsSerializer):
    role = RoleSerializer(read_only=True)
    is_pending_role = serializers.BooleanField(read_only=True)

    class Meta(UserDetailsSerializer.Meta):
        fields = UserDetailsSerializer.Meta.fields + ("role", "is_pending_role", "is_active", "office", "position")


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