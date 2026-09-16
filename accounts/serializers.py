from dj_rest_auth.serializers import UserDetailsSerializer
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework import serializers
from .models import Role


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ["id", "code", "name"]


class CustomUserDetailsSerializer(UserDetailsSerializer):
    role = RoleSerializer(read_only=True)
    is_pending_role = serializers.BooleanField(read_only=True)

    class Meta(UserDetailsSerializer.Meta):
        fields = UserDetailsSerializer.Meta.fields + ("role", "is_pending_role")


class RoleTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["role"] = user.role.code if user.role else None
        token["role_tier"] = user.role.tier if user.role else None
        token["is_pending_role"] = user.is_pending_role
        return token