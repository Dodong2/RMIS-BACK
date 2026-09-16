import requests
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from accounts.models import User
from accounts.serializers import RoleTokenObtainPairSerializer


class RoleTokenObtainPairView(TokenObtainPairView):
    serializer_class = RoleTokenObtainPairSerializer


class GoogleExchangeView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        token = request.data.get("supabase_access_token")
        if not token:
            return Response({"detail": "Missing token."}, status=400)

        resp = requests.get(
            f"{settings.SUPABASE_URL}/auth/v1/user",
            headers={
                "Authorization": f"Bearer {token}",
                "apikey": settings.SUPABASE_ANON_KEY,
            },
        )
        if resp.status_code != 200:
            return Response({"detail": "Invalid Supabase token."}, status=401)

        supa_user = resp.json()
        email = supa_user["email"]
        supabase_uid = supa_user["id"]

        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "username": email.split("@")[0],
                "supabase_uid": supabase_uid,
                "is_pending_role": True,
            },
        )
        if created:
            user.set_unusable_password()
            user.save()

        refresh = RefreshToken.for_user(user)
        refresh["role"] = user.role.code if user.role else None
        refresh["role_tier"] = user.role.tier if user.role else None
        refresh["is_pending_role"] = user.is_pending_role

        return Response({
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "is_pending_role": user.is_pending_role,
        })