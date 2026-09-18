import requests as http
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils.crypto import get_random_string
from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User, Role
from .serializers import RoleSerializer, PendingUserSerializer, UserListSerializer
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
    permission_classes = [HasRole(["system_admin"])]
    queryset = User.objects.filter(is_pending_role=True)


class UsersListView(generics.ListAPIView):
    serializer_class = UserListSerializer
    permission_classes = [HasRole(["system_admin"])]
    queryset = User.objects.filter(is_pending_role=False)


class AssignRoleView(APIView):
    permission_classes = [HasRole(["system_admin"])]

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
    permission_classes = [HasRole(["system_admin"])]
 
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
    permission_classes = [HasRole(["system_admin"])]
 
    def patch(self, request, user_id):
        user = get_object_or_404(User, id=user_id, is_pending_role=False)
        user.is_active = not user.is_active
        user.save()
 
        return Response({"detail": "Activated." if user.is_active else "Deactivated.", "is_active": user.is_active})