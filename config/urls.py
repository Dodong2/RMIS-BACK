from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("dj_rest_auth.urls")),
    path("api/", include("accounts.urls")),
    path("api/", include("research_projects.urls")),
    path("api/personnel/", include("personnel.urls")),
]