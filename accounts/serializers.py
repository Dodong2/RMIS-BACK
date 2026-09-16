from rest_framework_simplejwt.serializers import TokenObtainPairSerializer


class RoleTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["role"] = user.role.code if user.role else None
        token["role_tier"] = user.role.tier if user.role else None
        token["is_pending_role"] = user.is_pending_role
        return token