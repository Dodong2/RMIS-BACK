from dj_rest_auth.jwt_auth import get_refresh_view
from dj_rest_auth.views import LoginView, LogoutView, PasswordChangeView, UserDetailsView
from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import TokenVerifyView

# dj-rest-auth's routes minus password reset: its reset flow crashed (NoReverseMatch) and sends through Django SMTP,
# which RMIS doesn't use (e-mail goes through Brevo). No frontend screen uses it.
auth_urlpatterns = [
    path("login/", LoginView.as_view(), name="rest_login"),
    path("logout/", LogoutView.as_view(), name="rest_logout"),
    path("user/", UserDetailsView.as_view(), name="rest_user_details"),
    path("password/change/", PasswordChangeView.as_view(), name="rest_password_change"),
    path("token/verify/", TokenVerifyView.as_view(), name="token_verify"),
    path("token/refresh/", get_refresh_view().as_view(), name="token_refresh"),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include(auth_urlpatterns)),
    path("api/", include("accounts.urls")),
    path("api/", include("research_projects.urls")),
    path("api/personnel/", include("personnel.urls")),
    path("api/budget/", include("budget_lib.urls")),
    path("api/financial/", include("financial_monitoring.urls")),
    path("api/compliance/", include("compliance.urls")),
    path("api/documents/", include("document_management.urls")),
    path("api/outputs/", include("outputs.urls")),
    path("api/monitoring/", include("monitoring.urls")),
    path("api/dashboard/", include("dashboard.urls")),
    path("api/forecasting/", include("forecasting.urls")),
    path("api/decision-support/", include("decision_support.urls")),
    path("api/risk/", include("risk_indicators.urls")),
    path("api/reports/", include("reports.urls")),
    path("api/budget-sync/", include("budget_sync.urls")),
]