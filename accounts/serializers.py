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
        fields = UserDetailsSerializer.Meta.fields + ("role", "is_pending_role", "is_active")


class PendingUserSerializer(serializers.ModelSerializer):
    requested_role = RoleSerializer(read_only=True)

    class Meta:
        model = User
        fields = ["id", "email", "registration_method", "requested_role", "date_joined"]


class UserListSerializer(serializers.ModelSerializer):
    role = RoleSerializer(read_only=True)

    class Meta:
        model = User
        fields = ["id", "email", "role", "is_active", "date_joined"]


class AuditLogSerializer(serializers.ModelSerializer):
    actor_email = serializers.CharField(source="actor.email", read_only=True, default=None)

    class Meta:
        model = AuditLog
        fields = ["id", "actor", "actor_email", "method", "path", "status_code", "ip_address", "created_at"]