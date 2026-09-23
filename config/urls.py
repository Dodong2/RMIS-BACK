from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("dj_rest_auth.urls")),
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
]