from django.contrib import admin
from django.urls import path, include
from accounts.views import RoleTokenObtainPairView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/login/", RoleTokenObtainPairView.as_view()),
    path("api/auth/", include("dj_rest_auth.urls")),
    path("api/auth/registration/", include("dj_rest_auth.registration.urls")),
    path("api/auth/", include("accounts.urls")),
]